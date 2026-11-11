"""Focused contract tests for diagnostic report orchestration."""

from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from backend.config import DEFAULT_OPENAI_BASE_URL
from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)
from backend.sync import session_rebundle

_OTHER_TABLES = (
    "sync_jobs",
    "provider_refresh_history",
    "planned_units",
    "activity_records",
    "activity_sessions",
    "observations",
    "provider_records",
    "sleep_periods",
    "zone_configurations",
    "power_curve_points",
)


class _Database:
    def __init__(self):
        self.queries = []
        self.values = {
            "messages": 3,
            "workout_library": 4,
            "competitions": 5,
            "athlete_checkins": 6,
            "activity_feedback": 7,
            "change_history": 8,
        }

    def execute(self, query, parameters=()):
        self.queries.append((query, parameters))
        if query == "PRAGMA user_version":
            return SimpleNamespace(fetchone=lambda: {"user_version": 25})
        if any(table in query for table in _OTHER_TABLES):
            return SimpleNamespace(fetchall=list, fetchone=lambda: {"count": 0})
        table = query.rsplit("FROM ", 1)[1]
        if table.startswith("kv WHERE key IN"):
            return SimpleNamespace(
                fetchall=lambda: [
                    {"key": "garmin_state", "bytes": 4096},
                    {"key": "diagnostic_capture_entries", "bytes": 12},
                ]
            )
        count = self.values[table]
        return SimpleNamespace(fetchone=lambda: {"count": count})


class _DatabaseManager:
    def __init__(self, database):
        self.database = database
        self.transactions = 0

    @contextmanager
    def read_snapshot(self):
        self.transactions += 1
        yield self.database


class DiagnosticReportServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = _Database()
        self.manager = _DatabaseManager(self.db)
        self.values = {
            "last_sync_error": "fake-api-key-secret",
            "last_external_calendar_sync_at": "calendar-time",
            "last_external_calendar_sync_error": "",
        }
        self.key_values = Mock()
        self.key_values.get.side_effect = lambda _db, key: self.values.get(key)
        self.redactor = Mock()
        self.redactor.redact_text.side_effect = lambda value: value.replace(
            "fake-api-key-secret", "[REDACTED]"
        )
        self.garmin_projection = Mock()
        self.garmin_projection.public_state.return_value = {
            "configured": True,
            "status": "ready",
        }
        self.calendar_reader = Mock()
        self.calendar_reader.event_counts.return_value = {"total": 400, "upcoming": 320}
        self.profile = Mock()
        self.profile.get.return_value = {"name": "private athlete"}
        self.freshness = Mock()
        self.freshness.current.return_value = [
            {"provider": "intervals", "state": "fresh"}
        ]
        self.coverage = Mock()
        self.coverage.coverage.return_value = ()
        self.capture = Mock()
        self.capture.status.return_value = {"active": True, "entries": 1}
        self.capture.entries.return_value = [
            {"operation": "body_battery", "shape": ["bodyBattery"]}
        ]

        self.service = DiagnosticReportService(
            DiagnosticReportDependencies(
                database_manager=self.manager,
                key_values=self.key_values,
                config=SimpleNamespace(
                    openai_api_key="fake-openai-secret",
                    openai_base_url="https://proxy.invalid/fake-base-secret/v1",
                    wahoo_configured=False,
                    intervals_api_key="fake-intervals-secret",
                    calendar_ical_url="https://calendar.invalid/fake-token",
                    garmin_tokenstore="/does-not-exist/fake-token-store",
                    sync_history_earliest_date=date(2020, 1, 1),
                ),
                settings=SimpleNamespace(
                    selected_model=lambda: "gpt-test",
                    selected_thinking_level=lambda: "medium",
                    available_model_options=lambda: [{"id": "gpt-test"}],
                ),
                app_name="Test Coach",
                app_version="1.2.3",
                utc_now=lambda: "2026-09-23T10:00:00Z",
                garmin_projection=self.garmin_projection,
                garmin_client_factory=SimpleNamespace(available=lambda: True),
                garmin_fixture_loader=SimpleNamespace(path=lambda: None),
                provider_state=SimpleNamespace(
                    summary=lambda provider: {"provider": provider}
                ),
                coach_history=SimpleNamespace(
                    history=lambda: [{"status": "completed"}]
                ),
                redactor=self.redactor,
                provider_freshness=self.freshness,
                profile=self.profile,
                garmin_sync_state=SimpleNamespace(core_error_entries=list),
                external_calendar_sync=SimpleNamespace(running=lambda: False),
                external_calendar_reader=self.calendar_reader,
                morning_checkin=SimpleNamespace(state=lambda: {"status": "waiting"}),
                workout_library_sync_state=SimpleNamespace(
                    summary=lambda: {"local": 2}
                ),
                canonical_coverage=self.coverage,
                recent_logs=SimpleNamespace(report_entries=lambda: [{"event": "safe"}]),
                diagnostic_capture=self.capture,
            )
        )

    def test_report_shape_counts_redaction_and_privacy(self):
        report = self.service.report()

        self.assertEqual(report["generated_at"], "2026-09-23T10:00:00Z")
        self.assertEqual(report["app"], {"name": "Test Coach", "version": "1.2.3"})
        self.assertEqual(
            set(report),
            {
                "generated_at",
                "app",
                "runtime",
                "configuration",
                "openai",
                "coach_commands",
                "sync",
                "garmin",
                "provider_freshness",
                "external_calendar",
                "morning_checkin",
                "database",
                "wahoo",
                "plan_sync",
                "canonical_coverage",
                "canonical_backfill",
                "canonical_read",
                "canonical_session_conflicts",
                "canonical_provider_composition",
                "local_load",
                "stream_backfill",
                "fit_inventory",
                "session_metrics",
                "activity_weather",
                "activity_routes",
                "session_analysis",
                "session_focus_backfill",
                "profile_weekly_plan_removal",
                "session_rebundle",
                "logs",
                "debug_capture",
                "note",
            },
        )
        self.assertEqual(
            report["canonical_coverage"], {"status": "available", "providers": []}
        )
        self.assertEqual(report["canonical_backfill"], {"status": "unavailable"})
        # Counts only, per recording origin and sport; empty before any file (#2220).
        self.assertEqual(report["fit_inventory"], {})
        self.assertEqual(report["canonical_read"], {"status": "unavailable"})
        self.assertEqual(
            report["canonical_session_conflicts"],
            {
                "total": 0,
                "sessions": [],
                "link_kinds": {},
            },
        )
        self.assertEqual(set(report["sync"]), {"last_error", "providers"})
        self.assertEqual(
            report["sync"]["providers"],
            {
                provider: {"last_sync_at": None, "last_plan_sync_at": None}
                for provider in ("garmin", "wahoo", "intervals")
            },
        )
        self.assertEqual(
            report["database"],
            {
                "schema_version": 25,
                "messages": 3,
                "workout_library": 4,
                "competitions": 5,
                "athlete_checkins": 6,
                "activity_feedback": 7,
                "change_history": 8,
                "stored_payload_bytes": {
                    "garmin_state": 4096,
                    "garmin_snapshot_legacy": 0,
                    "diagnostic_capture_entries": 12,
                },
                "workout_library_state": {"local": 2},
                "external_calendar_events": 400,
            },
        )
        self.assertEqual(report["external_calendar"]["events"], 320)
        self.assertEqual(report["sync"]["last_error"], "[REDACTED]")
        self.assertEqual(
            report["debug_capture"]["entries"], self.capture.entries.return_value
        )
        self.calendar_reader.event_counts.assert_called_once_with(self.db)
        self.calendar_reader.list_events.assert_not_called()
        self.profile.get.assert_called_once_with()
        self.assertEqual(
            self.freshness.current.call_args.kwargs["profile"],
            {"name": "private athlete"},
        )

        serialized = str(report)
        for private in (
            "fake-openai-secret",
            "fake-provider-secret",
            "fake-intervals-secret",
            "fake-token",
            "private athlete",
        ):
            self.assertNotIn(private, serialized)

    def test_note_states_what_the_capture_keeps(self):
        note = self.service.report()["note"]

        # Non-OpenAI requests and all responses: shape only. OpenAI requests may
        # carry Coach context. Entries expire after seven days.
        self.assertIn("nur als Form gespeichert", note)
        self.assertIn("Anfragen an OpenAI können", note)
        self.assertIn("7 Tage", note)
        self.assertNotIn("Athleteninhalte", note)

    def test_database_counts_and_kv_reads_share_one_read_snapshot(self):
        self.service.report()

        self.assertEqual(self.manager.transactions, 1)
        count_queries = [
            query
            for query, _parameters in self.db.queries
            if query != "PRAGMA user_version"
            and not any(table in query for table in _OTHER_TABLES)
        ]
        # The provider composition adds five reads (sessions, observations and
        # three domain tables) to the same snapshot; the stream backfill counts
        # add two (Garmin records, the stream cursor); the provider sync times add
        # two (refresh history, push jobs); the schema version adds one.
        self.assertEqual(len(self.db.queries), 23)
        self.assertEqual(
            [query.rsplit("FROM ", 1)[1] for query in count_queries],
            [
                "messages",
                "workout_library",
                "competitions",
                "athlete_checkins",
                "activity_feedback",
                "change_history",
                "kv WHERE key IN (?, ?, ?)",
                "provider_sync_cursors WHERE provider=? AND stream=?",
            ],
        )
        # Two extra reads: the Garmin configured signal checks the token blob and
        # the disconnect marker inside the same snapshot (see transactions above).
        # One more reads the local load state (card M6).
        # The stream backfill reads its state once (the read stops at the fake db).
        # The session focus backfill state and the weekly plan removal state are one more read each.
        # The Wahoo block reads the token record and the last sync time and error.
        # The session rebundle state is one more read, the FIT inventory one more (#2220).
        self.assertEqual(self.key_values.get.call_count, 18)

    def test_payload_sizes_count_utf8_bytes_without_fetching_the_payload(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            for table in self.db.values:
                db.execute(f"CREATE TABLE {table} (id INTEGER)")
            db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
            self.assertEqual(
                self.service._database_counts(db)["stored_payload_bytes"],
                {
                    "garmin_state": 0,
                    "garmin_snapshot_legacy": 0,
                    "diagnostic_capture_entries": 0,
                },
            )

            payload = '{"value":"\u00e4\U0001f6b2"}'
            db.executemany(
                "INSERT INTO kv (key, value) VALUES (?, ?)",
                [
                    ("garmin_state", payload),
                    ("garmin_snapshot_legacy", payload * 2),
                    ("diagnostic_capture_entries", "[]"),
                    # The retired key of the former byte count is not measured.
                    ("garmin_snapshot", payload),
                    ("synthetic_other_value", "x" * 10000),
                ],
            )
            sizes = self.service._database_counts(db)["stored_payload_bytes"]
            self.assertEqual(
                sizes,
                {
                    "garmin_state": len(payload.encode("utf-8")),
                    "garmin_snapshot_legacy": 2 * len(payload.encode("utf-8")),
                    "diagnostic_capture_entries": 2,
                },
            )
            self.assertGreater(sizes["garmin_state"], len(payload))
            self.key_values.get.assert_not_called()

    def test_removed_snapshot_fields_are_absent(self):
        report = self.service.report()

        self.assertNotIn("snapshot_counts", report["sync"])
        self.assertNotIn("last_success", report["sync"])
        self.assertNotIn("garmin_snapshot_bytes", report["database"])

    def test_clear_delegates_to_diagnostic_capture(self):
        self.capture.clear.return_value = {"ok": True, "entries": 0}

        result = self.service.clear()

        self.assertEqual(result, {"ok": True, "entries": 0})
        self.capture.clear.assert_called_once_with()

    def test_diagnostic_capture_is_snapshotted_before_the_read_snapshot(self):
        self.capture.entries.side_effect = lambda: (
            self.assertEqual(self.manager.transactions, 0)
            or [{"operation": "body_battery", "shape": ["bodyBattery"]}]
        )
        self.capture.status.side_effect = lambda: (
            self.assertEqual(self.manager.transactions, 0)
            or {
                "active": True,
                "entries": 1,
            }
        )

        self.service.report()

        self.assertEqual(self.manager.transactions, 1)

    def test_schema_version_wahoo_state_and_base_url_flag_carry_no_secrets(self):
        self.service._deps.config.wahoo_configured = True
        self.values["wahoo_oauth_tokens"] = json.dumps(
            {
                "access_token": "fake-wahoo-access-secret",
                "refresh_token": "fake-wahoo-refresh-secret",
                "expires_at": "2026-09-23T09:00:00+00:00",
                "scope": "workouts_read user_read",
                "connected_at": "2026-09-01T09:00:00+00:00",
            }
        )
        self.values["last_wahoo_sync_at"] = "2026-09-23T08:00:00+00:00"
        self.values["last_wahoo_sync_error"] = "fake-api-key-secret rejected"

        report = self.service.report()

        self.assertEqual(report["database"]["schema_version"], 25)
        self.assertEqual(
            report["wahoo"],
            {
                "configured": True,
                "connected": True,
                "scope": "workouts_read user_read",
                "access_token": "expired",
                "last_wahoo_sync_at": "2026-09-23T08:00:00+00:00",
                "last_wahoo_sync_error": "[REDACTED] rejected",
            },
        )
        self.assertIs(report["configuration"]["openai_base_url_custom"], True)
        serialized = json.dumps(report)
        for private in (
            "fake-wahoo-access-secret",
            "fake-wahoo-refresh-secret",
            "fake-base-secret",
            "proxy.invalid",
            "2026-09-23T09:00:00+00:00",
        ):
            self.assertNotIn(private, serialized)

    def test_default_openai_endpoint_is_not_custom(self):
        self.service._deps.config.openai_base_url = DEFAULT_OPENAI_BASE_URL

        report = self.service.report()

        self.assertIs(report["configuration"]["openai_base_url_custom"], False)
        self.assertEqual(
            report["wahoo"],
            {
                "configured": False,
                "connected": False,
                "scope": None,
                "access_token": None,
                "last_wahoo_sync_at": None,
                "last_wahoo_sync_error": None,
            },
        )

    def test_a_failing_section_is_unavailable_and_the_report_still_builds(self):
        self.service._deps.morning_checkin.state = Mock(side_effect=RuntimeError("x"))
        self.service._deps.workout_library_sync_state.summary = Mock(
            side_effect=sqlite3.DatabaseError("malformed row")
        )
        # K-009: a malformed stored rebundle state fails only its own section.
        self.values[session_rebundle.STATE_KEY] = '{"counts": {"days": "malformed"}}'

        report = self.service.report()

        self.assertEqual(report["morning_checkin"], {"status": "unavailable"})
        self.assertEqual(report["database"], {"status": "unavailable"})
        self.assertEqual(report["session_rebundle"], {"status": "unavailable"})
        self.assertEqual(report["app"]["version"], "1.2.3")
        self.assertEqual(report["wahoo"]["connected"], False)

    def test_a_failing_garmin_section_keeps_the_configuration(self):
        self.garmin_projection.public_state.side_effect = RuntimeError("x")

        report = self.service.report()

        self.assertEqual(report["garmin"], {"status": "unavailable"})
        self.assertIsNone(report["configuration"]["garmin_configured"])
        self.assertIn("openai_base_url_custom", report["configuration"])

    def test_log_files_are_read_before_the_read_snapshot(self):
        self.service._deps = replace(
            self.service._deps,
            recent_logs=SimpleNamespace(
                report_entries=lambda: (
                    self.assertEqual(self.manager.transactions, 0)
                    or [{"event": "safe"}]
                )
            ),
        )

        report = self.service.report()

        self.assertEqual(report["logs"], [{"event": "safe"}])
        self.assertEqual(self.manager.transactions, 1)


if __name__ == "__main__":
    unittest.main()
