from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend import privacy as privacy_module
from backend.privacy import PrivacyDataExportDependencies, PrivacyDataExportService
from backend.weather import cache as weather_cache


class _Lock:
    def __init__(self):
        self.active = False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, *_exc):
        self.active = False


class _Database:
    def __init__(self, lock):
        self.lock = lock
        self.queries = []

    def execute(self, query, _params=()):
        if not self.lock.active:
            raise AssertionError("SQL read escaped DB_LOCK")
        self.queries.append(query)
        if "FROM kv ORDER BY key" in query:
            return _Rows(
                [
                    {"key": "profile", "value": "{}"},
                    {"key": "garmin_snapshot", "value": "{}"},
                    {"key": weather_cache.CACHE_KEY, "value": "{}"},
                    {"key": "ordinary", "value": "{broken"},
                    {"key": "sync_running", "value": "true"},
                    {"key": "sync_status", "value": "active"},
                ]
            )
        return _Rows([])


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Manager:
    def __init__(self, lock, db):
        self.lock = lock
        self.db = db
        self.entries = 0

    @contextmanager
    def unit_of_work(self):
        if not self.lock.active:
            raise AssertionError("unit of work entered without DB_LOCK")
        self.entries += 1
        yield self.db


class PrivacyDataExportServiceTests(unittest.TestCase):
    def test_local_projection_keeps_shared_uow_and_separate_snapshot_reads(self):
        lock = _Lock()
        db = _Database(lock)
        manager = _Manager(lock, db)

        class KeyValues:
            def get(self, current_db, key):
                self_outer.assertIs(current_db, db)
                self_outer.assertTrue(lock.active)
                return "{malformed" if key == "garmin_snapshot" else "[]"

        class EmptyService:
            def list(self, *_args, **_kwargs):
                return []

            def context(self):
                return {}

            def latest_preview(self):
                return None

            def status(self):
                return {}

        class Profile:
            def get(self):
                return {"timezone": "UTC"}

        class Calendar:
            def list_events(self):
                return []

        class PublicCalendar:
            @staticmethod
            def state(current_db):
                self_outer.assertIs(current_db, db)
                self_outer.assertTrue(lock.active)
                return {}

        self_outer = self
        service = PrivacyDataExportService(
            PrivacyDataExportDependencies(
                database_manager=manager,
                database_lock=lock,
                key_value_repository=KeyValues(),
                profile_service=Profile(),
                workout_library_service=EmptyService(),
                competition_service=EmptyService(),
                training_plan_service=EmptyService(),
                checkin_service=EmptyService(),
                activity_feedback_service=EmptyService(),
                adaptive_preview_service=EmptyService(),
                external_calendar_reader=Calendar(),
                local_now=lambda: datetime(2026, 9, 23, tzinfo=timezone.utc),
                utc_now=lambda: "2026-09-23T00:00:00+00:00",
            )
        )

        # The public calendar projection is imported directly from its owner;
        # patch it here to verify its position inside the shared DB boundary.
        with patch("backend.privacy.public_event_calendar.state", PublicCalendar.state):
            exported = service.export()

        self.assertEqual(manager.entries, 3)
        self.assertEqual(len(db.queries), 5)
        self.assertEqual(exported["application_state"], {"ordinary": "{broken"})
        self.assertEqual(exported["garmin_snapshot"], {})
        self.assertEqual(exported["weather_cache"], [])
        self.assertNotIn("sync_running", exported["application_state"])
        self.assertNotIn("sync_status", exported["application_state"])
        self.assertFalse(lock.active)

    def test_backend_module_has_no_server_dependency_and_old_wrapper_is_absent(self):
        import server

        source = Path(privacy_module.__file__)
        self.assertNotIn("import server", source.read_text(encoding="utf-8"))
        self.assertFalse(hasattr(server, "privacy_export"))
        self.assertTrue(callable(server.privacy_data_export_service))


if __name__ == "__main__":
    unittest.main()
