"""Tests for complete-period plan-repair manifests."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.db import DatabaseManager, row_factory
from backend.errors import AppError
from backend.planning.library import library_payload_hash
from backend.sync.plan_repair import PlanRepairManifestService

UNIT_A = "00000000-0000-0000-0000-000000000001"
UNIT_B = "00000000-0000-0000-0000-000000000002"
PERIOD = {"start": "2026-09-09", "end": "2026-09-10"}
INTENT = {"_repair_period": PERIOD}


class PlanRepairManifestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temp.name) / "plan-repair.db", sqlite3, row_factory=row_factory
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "sync_state TEXT NOT NULL DEFAULT 'local', sync_dirty INTEGER NOT NULL DEFAULT 1, "
                "sync_error TEXT, updated_at TEXT NOT NULL DEFAULT '')"
            )
            db.execute("CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)")
            db.execute("INSERT INTO planning_state(id, revision) VALUES (1, 7)")
        self.authority = Mock()
        self.service = PlanRepairManifestService(self.manager, self.authority)

    def tearDown(self) -> None:
        self.manager.close()
        self.temp.cleanup()

    def add(self, local_id: str, *, date: str = "2026-09-09", **fields: object) -> str:
        payload = {
            "date": date,
            "sport": "Run",
            "name": "Easy run",
            "description": "- 30m Z1 HR",
            "duration_minutes": 30,
            **fields,
        }
        raw = json.dumps(payload, sort_keys=True)
        with self.manager.unit_of_work() as db:
            db.execute("INSERT INTO planned_units(local_id, payload) VALUES (?, ?)", (local_id, raw))
        return library_payload_hash(raw)

    def selected(self, *items: tuple[str, str]) -> list[dict[str, str]]:
        return [
            {"library_workout_id": local_id, "expected_payload_hash": payload_hash}
            for local_id, payload_hash in items
        ]

    def read_payload(self, local_id: str) -> dict[str, object]:
        with self.manager.reader() as db:
            row = db.execute("SELECT payload FROM planned_units WHERE local_id=?", (local_id,)).fetchone()
        return json.loads(row["payload"])

    def test_partial_selection_fails_with_conflict(self) -> None:
        first = self.add(UNIT_A)
        second = self.add(UNIT_B, date="2026-09-10")
        with self.assertRaises(AppError) as caught:
            self.service.prepare({"entries": self.selected((UNIT_A, first))}, INTENT)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "incomplete_repair_selection")
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_stale_revision_and_hash_fail_before_authority(self) -> None:
        payload_hash = self.add(UNIT_A)
        stale_revision = self.service.prepare({"expected_revision": 6}, INTENT)
        self.assertEqual(stale_revision.required_scope_groups, (("local_plan",),))
        with self.assertRaises(AppError) as revision_error:
            self.service.execute(stale_revision)
        self.assertEqual(revision_error.exception.reason, "planning_revision_conflict")

        stale_hash = self.service.prepare(
            {"entries": self.selected((UNIT_A, "0" * 64))}, INTENT
        )
        self.assertEqual(
            stale_hash.required_scope_groups,
            ((f"planned_unit:{UNIT_A}", f"library_workout:{UNIT_A}"),),
        )
        with self.assertRaises(AppError) as hash_error:
            self.service.execute(stale_hash)
        self.assertEqual(hash_error.exception.reason, "planning_revision_conflict")
        self.assertNotEqual(payload_hash, "0" * 64)
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_prepare_returns_required_scope_groups_for_root_authorization(self) -> None:
        payload_hash = self.add(UNIT_A)
        selected = self.service.prepare(
            {"entries": self.selected((UNIT_A, payload_hash))}, INTENT
        )
        complete = self.service.prepare({"expected_revision": 7}, INTENT)
        self.assertEqual(
            selected.required_scope_groups,
            ((f"planned_unit:{UNIT_A}", f"library_workout:{UNIT_A}"),),
        )
        self.assertEqual(complete.required_scope_groups, (("local_plan",),))

    def test_invalid_active_workout_prevents_mark(self) -> None:
        payload_hash = self.add(UNIT_A, description="not a structured workout")
        prepared = self.service.prepare(
            {"entries": self.selected((UNIT_A, payload_hash))}, INTENT
        )
        with self.assertRaises(AppError):
            self.service.execute(prepared)
        self.authority.mark_planning_authoritative.assert_not_called()
        self.assertNotIn("sync_status", self.read_payload(UNIT_A))

    def test_execute_rolls_back_authority_mutation_on_error(self) -> None:
        payload_hash = self.add(UNIT_A)
        prepared = self.service.prepare(
            {"entries": self.selected((UNIT_A, payload_hash))}, INTENT
        )

        def mark_then_fail(local_ids: list[str]) -> None:
            with self.manager.unit_of_work() as db:
                row = db.execute("SELECT payload FROM planned_units WHERE local_id=?", (local_ids[0],)).fetchone()
                payload = json.loads(row["payload"])
                payload["sync_status"] = "local"
                db.execute(
                    "UPDATE planned_units SET payload=? WHERE local_id=?",
                    (json.dumps(payload, sort_keys=True), local_ids[0]),
                )
            raise RuntimeError("authority failed")

        self.authority.mark_planning_authoritative.side_effect = mark_then_fail
        with self.assertRaisesRegex(RuntimeError, "authority failed"):
            self.service.execute(prepared)
        self.assertNotIn("sync_status", self.read_payload(UNIT_A))

    def test_hash_is_refreshed_after_authority_mark(self) -> None:
        payload_hash = self.add(UNIT_A)
        prepared = self.service.prepare(
            {"entries": self.selected((UNIT_A, payload_hash))}, INTENT
        )

        def mark(local_ids: list[str]) -> None:
            with self.manager.unit_of_work() as db:
                row = db.execute("SELECT payload FROM planned_units WHERE local_id=?", (local_ids[0],)).fetchone()
                payload = json.loads(row["payload"])
                payload["sync_status"] = "local"
                db.execute(
                    "UPDATE planned_units SET payload=? WHERE local_id=?",
                    (json.dumps(payload, sort_keys=True), local_ids[0]),
                )

        self.authority.mark_planning_authoritative.side_effect = mark
        manifest = self.service.execute(prepared)
        self.assertNotEqual(manifest[0]["expected_payload_hash"], payload_hash)
        self.assertEqual(manifest[0]["expected_payload_hash"], library_payload_hash(json.dumps(self.read_payload(UNIT_A), sort_keys=True)))

    def test_toctou_change_between_prepare_and_execute_conflicts(self) -> None:
        self.add(UNIT_A)
        prepared = self.service.prepare({"expected_revision": 7}, INTENT)
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE planning_state SET revision=revision+1 WHERE id=1")
        with self.assertRaises(AppError) as caught:
            self.service.execute(prepared)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "planning_revision_conflict")
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_item_hash_selection_is_not_blocked_by_unrelated_revision_change(self) -> None:
        payload_hash = self.add(UNIT_A)
        prepared = self.service.prepare(
            {"entries": self.selected((UNIT_A, payload_hash))}, INTENT
        )
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE planning_state SET revision=revision+1 WHERE id=1")
        self.assertEqual(len(self.service.execute(prepared)), 1)

    def test_empty_period_is_valid_and_creates_no_remote_work(self) -> None:
        prepared = self.service.prepare({"expected_revision": 7}, INTENT)
        self.assertEqual(prepared.entries, [])
        self.assertEqual(prepared.required_scope_groups, (("local_plan",),))
        self.assertEqual(self.service.execute(prepared), [])
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_empty_selected_entries_keep_bulk_parser_rejection(self) -> None:
        with self.assertRaises(AppError) as caught:
            self.service.prepare({"entries": []}, INTENT)
        self.assertEqual(caught.exception.status, 400)

    def test_archived_and_deleted_workouts_skip_description_validation(self) -> None:
        archived_hash = self.add(UNIT_A, description="invalid", archived=True)
        deleted_hash = self.add(UNIT_B, description="invalid", local_deleted=True, date="2026-09-10")
        prepared = self.service.prepare(
            {"entries": self.selected((UNIT_A, archived_hash), (UNIT_B, deleted_hash))}, INTENT
        )
        manifest = self.service.execute(prepared)
        self.assertEqual({item["library_workout_id"] for item in manifest}, {UNIT_A, UNIT_B})
        self.authority.mark_planning_authoritative.assert_called_once_with([UNIT_A, UNIT_B])


if __name__ == "__main__":
    unittest.main()
