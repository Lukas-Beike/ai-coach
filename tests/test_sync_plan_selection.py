"""Tests for structured plan-sync selection and execution."""

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
from backend.sync.plan_selection import StructuredPlanSyncService

UNIT_A = "00000000-0000-0000-0000-000000000001"
UNIT_B = "00000000-0000-0000-0000-000000000002"


class StructuredPlanSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "plan-selection.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "sync_state TEXT NOT NULL DEFAULT 'local', sync_dirty INTEGER NOT NULL DEFAULT 1, "
                "sync_error TEXT, updated_at TEXT NOT NULL DEFAULT '')"
            )
        self.pending: list[dict[str, str]] = []
        self.events: list[tuple[str, object]] = []
        self.authority = Mock()
        self.authority.pending_plan_push_entries.side_effect = self._pending
        self.authority.mark_planning_authoritative.side_effect = self._mark
        self.queue = Mock()
        self.queue.enqueue.side_effect = self._enqueue
        self.service = StructuredPlanSyncService(self.manager, self.authority, self.queue, 366)

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def add_entry(self, local_id: str, payload: dict[str, object]) -> dict[str, str]:
        raw = json.dumps(payload, sort_keys=True)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
                (local_id, raw),
            )
        item = {
            "library_workout_id": local_id,
            "expected_payload_hash": library_payload_hash(raw),
        }
        self.pending.append(item)
        return item

    def _pending(self) -> list[dict[str, str]]:
        self.events.append(("pending", None))
        return [dict(item) for item in self.pending]

    def _mark(self, local_ids: list[str] | None = None) -> None:
        self.events.append(("mark", list(local_ids) if local_ids else None))
        targets = local_ids or [item["library_workout_id"] for item in self.pending]
        with self.manager.unit_of_work() as db:
            for local_id in targets:
                row = db.execute(
                    "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
                ).fetchone()
                if not row:
                    continue
                payload = json.loads(row["payload"])
                payload["sync_status"] = "local"
                raw = json.dumps(payload, sort_keys=True)
                db.execute(
                    "UPDATE planned_units SET payload=? WHERE local_id=?",
                    (raw, local_id),
                )
                for item in self.pending:
                    if item["library_workout_id"] == local_id:
                        item["expected_payload_hash"] = library_payload_hash(raw)

    def _enqueue(self, entries, sync_job_ids, *, reason):
        self.events.append(("enqueue", [dict(item) for item in entries]))
        return {"ok": True, "status": "queued", "entries": len(entries)}

    def test_all_marks_before_manifest_read_and_empty_all_completes(self) -> None:
        prepared = self.service.prepare(None, {})
        self.assertEqual(prepared.mode, "all")
        self.assertEqual(prepared.required_scope_groups, (("local_plan",),))
        self.service.execute(prepared, [], reason="all")
        self.assertEqual([event[0] for event in self.events], ["mark", "pending", "enqueue"])
        self.assertEqual(self.events[-1][1], [])

    def test_changed_selection_scopes_each_id_and_queues_pre_mark_hash(self) -> None:
        first = self.add_entry(UNIT_B, {"name": "B"})
        first_hash = first["expected_payload_hash"]
        self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            None,
            {"_sync_changed_entries_only": True, "_changed_sync_entry_ids": [f" {UNIT_B} ", UNIT_A]},
        )
        self.assertEqual([entry["library_workout_id"] for entry in prepared.entries], [UNIT_A, UNIT_B])
        self.assertEqual(
            prepared.required_scope_groups,
            (
                (f"planned_unit:{UNIT_A}", f"library_workout:{UNIT_A}"),
                (f"planned_unit:{UNIT_B}", f"library_workout:{UNIT_B}"),
            ),
        )
        self.service.execute(prepared, [], reason="changed")
        queued = self.events[-1][1]
        self.assertEqual(queued, prepared.entries)
        queued_hash = next(
            entry["expected_payload_hash"]
            for entry in queued
            if entry["library_workout_id"] == UNIT_B
        )
        self.assertEqual(queued_hash, first_hash)
        self.assertNotEqual(self.pending[0]["expected_payload_hash"], first_hash)

    def test_selected_scope_and_all_pending_validation(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}],
            {"_created_sync_entry_ids": [UNIT_A]},
        )
        self.assertEqual(prepared.required_scope_groups, ((f"planned_unit:{UNIT_A}", f"library_workout:{UNIT_A}"),))
        all_pending = self.service.prepare(
            [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}],
            {"_sync_all_pending": True},
        )
        self.assertEqual(all_pending.required_scope_groups, (("local_plan",),))
        with self.assertRaises(AppError) as error:
            self.service.prepare(
                [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}],
                {"_created_sync_entry_ids": ["00000000-0000-0000-0000-000000000009"]},
            )
        self.assertEqual(error.exception.reason, "intent_scope_denied")
        with self.assertRaises(AppError) as all_pending_error:
            self.service.prepare(
                [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}],
                {
                    "_sync_all_pending": True,
                    "_created_sync_entry_ids": ["00000000-0000-0000-0000-000000000009"],
                },
            )
        self.assertEqual(all_pending_error.exception.reason, "intent_scope_denied")

    def test_stale_hash_rejected_before_authority_mutation(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}], {}
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (json.dumps({"name": "new"}), UNIT_A),
            )
        with self.assertRaises(AppError) as error:
            self.service.execute(prepared, [], reason="selected")
        self.assertEqual(error.exception.reason, "planning_revision_conflict")
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_selected_rehashes_after_authority_mark_before_enqueue(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        original_hash = item["expected_payload_hash"]
        prepared = self.service.prepare(
            [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}], {}
        )
        self.service.execute(prepared, [], reason="selected")
        queued_hash = self.events[-1][1][0]["expected_payload_hash"]
        self.assertEqual(queued_hash, self.pending[0]["expected_payload_hash"])
        self.assertNotEqual(queued_hash, original_hash)
        self.assertEqual([event[0] for event in self.events[-2:]], ["mark", "enqueue"])

    def test_selected_authority_failure_rolls_back_database_mutation(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            [{"library_workout_id": UNIT_A, "expected_payload_hash": item["expected_payload_hash"]}], {}
        )
        with self.manager.reader() as db:
            original_payload = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (UNIT_A,)
            ).fetchone()["payload"]

        def mark_then_fail(local_ids):
            self._mark(local_ids)
            raise RuntimeError("authority failure")

        self.authority.mark_planning_authoritative.side_effect = mark_then_fail
        with self.assertRaisesRegex(RuntimeError, "authority failure"):
            self.service.execute(prepared, [], reason="selected")

        with self.manager.reader() as db:
            persisted_payload = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (UNIT_A,)
            ).fetchone()["payload"]
        self.assertEqual(persisted_payload, original_payload)
        self.queue.enqueue.assert_not_called()

    def test_queue_failure_propagates(self) -> None:
        prepared = self.service.prepare(None, {})
        self.queue.enqueue.side_effect = RuntimeError("queue unavailable")
        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            self.service.execute(prepared, [], reason="all")


if __name__ == "__main__":
    unittest.main()
