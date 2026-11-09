"""Intervals.icu events of deleted or replaced units are removed by the explicit sync."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.coach.proposal_creation import (
    _approved_plan_sync_arguments,
    _plan_sync_approval_details,
)
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.planning import library as planning_library
from backend.planning.intervals_orphans import find_intervals_orphans, sync_entries
from backend.planning.push_state import attach_push_state

OLD, NEW, LIVE, PAST, PLAIN = (
    f"{n}" * 8 + "-1111-4111-8111-" + f"{n}" * 12 for n in "12345"
)
TODAY = date(2026, 11, 9)
UNIT = {
    "sport": "Ride",
    "name": "Lockeres Indoor-Rad",
    "date": "2026-11-11",
    "remote_event_id": "evt-1",
}


class IntervalsOrphanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.directory.name) / "orphans.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.manager.close)

    def insert(self, local_id: str, payload: dict, state: str = "local") -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, sync_state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '2026-11-01', '2026-11-01')",
                (local_id, local_id, json.dumps(payload), state),
            )

    def orphans(self) -> list[str]:
        with self.manager.reader() as db:
            return [item.local_id for item in find_intervals_orphans(db, TODAY)[0]]

    def test_only_hidden_future_units_with_an_event_are_orphans(self) -> None:
        self.insert(OLD, {**UNIT, "archived": True, "local_deleted": True})
        self.insert(LIVE, UNIT)
        self.insert(PAST, {**UNIT, "archived": True, "date": "2026-11-08"})
        self.insert(PLAIN, {**UNIT, "archived": True, "remote_event_id": ""})
        self.insert(NEW, {**UNIT, "archived": True}, state="synced")

        self.assertEqual([OLD], self.orphans())

    def test_the_calendar_lists_the_events_on_a_unit_intervals_waits_for(self) -> None:
        self.insert(OLD, {**UNIT, "local_deleted": True, "archived": True})
        self.insert(NEW, {**UNIT, "remote_event_id": ""})
        with self.manager.reader() as db:
            orphans = find_intervals_orphans(db, TODAY)[0]
            rows = db.execute(
                "SELECT local_id, payload, sync_state FROM planned_units WHERE local_id=?",
                (NEW,),
            ).fetchall()
        pairs = [(row, json.loads(row["payload"])) for row in rows]

        attach_push_state(pairs, {}, intervals_orphans=orphans, today=TODAY)

        self.assertEqual(
            {
                "intervals": [
                    {
                        "id": OLD,
                        "name": "Lockeres Indoor-Rad",
                        "date": "2026-11-11",
                        "hash": orphans[0].payload_hash,
                    }
                ]
            },
            pairs[0][1]["push_cleanup"],
        )

    def test_the_nearest_events_are_removed_first_and_listed_once(self) -> None:
        for index, day in enumerate(("2026-11-20", "2026-11-10", "2026-11-15")):
            self.insert(
                f"{index}" * 8 + "-1111-4111-8111-" + "9" * 12,
                {**UNIT, "archived": True, "date": day},
            )
        self.insert(NEW, {**UNIT, "remote_event_id": "", "date": "2026-11-12"})
        self.insert(LIVE, {**UNIT, "remote_event_id": "", "date": "2026-11-13"})
        with self.manager.reader() as db:
            capped, total = find_intervals_orphans(db, TODAY, limit=2)
            orphans = find_intervals_orphans(db, TODAY)[0]
            rows = db.execute(
                "SELECT local_id, payload, sync_state FROM planned_units WHERE local_id IN (?, ?) ORDER BY local_id",
                (NEW, LIVE),
            ).fetchall()
        pairs = [(row, json.loads(row["payload"])) for row in rows]

        attach_push_state(pairs, {}, intervals_orphans=orphans, today=TODAY)

        self.assertEqual(
            (["2026-11-10", "2026-11-15"], 3), ([o.date for o in capped], total)
        )
        self.assertEqual(
            [True, False], ["push_cleanup" in payload for _row, payload in pairs]
        )

    def selected(self, intent: dict) -> dict:
        arguments = {"entries": [{"local_id": NEW, "expected_payload_hash": "c" * 64}]}
        return _approved_plan_sync_arguments(arguments, intent, self.manager, TODAY)

    def test_a_selected_coach_card_adds_and_lists_the_removals(self) -> None:
        self.insert(NEW, {**UNIT, "remote_event_id": ""})
        self.insert(OLD, {**UNIT, "archived": True})
        with self.manager.reader() as db:
            raw = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (OLD,)
            ).fetchone()["payload"]
        intent = {"request": {"sync_scope": "selected"}}

        approved = self.selected(intent)
        details = _plan_sync_approval_details(approved, intent, self.manager, TODAY)

        self.assertEqual(
            [
                {"local_id": NEW, "expected_payload_hash": "c" * 64},
                {
                    "library_workout_id": OLD,
                    "expected_payload_hash": planning_library.library_payload_hash(raw),
                    "entity": "planned_unit",
                },
            ],
            approved["entries"],
        )
        self.assertEqual(
            {NEW: "Ride", OLD: "Wird bei Intervals.icu entfernt"},
            {item["id"]: item["sport"] for item in details},
        )

    def test_a_turn_bound_sync_gets_no_extra_entries(self) -> None:
        self.insert(NEW, {**UNIT, "remote_event_id": ""})
        self.insert(OLD, {**UNIT, "archived": True})

        for key in ("_replacement_sync_entry_ids", "_changed_sync_entry_ids"):
            with self.subTest(key=key):
                approved = self.selected(
                    {"request": {"sync_scope": "selected"}, key: [NEW]}
                )
                self.assertEqual(1, len(approved["entries"]))

    def test_sync_entries_carry_the_hash_the_job_checks(self) -> None:
        self.insert(OLD, {**UNIT, "archived": True})
        with self.manager.reader() as db:
            orphans = find_intervals_orphans(db, TODAY)[0]

        self.assertEqual(
            ["planned_unit"], [entry["entity"] for entry in sync_entries(orphans)]
        )


if __name__ == "__main__":
    unittest.main()
