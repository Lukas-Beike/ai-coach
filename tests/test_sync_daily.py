from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.sync.daily import DailySyncMarkerService


class CountingDatabaseManager(DatabaseManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit_of_work_calls = 0

    @contextmanager
    def unit_of_work(self):
        self.unit_of_work_calls += 1
        with super().unit_of_work() as db:
            yield db


class TrackingKeyValueRepository(KeyValueRepository):
    def __init__(self, manager: DatabaseManager):
        super().__init__(lambda: "2026-01-01T00:00:00+00:00")
        self.manager = manager
        self.connections = []

    def get(self, db, key):
        self.connections.append(db)
        if self.manager._unit_of_work.get() is not db:
            raise AssertionError("key/value read did not use the active unit of work")
        return super().get(db, key)

    def set(self, db, key, value):
        self.connections.append(db)
        if self.manager._unit_of_work.get() is not db:
            raise AssertionError("key/value write did not use the active unit of work")
        return super().set(db, key, value)


class FailingKeyValueRepository(TrackingKeyValueRepository):
    def set(self, db, key, value):
        super().set(db, key, value)
        raise RuntimeError("synthetic write failure")


class DailySyncMarkerServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_path = Path(self.temp_directory.name) / "daily-sync.db"
        self.manager = CountingDatabaseManager(
            self.database_path, sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        self.local_time = datetime(
            2026, 9, 20, 8, 15, tzinfo=timezone(timedelta(hours=2))
        )
        self.local_now_calls = 0
        self.repository = TrackingKeyValueRepository(self.manager)
        self.service = DailySyncMarkerService(
            self.manager, self.repository, self.default_local_now
        )

    def default_local_now(self):
        self.local_now_calls += 1
        return self.local_time

    def test_every_allowed_source_is_due_then_marked_for_refresh_interval(self):
        for source in ("intervals", "garmin", "calendar"):
            with self.subTest(source=source):
                self.assertTrue(self.service.is_due(source, self.local_time))
                self.service.mark(source, self.local_time)
                self.assertFalse(self.service.is_due(source, self.local_time))

    def test_explicit_and_default_now_are_supported(self):
        explicit = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)

        self.service.mark("intervals", explicit)
        self.assertFalse(self.service.is_due("intervals", explicit))
        self.assertFalse(self.service.is_due("intervals"))
        self.assertEqual(self.local_now_calls, 1)

        self.service.mark("garmin")
        self.assertEqual(self.local_now_calls, 2)
        self.assertFalse(self.service.is_due("garmin"))
        self.assertEqual(self.local_now_calls, 3)

    def test_timezone_aware_marker_uses_the_same_instant_across_zones(self):
        local = datetime(2026, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=14)))
        same_instant_utc = local.astimezone(timezone.utc)

        self.service.mark("calendar", local)

        with self.manager.unit_of_work() as db:
            self.assertEqual(
                self.repository.get(db, "sync_calendar_last_success_at"),
                "2026-01-01T00:30:00+14:00",
            )
        self.assertFalse(self.service.is_due("calendar", local))
        self.assertFalse(self.service.is_due("calendar", same_instant_utc))

    def test_attempt_suppresses_refresh_for_one_hour(self):
        self.service.mark_attempt("garmin", self.local_time)
        self.assertFalse(self.service.is_due("garmin", self.local_time + timedelta(minutes=59)))
        self.assertTrue(self.service.is_due("garmin", self.local_time + timedelta(hours=1)))

    def test_invalid_sources_raise_value_error_without_key_value_access(self):
        for source in ("activities", "Garmin", "calendar "):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "unknown daily sync source"):
                    self.service.is_due(source, self.local_time)
                with self.assertRaisesRegex(ValueError, "unknown daily sync source"):
                    self.service.mark(source, self.local_time)
        self.assertEqual(self.repository.connections, [])

    def test_marker_persists_and_can_be_read_after_reopening_database(self):
        self.service.mark("intervals", self.local_time)
        self.manager.close()

        reopened_manager = DatabaseManager(
            self.database_path, sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(reopened_manager.close)
        reopened_service = DailySyncMarkerService(
            reopened_manager,
            KeyValueRepository(lambda: "2026-01-01T00:00:00+00:00"),
            lambda: self.local_time,
        )

        self.assertFalse(reopened_service.is_due("intervals", self.local_time))

    def test_nested_unit_of_work_reuses_the_active_connection_and_rolls_back_safely(
        self,
    ):
        initial_calls = self.manager.unit_of_work_calls
        with (
            self.assertRaisesRegex(RuntimeError, "outer rollback"),
            self.manager.unit_of_work() as outer_db,
        ):
            self.service.mark("garmin", self.local_time)
            self.assertIs(self.repository.connections[-1], outer_db)
            self.assertEqual(self.manager.unit_of_work_calls, initial_calls + 2)
            self.assertFalse(self.service.is_due("garmin", self.local_time))
            self.assertIs(self.repository.connections[-1], outer_db)
            raise RuntimeError("outer rollback")

        self.assertTrue(self.service.is_due("garmin", self.local_time))

    def test_write_failure_rolls_back_marker(self):
        failing_repository = FailingKeyValueRepository(self.manager)
        failing_service = DailySyncMarkerService(
            self.manager, failing_repository, self.default_local_now
        )

        with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
            failing_service.mark("calendar", self.local_time)

        self.assertTrue(self.service.is_due("calendar", self.local_time))


if __name__ == "__main__":
    unittest.main()
