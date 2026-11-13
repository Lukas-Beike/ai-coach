"""Intervals.icu events of deleted or replaced units are removed by the explicit sync."""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import Mock

from support import temp_database

from backend.coach.proposal_creation import (
    _approved_plan_sync_arguments,
    _plan_sync_approval_details,
)
from backend.db import row_factory
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning.intervals_orphans import find_intervals_orphans, sync_entries
from backend.planning.push_state import attach_push_state
from backend.sync.plan_selection import StructuredPlanSyncService

OLD, NEW, LIVE, PAST, PLAIN = (
    f"{n}" * 8 + "-1111-4111-8111-" + f"{n}" * 12 for n in "12345"
)
TODAY = date(2026, 11, 9)
UNIT = {
    "sport": "VirtualRide",
    "name": "Lockeres Indoor-Rad",
    "date": "2026-11-11",
    "remote_event_id": "evt-1",
}


class IntervalsOrphanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "orphans.sqlite", row_factory=row_factory, schema=True
        )

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

    def test_a_live_unit_that_no_longer_qualifies_keeps_its_event_untouched(
        self,
    ) -> None:
        # Only indoor rides go to Intervals.icu (#2419): the event of a live run
        # is no orphan and never waits, while a deleted run's event is removed.
        self.insert(LIVE, {**UNIT, "sport": "Run"})
        self.insert(PLAIN, {**UNIT, "sport": "Run", "local_deleted": True})

        self.assertEqual([PLAIN], self.orphans())
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT local_id, payload, sync_state FROM planned_units WHERE local_id=?",
                (LIVE,),
            ).fetchall()
        pairs = [(row[0], json.loads(row[0]["payload"]))]
        attach_push_state(pairs, {}, today=TODAY)
        self.assertFalse(pairs[0][1]["push_pending"]["intervals"])

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

    def test_the_nearest_events_come_first_and_every_upcoming_unit_carries_them(
        self,
    ) -> None:
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
            [True, True], ["push_cleanup" in payload for _row, payload in pairs]
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
            {NEW: "VirtualRide", OLD: "Wird bei Intervals.icu entfernt"},
            {item["id"]: item["sport"] for item in details},
        )

    def test_a_turn_bound_sync_also_removes_the_replaced_units_event(self) -> None:
        # The Coach replaces a ride by a run on the same day and sends the run:
        # the ride's event goes too, or Intervals.icu keeps it in Garmin (#2373).
        self.insert(NEW, {**UNIT, "sport": "Run", "remote_event_id": ""})
        self.insert(OLD, {**UNIT, "archived": True, "local_deleted": True})

        for scope, key in (
            ("created", "_created_sync_entry_ids"),
            ("changed", "_changed_sync_entry_ids"),
            ("selected", "_replacement_sync_entry_ids"),
        ):
            with self.subTest(key=key):
                approved = self.selected({"request": {"sync_scope": scope}, key: [NEW]})
                self.assertEqual(
                    [NEW, OLD],
                    [
                        entry.get("library_workout_id") or entry.get("local_id")
                        for entry in approved["entries"]
                    ],
                )
        all_pending = self.selected(
            {"request": {"sync_scope": "all_pending"}, "_sync_all_pending": True}
        )
        self.assertEqual(1, len(all_pending["entries"]))

    def test_a_turn_of_skipped_units_still_removes_the_replaced_units_event(
        self,
    ) -> None:
        # The Coach replaces a synced ride by a run: Intervals.icu takes the run
        # no more, yet the replaced ride's event must still go (#2419).
        self.insert(NEW, {**UNIT, "sport": "Run", "remote_event_id": ""})
        self.insert(OLD, {**UNIT, "archived": True, "local_deleted": True})
        intent = {
            "request": {"sync_scope": "created"},
            "_created_sync_entry_ids": [],
            "_skipped_sync_entry_ids": [NEW],
        }
        approved = _approved_plan_sync_arguments(
            {"entries": []}, intent, self.manager, TODAY
        )
        self.assertEqual(
            [OLD], [entry["library_workout_id"] for entry in approved["entries"]]
        )
        authority = Mock()
        authority.intervals_skipped.return_value = set()
        queue = Mock()
        queue.enqueue.return_value = {"ok": True}
        service = StructuredPlanSyncService(self.manager, authority, queue, 366)

        prepared = service.prepare(approved["entries"], intent)
        service.execute(prepared, [], reason="created")

        self.assertEqual(
            [OLD],
            [entry["library_workout_id"] for entry in queue.enqueue.call_args.args[0]],
        )
        # Nothing but leftovers is admitted once the turn's own units were skipped.
        outside = {"library_workout_id": NEW, "expected_payload_hash": "c" * 64}
        with self.assertRaises(AppError) as raised:
            service.prepare([outside], intent)
        self.assertEqual("intent_scope_denied", raised.exception.reason)

    def test_sync_entries_carry_the_hash_the_job_checks(self) -> None:
        self.insert(OLD, {**UNIT, "archived": True})
        with self.manager.reader() as db:
            orphans = find_intervals_orphans(db, TODAY)[0]

        self.assertEqual(
            ["planned_unit"], [entry["entity"] for entry in sync_entries(orphans)]
        )


if __name__ == "__main__":
    unittest.main()
