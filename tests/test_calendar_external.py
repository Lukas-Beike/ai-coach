import sqlite3
import unittest
from datetime import date, timedelta
from unittest import mock

from support import FakeManager

from backend.calendar.decisions import ExternalCalendarDecisionService
from backend.calendar.external import (
    ExternalCalendarReader,
    event_counts,
    list_events,
    list_events_in_window,
    state,
)
from backend.calendar.local import local_calendar_events
from backend.db.schema import CALENDAR_DECISIONS_DDL, execute_ddl
from backend.errors import AppError
from backend.planning.calendar import calendar_event_has_constraint
from backend.planning.context import build_daily_planning_context


class ExternalCalendarTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE external_calendar_events (
                id TEXT PRIMARY KEY,
                uid TEXT NOT NULL,
                name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                start_local TEXT NOT NULL,
                end_local TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                all_day INTEGER NOT NULL,
                training_relevant INTEGER NOT NULL,
                no_training INTEGER NOT NULL,
                no_intensity INTEGER NOT NULL,
                short_only INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        execute_ddl(self.db, CALENDAR_DECISIONS_DDL)
        self.today = date(2026, 9, 20)

    def tearDown(self):
        self.db.close()

    def add_event(
        self,
        event_id,
        *,
        start="2026-09-21T09:00:00",
        end="2026-09-21T10:00:00",
        relevant=1,
        uid=None,
    ):
        self.db.execute(
            "INSERT INTO external_calendar_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                uid or f"uid-{event_id}",
                f"Event {event_id}",
                start[:10],
                start,
                end,
                60,
                0,
                relevant,
                0,
                0,
                0,
                "updated",
            ),
        )

    def add_kv(self, key, value):
        self.db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, "updated"),
        )

    def test_date_boundary_sorting_and_exact_fields(self):
        self.add_event("after", start="2026-09-22T09:00:00", end="2026-09-22T10:00:00")
        self.add_event(
            "boundary", start="2026-09-20T00:00:00", end="2026-09-20T00:00:00"
        )
        self.add_event("before", start="2026-09-19T23:00:00", end="2026-09-19T23:59:59")
        self.add_event(
            "crossing", start="2026-09-19T23:00:00", end="2026-09-20T00:00:01"
        )
        self.add_event(
            "earlier", start="2026-09-20T08:00:00", end="2026-09-20T09:00:00"
        )

        events = list_events(self.db, today=self.today)

        self.assertEqual(
            ["crossing", "earlier", "after"], [event["id"] for event in events]
        )
        self.assertEqual(
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
                "no_training",
                "no_intensity",
                "short_only",
                "impact",
                "decision_scope",
                "recurring",
                "updated_at",
            },
            set(events[0]),
        )

    def test_training_relevance_filter_is_optional(self):
        self.add_event("relevant", relevant=1)
        self.add_event("irrelevant", relevant=0)

        self.assertEqual(
            ["relevant", "irrelevant"],
            [event["id"] for event in list_events(self.db, today=self.today)],
        )
        self.assertEqual(
            ["relevant"],
            [
                event["id"]
                for event in list_events(
                    self.db, today=self.today, training_relevant_only=True
                )
            ],
        )

    def test_training_relevance_filter_keeps_no_training_blockers(self):
        self.add_event("irrelevant", relevant=0)
        self.db.execute(
            "UPDATE external_calendar_events SET no_training=1 WHERE id='irrelevant'"
        )
        self.assertEqual(
            ["irrelevant"],
            [
                event["id"]
                for event in list_events(
                    self.db, today=self.today, training_relevant_only=True
                )
            ],
        )

    def test_training_relevance_filter_keeps_title_only_no_intensity_markers(self):
        self.add_event("easy-only", relevant=0)
        self.db.execute(
            "UPDATE external_calendar_events SET no_intensity=1 WHERE id='easy-only'"
        )
        self.assertEqual(
            ["easy-only"],
            [
                event["id"]
                for event in list_events(
                    self.db, today=self.today, training_relevant_only=True
                )
            ],
        )

    def test_limit_is_clamped_to_one_and_one_thousand(self):
        for index in range(1002):
            self.add_event(f"event-{index:04d}")

        self.assertEqual(1, len(list_events(self.db, today=self.today, limit=0)))
        self.assertEqual(1000, len(list_events(self.db, today=self.today, limit=2000)))

    def test_event_counts_are_one_uncapped_query_for_total_and_upcoming(self):
        self.assertEqual(
            {"total": 0, "upcoming": 0}, event_counts(self.db, today=self.today)
        )
        for index in range(400):
            self.add_event(f"event-{index:04d}")
        self.add_event("past", start="2026-09-01T09:00:00", end="2026-09-01T10:00:00")
        queries: list[str] = []
        self.db.set_trace_callback(queries.append)

        counts = event_counts(self.db, today=self.today)
        reader = ExternalCalendarReader(FakeManager(self.db), lambda: self.today)

        self.assertEqual({"total": 401, "upcoming": 400}, counts)
        self.assertEqual(counts, reader.event_counts(self.db))
        self.assertEqual(2, sum("COUNT(*)" in query for query in queries))

    def test_window_query_is_not_capped_so_day_markers_see_late_events(self):
        window_start = date(2026, 9, 21)
        for index in range(56):
            day = (window_start + timedelta(days=index)).isoformat()
            self.add_event(
                f"event-{index:02d}", start=f"{day}T09:00:00", end=f"{day}T10:00:00"
            )
        self.add_event(
            "far-future", start="2026-12-01T09:00:00", end="2026-12-01T10:00:00"
        )
        marker_day = window_start + timedelta(days=54)
        self.db.execute(
            "UPDATE external_calendar_events SET no_training=1, training_relevant=0 WHERE id='event-54'"
        )

        events = list_events_in_window(
            self.db, today=self.today, window_days=56, training_relevant_only=True
        )
        self.assertEqual(56, len(events))
        self.assertNotIn("far-future", [event["id"] for event in events])

        days = build_daily_planning_context(
            planned=[],
            checkins=[],
            calendar_events=events,
            weather_days=[],
            recovery_by_date={},
            health_by_date={},
            activity_feedback=[],
            today=self.today,
            calendar_window_days=56,
        )
        marked_dates = [day["date"] for day in days if day.get("no_training")]
        self.assertEqual([marker_day.isoformat()], marked_dates)

    def test_state_projects_fields_and_defaults_missing_kv(self):
        self.add_event("event")

        result = state(
            self.db,
            configured=True,
            running=False,
            today=self.today,
            window_days=56,
        )

        self.assertEqual(
            {
                "configured",
                "provider",
                "read_only",
                "running",
                "last_sync_at",
                "last_error",
                "skipped_events",
                "events",
                "undecided_upcoming",
                "window_days",
            },
            set(result),
        )
        self.assertEqual(
            {
                "configured": True,
                "provider": "iCalendar",
                "read_only": True,
                "running": False,
                "last_sync_at": None,
                "last_error": None,
                "skipped_events": 0,
                "events": list_events(self.db, today=self.today),
                "undecided_upcoming": 1,
                "window_days": 56,
            },
            result,
        )

    def test_state_keeps_kv_values_opaque_and_maps_empty_error_to_none(self):
        self.add_kv("last_external_calendar_sync_at", "not-json")
        self.add_kv("last_external_calendar_sync_error", "")

        result = state(
            self.db,
            configured=False,
            running=True,
            today=self.today,
            window_days=42,
        )

        self.assertEqual("not-json", result["last_sync_at"])
        self.assertIsNone(result["last_error"])
        self.assertFalse(result["configured"])
        self.assertTrue(result["running"])

    def test_state_reports_the_skipped_component_count(self):
        kwargs = {
            "configured": True,
            "running": False,
            "today": self.today,
            "window_days": 56,
        }
        self.add_kv(
            "last_external_calendar_sync_skipped", '{"component": 1, "recurrence": 2}'
        )
        self.assertEqual(state(self.db, **kwargs)["skipped_events"], 3)
        self.db.execute(
            "UPDATE kv SET value = 'not-json' WHERE key = ?",
            ("last_external_calendar_sync_skipped",),
        )
        self.assertEqual(state(self.db, **kwargs)["skipped_events"], 0)

    def test_state_uses_default_event_limit(self):
        for index in range(301):
            self.add_event(f"event-{index:04d}")

        result = state(
            self.db,
            configured=True,
            running=False,
            today=self.today,
            window_days=56,
        )

        self.assertEqual(300, len(result["events"]))

    def test_kv_contract_rejects_null_values(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_kv("last_external_calendar_sync_error", None)

    def test_reader_owns_transactions_for_lists_and_state(self):
        self.add_event("event")
        self.add_kv("last_external_calendar_sync_at", "2026-09-20T12:00:00+00:00")
        reader = ExternalCalendarReader(FakeManager(self.db), lambda: self.today)

        self.assertEqual(reader.list_events()[0]["id"], "event")
        projected = reader.state(configured=True, running=False, window_days=56)
        self.assertEqual(projected["events"][0]["id"], "event")
        self.assertEqual(projected["last_sync_at"], "2026-09-20T12:00:00+00:00")

    def decide(self, uid, start, impact, stamp="2026-09-20T08:00:00+00:00"):
        self.db.execute(
            "INSERT OR REPLACE INTO external_calendar_decisions VALUES (?, ?, ?, ?)",
            (uid, start, impact, stamp),
        )

    def impacts(self, **kwargs):
        return {
            event["id"]: (event["impact"], event["decision_scope"])
            for event in list_events(self.db, today=self.today, **kwargs)
        }

    def test_decisions_override_markers_and_survive_a_feed_refresh(self):
        for index, day in enumerate(("2026-09-21", "2026-09-22", "2026-09-23")):
            self.add_event(
                f"team-{index}",
                start=f"{day}T09:00:00",
                end=f"{day}T10:00:00",
                uid="team",
            )
        self.add_event("marked", start="2026-09-24T09:00:00", end="2026-09-24T10:00:00")
        self.db.execute(
            "UPDATE external_calendar_events SET short_only=1 WHERE id='marked'"
        )
        self.add_event(
            "plain", start="2026-09-25T09:00:00", end="2026-09-25T10:00:00", relevant=0
        )
        self.decide("team", "", "none")
        self.decide("team", "2026-09-22T09:00:00", "block")
        expected = {
            "team-0": ("none", "series"),
            "team-1": ("block", "event"),
            "team-2": ("none", "series"),
            "marked": ("short", None),
            "plain": ("open", None),
        }
        self.assertEqual(expected, self.impacts())
        # The sync deletes and re-inserts every event; decisions stay apart.
        rows = [
            dict(row)
            for row in self.db.execute("SELECT * FROM external_calendar_events")
        ]
        self.db.execute("DELETE FROM external_calendar_events")
        for row in rows:
            self.db.execute(
                f"INSERT INTO external_calendar_events ({', '.join(row)}) "
                f"VALUES ({', '.join('?' for _ in row)})",
                tuple(row.values()),
            )
        self.assertEqual(expected, self.impacts())
        self.assertEqual(
            {"team-1": ("block", "event"), "marked": ("short", None)},
            self.impacts(training_relevant_only=True),
        )
        # A title marker yields to the decision in planning and the calendar.
        self.db.execute(
            "UPDATE external_calendar_events SET name='[NO_TRAINING] Team' "
            "WHERE uid='team'"
        )
        decided = list_events(self.db, today=self.today)
        self.assertFalse(calendar_event_has_constraint(decided[0], "no_training"))
        self.assertTrue(calendar_event_has_constraint(decided[1], "no_training"))
        self.assertEqual(
            ["team-1", "marked"],
            [item["id"] for item in local_calendar_events([], [], decided)],
        )
        blocked = next(
            event
            for event in list_events(self.db, today=self.today)
            if event["id"] == "team-1"
        )
        self.assertEqual(
            (1, 0, 0, 0, 1),
            tuple(
                blocked[key]
                for key in (
                    "no_training",
                    "no_intensity",
                    "short_only",
                    "training_relevant",
                    "recurring",
                )
            ),
        )
        # A moved occurrence is a new event; only the series decision covers it.
        self.db.execute(
            "UPDATE external_calendar_events SET start_local='2026-09-22T11:00:00' "
            "WHERE id='team-1'"
        )
        self.assertEqual(("none", "series"), self.impacts()["team-1"])

    def test_undecided_count_covers_open_events_of_the_next_fourteen_days(self):
        for offset in (-1, 0, 14, 15):
            day = (self.today + timedelta(days=offset)).isoformat()
            self.add_event(
                f"day-{offset}", start=f"{day}T09:00:00", end=f"{day}T10:00:00"
            )
        self.add_event("decided", uid="decided")
        self.decide("decided", "2026-09-21T09:00:00", "none")
        self.add_event("marked")
        self.db.execute(
            "UPDATE external_calendar_events SET no_training=1 WHERE id='marked'"
        )
        result = state(
            self.db, configured=True, running=False, today=self.today, window_days=56
        )
        self.assertEqual(2, result["undecided_upcoming"])

    def service(self):
        followup = mock.Mock()
        followup.check.return_value = {"needs_replan": False, "replan_changes": 0}
        events = mock.Mock()
        service = ExternalCalendarDecisionService(
            FakeManager(self.db), followup, events, lambda: "2026-09-20T08:00:00Z"
        )
        return service, followup, events

    def stored_decisions(self):
        return [
            tuple(row)
            for row in self.db.execute(
                "SELECT uid, occurrence_start, impact FROM external_calendar_decisions "
                "ORDER BY uid, occurrence_start"
            )
        ]

    def test_decision_service_sets_replaces_and_removes_decisions(self):
        self.add_event("one", uid="team")
        self.add_event(
            "two", uid="team", start="2026-09-28T09:00:00", end="2026-09-28T10:00:00"
        )
        service, followup, events = self.service()

        result = service.decide("team", "2026-09-21T09:00:00", "short")

        self.assertEqual(
            {
                "uid": "team",
                "occurrence_start": "2026-09-21T09:00:00",
                "impact": "short",
                "needs_replan": False,
                "replan_changes": 0,
            },
            result,
        )
        followup.check.assert_called_once()
        events.publish.assert_called_once_with("coach", {"status": "changed"})
        service.decide("team", "2026-09-21T09:00:00", "easy")
        self.assertEqual(
            [("team", "2026-09-21T09:00:00", "easy")], self.stored_decisions()
        )
        service.decide("team", None, "block")
        self.assertEqual([("team", "", "block")], self.stored_decisions())
        service.decide("team", "2026-09-28T09:00:00", "none")
        service.decide("team", None, None)
        self.assertEqual([], self.stored_decisions())

    def test_decision_service_rejects_unknown_events_and_values(self):
        self.add_event("one", uid="team")
        service, followup, _events = self.service()
        cases = (
            (("other", None, "block"), 404),
            (("team", "2026-09-22T09:00:00", "block"), 404),
            (("team", None, "maybe"), 400),
            (("", None, "block"), 400),
            ((["team"], None, "block"), 400),
            (("team", None, ["block"]), 400),
            (("team", 5, "block"), 400),
            (("x" * 501, None, "block"), 400),
        )
        for arguments, status in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(AppError) as error:
                    service.decide(*arguments)
                self.assertEqual(status, error.exception.status)
        self.assertEqual([], self.stored_decisions())
        followup.check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
