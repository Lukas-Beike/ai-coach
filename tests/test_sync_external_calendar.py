"""Focused tests for the external iCalendar sync owner."""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.sync.daily import DailySyncMarkerService
from backend.sync.external_calendar import ExternalCalendarSyncService

NOW = "2026-09-20T10:00:00+00:00"
LOCAL = datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Europe/Berlin"))


class TrackingDatabaseManager(DatabaseManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit_calls = 0

    @contextmanager
    def unit_of_work(self):
        self.unit_calls += 1
        with super().unit_of_work() as db:
            yield db


class FakeObserver:
    def __init__(self):
        self.calls = []
        self.scopes = []

    @contextmanager
    def observe(self, provider, area, reason, operation_id):
        scope = type("Scope", (), {"result": None})()
        self.calls.append((provider, area, reason, operation_id))
        self.scopes.append(scope)
        yield scope


class FakePreview:
    def __init__(self, preview=None, status=None, error=None):
        self.preview_value = preview or {"changes": []}
        self.status_value = status or {"needs_replan": False, "replan_changes": 0}
        self.error = error
        self.preview_calls = 0
        self.status_calls = 0

    def preview(self):
        self.preview_calls += 1
        if self.error:
            raise self.error
        return self.preview_value

    def status(self):
        self.status_calls += 1
        return self.status_value


class ExternalCalendarSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = TrackingDatabaseManager(
            Path(self.temporary_directory.name) / "calendar.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE external_calendar_events ("
                "id TEXT PRIMARY KEY, uid TEXT NOT NULL, name TEXT NOT NULL, "
                "event_date TEXT NOT NULL, start_local TEXT NOT NULL, end_local TEXT NOT NULL, "
                "duration_minutes INTEGER NOT NULL, all_day INTEGER NOT NULL DEFAULT 0, "
                "training_relevant INTEGER NOT NULL DEFAULT 1, no_intensity INTEGER NOT NULL DEFAULT 0, "
                "short_only INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, UNIQUE(uid, start_local))"
            )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.daily_markers = DailySyncMarkerService(
            self.manager, self.key_values, lambda: LOCAL
        )
        self.observer = FakeObserver()
        self.preview = FakePreview(
            {"changes": [{"id": 1}, {"id": 2}]},
            {"needs_replan": True, "replan_changes": 2},
        )
        self.events = StateEventBuffer()
        self.lock = threading.Lock()
        self.config = Config(
            port=8090,
            openai_api_key="",
            openai_base_url="https://api.openai.com/v1",
            openai_model="test",
            gemini_api_key="",
            gemini_model="",
            ai_provider="openai",
            intervals_api_key="",
            intervals_athlete_id="",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="https://calendar.example/feed.ics",
            app_password="test-password-123",
            secure_cookies=False,
            data_retention_days=30,
        )
        self.service = self.make_service()
        self.manager.unit_calls = 0

    def tearDown(self):
        self.manager.close()
        self.temporary_directory.cleanup()

    def make_service(self, *, config=None, redactor=None, preview=None, lock=None):
        return ExternalCalendarSyncService(
            config or self.config,
            self.manager,
            self.key_values,
            self.daily_markers,
            self.observer,
            preview or self.preview,
            self.events,
            logging.getLogger("test.external_calendar"),
            redactor or (lambda value: value),
            lambda: LOCAL,
            lambda: NOW,
            "test-version",
            lock=lock or self.lock,
        )

    @staticmethod
    def parsed_event(**overrides):
        return {
            "id": "event-new",
            "uid": "uid-new",
            "name": "Appointment",
            "event_date": "2026-09-21",
            "start_local": "2026-09-21T10:00:00+02:00",
            "end_local": "2026-09-21T11:30:00+02:00",
            "duration_minutes": 90,
            "all_day": False,
            "training_relevant": True,
            "no_intensity": True,
            "short_only": False,
            **overrides,
        }

    def add_existing_event(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events "
                "(id, uid, name, event_date, start_local, end_local, duration_minutes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "event-old",
                    "uid-old",
                    "Old appointment",
                    "2026-09-22",
                    "2026-09-22T10:00:00+02:00",
                    "2026-09-22T11:00:00+02:00",
                    60,
                    NOW,
                ),
            )

    def rows(self):
        with self.manager.unit_of_work() as db:
            return db.execute(
                "SELECT * FROM external_calendar_events ORDER BY id"
            ).fetchall()

    def kv(self, key):
        with self.manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def test_success_replaces_exact_columns_marks_daily_and_publishes_replan(self):
        self.add_existing_event()
        with (
            patch(
                "backend.providers.calendar.external_calendar_url",
                return_value="https://calendar.example/feed.ics",
            ) as validate,
            patch(
                "backend.providers.calendar.fetch_calendar_feed", return_value=b"feed"
            ) as fetch,
            patch(
                "backend.providers.calendar.parse_ical_calendar",
                return_value=[self.parsed_event()],
            ) as parse,
        ):
            result = self.service.sync("manual", "operation-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["window_days"], 56)
        self.assertTrue(result["needs_replan"])
        self.assertEqual(result["replan_changes"], 2)
        validate.assert_called_once_with(self.config.calendar_ical_url)
        fetch.assert_called_once_with(
            "https://calendar.example/feed.ics", app_version="test-version"
        )
        args = parse.call_args.kwargs
        self.assertEqual(args["today"].isoformat(), "2026-09-20")
        self.assertEqual(args["window_start"], args["today"])
        self.assertEqual(args["window_end"].isoformat(), "2026-11-15")
        self.assertEqual(args["local_zone"], LOCAL.tzinfo)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            set(rows[0]),
            {
                "id",
                "uid",
                "name",
                "event_date",
                "start_local",
                "end_local",
                "duration_minutes",
                "all_day",
                "training_relevant",
                "no_intensity",
                "short_only",
                "updated_at",
            },
        )
        self.assertEqual(rows[0]["id"], "event-new")
        self.assertEqual(rows[0]["no_intensity"], 1)
        self.assertEqual(rows[0]["updated_at"], NOW)
        self.assertEqual(self.kv("last_external_calendar_sync_at"), NOW)
        self.assertEqual(self.kv("sync_calendar_last_success_at"), LOCAL.isoformat())
        self.assertEqual(self.kv("last_external_calendar_sync_error"), "")
        self.assertEqual(self.kv("external_calendar_sync_status"), "")
        self.assertEqual(
            self.events.since()["events"][0]["data"], {"status": "changed"}
        )
        self.assertEqual(
            self.observer.calls, [("calendar", "events", "manual", "operation-1")]
        )
        self.assertEqual(self.observer.scopes[0].result, result)

    def test_lock_competition_is_observed_without_provider_or_database_calls(self):
        self.lock.acquire()
        try:
            with (
                patch("backend.providers.calendar.external_calendar_url") as validate,
                patch("backend.providers.calendar.fetch_calendar_feed") as fetch,
            ):
                result = self.service.sync()
            validate.assert_not_called()
            fetch.assert_not_called()
            self.assertEqual(result, {"status": "already_running"})
            self.assertEqual(self.manager.unit_calls, 0)
            self.assertEqual(
                self.observer.calls, [("calendar", "events", "manual", None)]
            )
            self.assertEqual(self.observer.scopes[0].result, result)
        finally:
            self.lock.release()

    def test_missing_url_precedes_held_lock_and_preserves_existing_error(self):
        service = self.make_service(
            config=Config(**{**self.config.__dict__, "calendar_ical_url": ""})
        )
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, "last_external_calendar_sync_error", "older error")
        self.manager.unit_calls = 0
        self.lock.acquire()
        try:
            with self.assertRaises(AppError) as caught:
                service.sync()
            self.assertTrue(service.running())
            self.assertEqual(self.manager.unit_calls, 0)
            self.assertEqual(
                self.observer.calls, [("calendar", "events", "manual", None)]
            )
        finally:
            self.lock.release()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(
            caught.exception.message, "CALENDAR_ICAL_URL ist nicht konfiguriert."
        )
        self.assertEqual(self.kv("last_external_calendar_sync_error"), "older error")

    def test_invalid_app_error_is_redacted_and_preserves_last_good_events(self):
        self.add_existing_event()
        failure = AppError(400, "feed-secret-" + "x" * 1100)
        redacted = []
        service = self.make_service(
            redactor=lambda value: redacted.append(value) or "safe:" + value
        )
        with (
            patch(
                "backend.providers.calendar.external_calendar_url",
                return_value="https://calendar.example/feed.ics",
            ),
            patch(
                "backend.providers.calendar.fetch_calendar_feed", side_effect=failure
            ),
            self.assertRaises(AppError) as caught,
        ):
            service.sync()
        self.assertIs(caught.exception, failure)
        self.assertEqual(redacted, [failure.message])
        self.assertEqual(
            self.kv("last_external_calendar_sync_error"),
            ("safe:" + failure.message)[:1000],
        )
        self.assertEqual([row["id"] for row in self.rows()], ["event-old"])
        self.assertFalse(service.running())

    def test_generic_failure_maps_to_safe_provider_error_and_preserves_cause(self):
        cause = RuntimeError("private feed data")
        with (
            patch(
                "backend.providers.calendar.external_calendar_url", side_effect=cause
            ),
            self.assertRaises(AppError) as caught,
        ):
            self.service.sync()
        self.assertEqual(caught.exception.reason, "provider_client_error")
        self.assertIs(caught.exception.__cause__, cause)
        self.assertEqual(
            self.kv("last_external_calendar_sync_error"),
            "Die Antwort von Der externe Kalender konnte nicht verarbeitet werden.",
        )
        self.assertNotIn(
            "private feed data", self.kv("last_external_calendar_sync_error")
        )

    def test_error_state_persistence_failure_is_not_suppressed(self):
        class FailingErrorRepository:
            def __init__(self, delegate):
                self.delegate = delegate

            def set(self, db, key, value):
                if key == "last_external_calendar_sync_error":
                    raise RuntimeError("synthetic error-state write failure")
                self.delegate.set(db, key, value)

        self.service._key_value_repository = FailingErrorRepository(self.key_values)
        with (
            patch(
                "backend.providers.calendar.external_calendar_url",
                side_effect=AppError(400, "invalid feed"),
            ),
            self.assertRaises(RuntimeError) as caught,
        ):
            self.service.sync()
        self.assertEqual(str(caught.exception), "synthetic error-state write failure")
        self.assertFalse(self.service.running())

    def test_insert_failure_rolls_back_delete_and_keeps_last_good_events(self):
        self.add_existing_event()
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER reject_calendar_insert BEFORE INSERT ON external_calendar_events "
                "BEGIN SELECT RAISE(ABORT, 'synthetic insert failure'); END"
            )
        with (
            patch(
                "backend.providers.calendar.external_calendar_url",
                return_value="https://calendar.example/feed.ics",
            ),
            patch(
                "backend.providers.calendar.fetch_calendar_feed", return_value=b"feed"
            ),
            patch(
                "backend.providers.calendar.parse_ical_calendar",
                return_value=[self.parsed_event()],
            ),
            self.assertRaises(AppError) as caught,
        ):
            self.service.sync()
        self.assertEqual(caught.exception.reason, "provider_client_error")
        self.assertEqual([row["id"] for row in self.rows()], ["event-old"])

    def test_adaptive_preview_failure_uses_status_projection(self):
        fallback = {"needs_replan": True, "replan_changes": 4, "extra": "kept"}
        preview = FakePreview(error=RuntimeError("preview failed"), status=fallback)
        service = self.make_service(preview=preview)
        with (
            patch(
                "backend.providers.calendar.external_calendar_url",
                return_value="https://calendar.example/feed.ics",
            ),
            patch(
                "backend.providers.calendar.fetch_calendar_feed", return_value=b"feed"
            ),
            patch("backend.providers.calendar.parse_ical_calendar", return_value=[]),
        ):
            result = service.sync()
        self.assertEqual(result["needs_replan"], True)
        self.assertEqual(result["replan_changes"], 4)
        self.assertEqual(result["extra"], "kept")
        self.assertEqual((preview.preview_calls, preview.status_calls), (1, 1))

    def test_cleanup_kv_failure_still_releases_module_lock(self):
        class FailingCleanupRepository:
            def __init__(self, delegate):
                self.delegate = delegate

            def set(self, db, key, value):
                if key == "external_calendar_sync_status" and value == "":
                    raise RuntimeError("synthetic cleanup write failure")
                self.delegate.set(db, key, value)

        self.service._key_value_repository = FailingCleanupRepository(self.key_values)
        with (
            patch(
                "backend.providers.calendar.external_calendar_url",
                return_value="https://calendar.example/feed.ics",
            ),
            patch(
                "backend.providers.calendar.fetch_calendar_feed", return_value=b"feed"
            ),
            patch("backend.providers.calendar.parse_ical_calendar", return_value=[]),
            self.assertRaises(RuntimeError) as caught,
        ):
            self.service.sync()
        self.assertEqual(str(caught.exception), "synthetic cleanup write failure")
        self.assertFalse(self.service.running())
        self.assertTrue(self.lock.acquire(blocking=False))
        self.lock.release()


if __name__ == "__main__":
    unittest.main()
