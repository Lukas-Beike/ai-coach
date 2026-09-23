import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date

from backend.calendar.external import ExternalCalendarReader, list_events, state


class Manager:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def unit_of_work(self):
        yield self.db


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
    ):
        self.db.execute(
            "INSERT INTO external_calendar_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                f"uid-{event_id}",
                f"Event {event_id}",
                start[:10],
                start,
                end,
                60,
                0,
                relevant,
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
                "no_intensity",
                "short_only",
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

    def test_limit_is_clamped_to_one_and_one_thousand(self):
        for index in range(1002):
            self.add_event(f"event-{index:04d}")

        self.assertEqual(1, len(list_events(self.db, today=self.today, limit=0)))
        self.assertEqual(1000, len(list_events(self.db, today=self.today, limit=2000)))

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
                "events",
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
                "events": list_events(self.db, today=self.today),
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
        reader = ExternalCalendarReader(Manager(self.db), lambda: self.today)

        self.assertEqual(reader.list_events()[0]["id"], "event")
        projected = reader.state(configured=True, running=False, window_days=56)
        self.assertEqual(projected["events"][0]["id"], "event")
        self.assertEqual(projected["last_sync_at"], "2026-09-20T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
