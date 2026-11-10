"""Equipment items, assignments and maintenance record change history.

Temporary database and synthetic gear only.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from backend import change_history
from backend.athlete.equipment import EquipmentService
from backend.athlete.equipment_history import equipment_history_records
from backend.canonical.activity_summary import ActivitySummary
from backend.coach.change_receipts import change_summary
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService

NOW = "2026-10-02T12:00:00+00:00"
BIKE = {
    "name": "Road bike",
    "sport": "ride",
    "kind": "bike",
    "start_date": "2026-08-01",
    "initial_distance_km": 100,
    "initial_hours": 5,
    "maintenance_km": 500,
}


def ride(identifier: str) -> ActivitySummary:
    return {
        "id": "act_" + identifier,
        "started_at": "2026-09-10T07:00:00+00:00",
        "started_at_local": "2026-09-10T07:00:00",
        "sport": "ride",
        "environment": "unknown",
        "record_ids": {"wahoo": identifier},
        "distance_m": 30000.0,
        "moving_duration_s": 5400.0,
    }


class EquipmentHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "equipment_history.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.summaries = lambda: [ride("w1"), ride("w2")]
        self.service = EquipmentService(
            self.manager,
            self.summaries,
            lambda: date(2026, 10, 2),
            lambda: NOW,
        )

    def collected(self, write: Any) -> tuple[Any, list[dict[str, str]]]:
        with change_history.collect_changes() as changes:
            result = write()
        return result, changes

    def undo(self, changes: list[dict[str, str]]) -> None:
        unused: Any = None
        services = equipment_history_records(lambda: NOW, self.summaries)
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, record_services=services),
            *(unused,) * 6,
            record_services=services,
            profile_mutation_coordinator=threading.RLock(),
        )
        with self.manager.unit_of_work() as db:
            undo.apply_many(db, changes)

    def actions(self, entity_type: str) -> list[str]:
        with self.manager.reader() as db:
            return [
                row["action"]
                for row in db.execute(
                    "SELECT action FROM change_history WHERE entity_type=? "
                    "ORDER BY created_at, rowid",
                    (entity_type,),
                ).fetchall()
            ]

    def stored(self, key: str) -> dict[str, Any] | None:
        with self.manager.reader() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def record(self, key: str) -> dict[str, Any]:
        stored = self.stored(key)
        assert stored is not None
        return stored

    def bike(self, **extra: Any) -> dict[str, Any]:
        return self.service.save({**BIKE, **extra})["equipment"]

    def edit(self, item: dict[str, Any], **changes: Any) -> dict[str, Any]:
        payload = {
            key: item[key]
            for key in (
                *BIKE,
                "id",
                "environment",
                "status",
                "parent_id",
                "lifetime_target_km",
            )
            if key in item
        }
        return self.service.save(
            {**payload, "expected_revision": item["revision"], **changes}
        )["equipment"]

    # Items

    def test_save_records_create_then_update_and_returns_the_reference(self) -> None:
        created = self.service.save(BIKE)
        self.assertEqual(created["change"]["entity_type"], "equipment")
        item = created["equipment"]
        self.edit(item, name="Gravel bike")
        self.assertEqual(self.actions("equipment"), ["create", "update"])

    def test_an_unchanged_save_records_nothing(self) -> None:
        item = self.bike()
        saved = self.service.save(
            {
                **{key: item[key] for key in (*BIKE, "id", "environment")},
                "expected_revision": item["revision"],
            }
        )
        self.assertIsNone(saved["change"])
        self.assertEqual(self.actions("equipment"), ["create"])

    def test_undo_of_a_created_item_removes_it(self) -> None:
        saved, changes = self.collected(lambda: self.service.save(BIKE))
        self.undo(changes)
        self.assertIsNone(self.stored("equipment:" + saved["equipment"]["id"]))

    def test_undo_of_a_created_item_is_refused_once_it_is_used(self) -> None:
        saved, changes = self.collected(lambda: self.service.save(BIKE))
        self.service.maintain(
            {"equipment_id": saved["equipment"]["id"], "date": "2026-10-01"}
        )
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertIsNotNone(self.stored("equipment:" + saved["equipment"]["id"]))

    def test_undo_of_an_edit_restores_values_and_advances_the_revision(self) -> None:
        item = self.bike(lifetime_target_km=3000)
        edited, changes = self.collected(
            lambda: self.edit(
                item, name="Gravel bike", maintenance_km=None, lifetime_target_km=None
            )
        )
        self.undo(changes)
        restored = self.stored("equipment:" + item["id"]) or {}
        for key in ("name", "maintenance_km", "lifetime_target_km", "status", "kind"):
            self.assertEqual(restored[key], item[key], key)
        self.assertEqual(restored["revision"], edited["revision"] + 1)

    def test_undo_of_an_archive_brings_the_item_back(self) -> None:
        item = self.bike()
        _, changes = self.collected(lambda: self.edit(item, status="archived"))
        self.undo(changes)
        self.assertEqual(self.record("equipment:" + item["id"])["status"], "active")

    def test_undo_keeps_garmin_owned_mileage(self) -> None:
        item = self.bike()
        _, changes = self.collected(lambda: self.edit(item, name="Renamed"))
        with self.manager.unit_of_work() as db:
            stored = self.stored("equipment:" + item["id"]) or {}
            stored["garmin_distance_km"] = 1234.5
            db.execute(
                "UPDATE kv SET value=? WHERE key=?",
                (json.dumps(stored), "equipment:" + item["id"]),
            )
        self.undo(changes)
        restored = self.stored("equipment:" + item["id"]) or {}
        self.assertEqual(restored["name"], item["name"])
        self.assertEqual(restored["garmin_distance_km"], 1234.5)

    def test_undo_is_refused_after_a_later_edit(self) -> None:
        item = self.bike()
        _, changes = self.collected(lambda: self.edit(item, name="Gravel bike"))
        later = self.stored("equipment:" + item["id"])
        assert later is not None
        self.edit(later, name="Third name")
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.record("equipment:" + item["id"])["name"], "Third name")

    def test_undo_is_refused_when_the_parent_no_longer_fits(self) -> None:
        first = self.bike(name="First")
        second = self.bike(name="Second")
        part = self.service.save(
            {
                "name": "Chain",
                "sport": "ride",
                "kind": "component",
                "parent_id": first["id"],
                "start_date": "2026-08-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
            }
        )["equipment"]
        _, changes = self.collected(
            lambda: self.edit(
                part,
                parent_id=second["id"],
                kind="component",
                name="Chain",
            )
        )
        self.edit(first, sport="run", kind="shoes")
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(
            self.record("equipment:" + part["id"])["parent_id"], second["id"]
        )

    # Assignments

    def test_assign_records_create_update_and_unassign_each_undoable(self) -> None:
        first, second = self.bike(), self.bike(name="Second")
        self.service.assign({"activity_id": "act_w1", "equipment_id": first["id"]})
        _, moved = self.collected(
            lambda: self.service.assign(
                {"activity_id": "act_w1", "equipment_id": second["id"]}
            )
        )
        self.undo(moved)
        self.assertEqual(
            self.record("equipment_assignment:act_w1")["equipment_id"], first["id"]
        )
        result, unassigned = self.collected(
            lambda: self.service.assign({"activity_id": "act_w1", "equipment_id": None})
        )
        self.assertEqual(result["change"]["entity_type"], "equipment_assignment")
        self.assertIsNone(self.record("equipment_assignment:act_w1")["equipment_id"])
        self.undo(unassigned)
        self.assertEqual(
            self.record("equipment_assignment:act_w1")["equipment_id"], first["id"]
        )
        self.assertEqual(
            self.actions("equipment_assignment"),
            ["create", "update", "undo", "update", "undo"],
        )

    def test_undo_of_a_first_unassignment_removes_the_override(self) -> None:
        _, changes = self.collected(
            lambda: self.service.assign({"activity_id": "act_w1", "equipment_id": None})
        )
        self.assertIsNotNone(self.stored("equipment_assignment:act_w1"))
        self.undo(changes)
        self.assertIsNone(self.stored("equipment_assignment:act_w1"))

    def test_undo_of_a_first_assignment_removes_it(self) -> None:
        item = self.bike()
        _, changes = self.collected(
            lambda: self.service.assign(
                {"activity_id": "act_w1", "equipment_id": item["id"]}
            )
        )
        self.undo(changes)
        self.assertIsNone(self.stored("equipment_assignment:act_w1"))
        self.assertEqual(
            self.service.read()["items"][0]["usage"]["assigned_sessions"], 0
        )

    def test_undo_of_a_deleted_unassignment_restores_the_unset_item(self) -> None:
        # A delete target lacks fields stored as None; the restore must seed them.
        with self.manager.unit_of_work() as db:
            before = {"activity_id": "act_w1", "equipment_id": None}
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                ("equipment_assignment:act_w1", json.dumps(before), NOW),
            )
            db.execute("DELETE FROM kv WHERE key='equipment_assignment:act_w1'")
            record = change_history.record_change(
                db, "equipment_assignment", "act_w1", "delete", before, None
            )
        assert record is not None
        self.undo([{key: record[key] for key in change_history.UNDO_REFERENCE_FIELDS}])
        restored = self.stored("equipment_assignment:act_w1") or {}
        self.assertEqual(restored["activity_id"], "act_w1")
        self.assertIsNone(restored["equipment_id"])

    def test_undo_of_an_unassignment_is_refused_when_the_gear_is_gone(self) -> None:
        item = self.bike()
        self.service.assign({"activity_id": "act_w1", "equipment_id": item["id"]})
        _, changes = self.collected(
            lambda: self.service.assign({"activity_id": "act_w1", "equipment_id": None})
        )
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM kv WHERE key=?", ("equipment:" + item["id"],))
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertIsNone(self.record("equipment_assignment:act_w1")["equipment_id"])

    def moved_assignment(self) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Gear A on the activity, then moved to B; returns A and the move."""
        first, second = self.bike(), self.bike(name="Second")
        self.service.assign({"activity_id": "act_w1", "equipment_id": first["id"]})
        _, moved = self.collected(
            lambda: self.service.assign(
                {"activity_id": "act_w1", "equipment_id": second["id"]}
            )
        )
        return first, moved

    def assert_undo_refused(self, changes: list[dict[str, str]], gear_id: str) -> None:
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertNotEqual(
            self.record("equipment_assignment:act_w1")["equipment_id"], gear_id
        )

    def test_undo_of_a_reassignment_is_refused_when_the_old_gear_is_archived(
        self,
    ) -> None:
        first, moved = self.moved_assignment()
        self.edit(first, status="archived")
        self.assert_undo_refused(moved, first["id"])

    def test_undo_of_a_reassignment_is_refused_when_the_sport_changed(self) -> None:
        first, moved = self.moved_assignment()
        self.edit(first, sport="run", kind="shoes")
        self.assert_undo_refused(moved, first["id"])

    def test_undo_of_a_reassignment_is_refused_when_the_old_gear_is_pending(
        self,
    ) -> None:
        first, moved = self.moved_assignment()
        with self.manager.unit_of_work() as db:
            stored = self.record("equipment:" + first["id"])
            stored["sport_pending"] = True
            db.execute(
                "UPDATE kv SET value=? WHERE key=?",
                (json.dumps(stored), "equipment:" + first["id"]),
            )
        self.assert_undo_refused(moved, first["id"])

    # Maintenance

    def test_maintenance_is_recorded_and_its_undo_removes_the_entry(self) -> None:
        item = self.bike()
        result, changes = self.collected(
            lambda: self.service.maintain(
                {"equipment_id": item["id"], "date": "2026-10-01", "notes": "Kette"}
            )
        )
        self.assertEqual(result["change"]["entity_type"], "equipment_maintenance")
        key = "equipment_maintenance:" + result["maintenance"]["id"]
        self.assertIsNotNone(self.stored(key))
        self.undo(changes)
        self.assertIsNone(self.stored(key))
        self.assertEqual(self.service.read()["items"][0]["maintenance"], [])

    def test_undo_of_a_removed_maintenance_entry_restores_it(self) -> None:
        item = self.bike()
        saved = self.service.maintain(
            {"equipment_id": item["id"], "date": "2026-10-01", "notes": "Kette"}
        )["maintenance"]
        with self.manager.unit_of_work() as db:
            db.execute(
                "DELETE FROM kv WHERE key=?", ("equipment_maintenance:" + saved["id"],)
            )
            record = change_history.record_change(
                db, "equipment_maintenance", saved["id"], "delete", saved, None
            )
        assert record is not None
        self.undo([{key: record[key] for key in change_history.UNDO_REFERENCE_FIELDS}])
        restored = self.stored("equipment_maintenance:" + saved["id"]) or {}
        self.assertEqual(restored["notes"], "Kette")
        self.assertEqual(restored["date"], "2026-10-01")

    # Coach receipts

    def test_coach_equipment_tools_offer_a_turn_undo(self) -> None:
        for tool in (
            "save_equipment",
            "assign_activity_equipment",
            "log_equipment_maintenance",
        ):
            summary = change_summary(
                [
                    {
                        "tool": tool,
                        "result": {"ok": True},
                        "changes": [{"id": "x", "action": "create"}],
                    }
                ]
            )
            assert summary is not None
            self.assertTrue(summary["undoable"], tool)


if __name__ == "__main__":
    unittest.main()
