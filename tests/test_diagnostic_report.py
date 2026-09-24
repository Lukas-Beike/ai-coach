"""Focused contract tests for diagnostic report orchestration."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)


class _Lock:
    def __init__(self):
        self.entries = 0

    def __enter__(self):
        self.entries += 1
        return self

    def __exit__(self, *_args):
        return False


class _Database:
    def __init__(self):
        self.queries = []
        self.values = {
            "messages": 3,
            "workout_library": 4,
            "competitions": 5,
            "athlete_checkins": 6,
            "activity_feedback": 7,
        }

    def execute(self, query, parameters=()):
        self.queries.append((query, parameters))
        table = query.rsplit("FROM ", 1)[1]
        return SimpleNamespace(fetchone=lambda: {"count": self.values[table]})


class _DatabaseManager:
    def __init__(self, database):
        self.database = database
        self.transactions = 0

    @contextmanager
    def unit_of_work(self):
        self.transactions += 1
        yield self.database


class DiagnosticReportServiceTests(unittest.TestCase):
    def setUp(self):
        self.lock = _Lock()
        self.db = _Database()
        self.manager = _DatabaseManager(self.db)
        self.values = {
            "last_sync_at": "sync-time",
            "last_sync_error": "fake-api-key-secret",
            "sync_running": "1",
            "last_performance_refresh_at": "refresh-time",
            "last_performance_error": "",
            "performance_refresh_running": "0",
            "last_external_calendar_sync_at": "calendar-time",
            "last_external_calendar_sync_error": "",
        }
        self.key_values = Mock()
        self.key_values.get.side_effect = lambda _db, key: self.values.get(key)
        self.redactor = Mock()
        self.redactor.redact_text.side_effect = lambda value: value.replace(
            "fake-api-key-secret", "[REDACTED]"
        )
        self.sync_state = Mock()
        self.sync_state.latest_snapshot.return_value = {
            "recent_activities": [{}, {}],
            "recent_wellness": [{}],
            "upcoming_calendar": [{}, {}, {}],
            "private_athlete_text": "never projected",
        }
        self.garmin_projection = Mock()
        self.garmin_projection.public_state.return_value = {
            "configured": True,
            "status": "ready",
        }
        self.calendar_reader = Mock()
        self.calendar_reader.list_events.return_value = [{"private_event": "never projected"}]
        self.profile = Mock()
        self.profile.get.return_value = {"name": "private athlete"}
        self.freshness = Mock()
        self.freshness.current.return_value = [{"provider": "intervals", "state": "fresh"}]
        self.capture = Mock()
        self.capture.status.return_value = {"active": True, "entries": 1}
        self.capture.entries.return_value = [{"operation": "body_battery", "shape": ["bodyBattery"]}]

        self.service = DiagnosticReportService(DiagnosticReportDependencies(
            database_manager=self.manager,
            db_lock=self.lock,
            key_values=self.key_values,
            config=SimpleNamespace(
                openai_api_key="fake-openai-secret",
                gemini_api_key="fake-gemini-secret",
                intervals_api_key="fake-intervals-secret",
                calendar_ical_url="https://calendar.invalid/fake-token",
                garmin_tokenstore="/does-not-exist/fake-token-store",
            ),
            settings=SimpleNamespace(
                selected_ai_provider=lambda: "openai",
                selected_model=lambda: "gpt-test",
                selected_thinking_level=lambda: "medium",
                available_model_options=lambda: [{"id": "gpt-test"}],
            ),
            app_name="Test Coach",
            app_version="1.2.3",
            utc_now=lambda: "2026-09-23T10:00:00Z",
            sync_state=self.sync_state,
            garmin_projection=self.garmin_projection,
            garmin_client_factory=SimpleNamespace(available=lambda: True),
            garmin_fixture_loader=SimpleNamespace(path=lambda: None),
            provider_state=SimpleNamespace(summary=lambda provider: {"provider": provider}),
            coach_history=SimpleNamespace(history=lambda: [{"status": "completed"}]),
            redactor=self.redactor,
            provider_freshness=self.freshness,
            profile=self.profile,
            garmin_sync_state=SimpleNamespace(core_error_entries=list),
            external_calendar_sync=SimpleNamespace(running=lambda: False),
            external_calendar_reader=self.calendar_reader,
            morning_checkin=SimpleNamespace(state=lambda: {"status": "waiting"}),
            workout_library_sync_state=SimpleNamespace(summary=lambda: {"local": 2}),
            recent_logs=SimpleNamespace(list=lambda: [{"event": "safe"}]),
            diagnostic_capture=self.capture,
        ))

    def test_report_shape_counts_redaction_and_privacy(self):
        report = self.service.report()

        self.assertEqual(report["generated_at"], "2026-09-23T10:00:00Z")
        self.assertEqual(report["app"], {"name": "Test Coach", "version": "1.2.3"})
        self.assertEqual(set(report), {
            "generated_at", "app", "runtime", "configuration", "openai", "gemini",
            "coach_commands", "sync", "performance_refresh", "garmin", "provider_freshness",
            "external_calendar", "morning_checkin", "database", "logs", "debug_capture", "note",
        })
        self.assertEqual(report["sync"]["snapshot_counts"], {
            "activities": 2, "wellness": 1, "calendar_events": 3,
        })
        self.assertEqual(report["database"], {
            "messages": 3,
            "workout_library": 4,
            "competitions": 5,
            "athlete_checkins": 6,
            "activity_feedback": 7,
            "workout_library_state": {"local": 2},
            "external_calendar_events": 1,
        })
        self.assertEqual(report["external_calendar"]["events"], 1)
        self.assertEqual(report["sync"]["last_error"], "[REDACTED]")
        self.assertEqual(report["debug_capture"]["entries"], self.capture.entries.return_value)
        self.assertEqual(self.calendar_reader.list_events.call_count, 2)
        self.profile.get.assert_called_once_with()
        self.assertEqual(self.freshness.current.call_args.kwargs["profile"], {"name": "private athlete"})

        serialized = str(report)
        for private in (
            "fake-openai-secret", "fake-gemini-secret", "fake-intervals-secret",
            "fake-token", "private athlete", "never projected", "private_event",
        ):
            self.assertNotIn(private, serialized)

    def test_database_counts_and_kv_reads_keep_lock_and_unit_of_work(self):
        self.service.report()

        self.assertEqual(self.manager.transactions, 9)
        self.assertEqual(self.lock.entries, 9)
        self.assertEqual(len(self.db.queries), 5)
        self.assertEqual(
            [query.rsplit("FROM ", 1)[1] for query, _parameters in self.db.queries],
            ["messages", "workout_library", "competitions", "athlete_checkins", "activity_feedback"],
        )
        self.assertEqual(self.key_values.get.call_count, 8)


if __name__ == "__main__":
    unittest.main()
