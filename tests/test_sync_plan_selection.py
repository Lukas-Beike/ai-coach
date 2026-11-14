"""Tests for structured plan-sync selection and execution."""

from __future__ import annotations

import json
import unittest
import uuid
from unittest.mock import Mock

from support import temp_database

from backend.db import row_factory
from backend.errors import AppError
from backend.planning.planned_units import plan_push_payload_hash
from backend.planning.push_state import skips_intervals
from backend.sync.plan_selection import StructuredPlanSyncService

UNIT_A = "00000000-0000-0000-0000-000000000001"
UNIT_B = "00000000-0000-0000-0000-000000000002"


class StructuredPlanSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(self, "plan-selection.db", row_factory=row_factory)
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "sync_state TEXT NOT NULL DEFAULT 'local', sync_dirty INTEGER NOT NULL DEFAULT 1, "
                "sync_error TEXT, updated_at TEXT NOT NULL DEFAULT '')"
            )
            db.execute(
                "CREATE TABLE workout_library (local_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
        self.pending: list[dict[str, str]] = []
        self.events: list[tuple[str, object]] = []
        self.authority = Mock()
        self.authority.pending_plan_push_entries.side_effect = self._pending
        self.authority.mark_planning_authoritative.side_effect = self._mark
        self.authority.intervals_skipped.side_effect = self._skipped
        self.queue = Mock()
        self.queue.enqueue.side_effect = self._enqueue
        self.service = StructuredPlanSyncService(
            self.manager, self.authority, self.queue, 366
        )

    def add_entry(self, local_id: str, payload: dict[str, object]) -> dict[str, str]:
        raw = json.dumps(payload, sort_keys=True)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
                (local_id, raw),
            )
        item = {
            "library_workout_id": local_id,
            "expected_payload_hash": plan_push_payload_hash(raw),
        }
        self.pending.append(item)
        return item

    def _skipped(self, local_ids) -> set[str]:
        with self.manager.reader() as db:
            rows = db.execute("SELECT local_id, payload FROM planned_units").fetchall()
        wanted = set(local_ids)
        return {
            row["local_id"]
            for row in rows
            if row["local_id"] in wanted and skips_intervals(json.loads(row["payload"]))
        }

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
                        item["expected_payload_hash"] = plan_push_payload_hash(raw)

    def _enqueue(self, entries, sync_job_ids, *, reason):
        self.events.append(("enqueue", [dict(item) for item in entries]))
        return {"ok": True, "status": "queued", "entries": len(entries)}

    def test_all_marks_before_manifest_read_and_empty_all_completes(self) -> None:
        prepared = self.service.prepare(None, {})
        self.assertEqual(prepared.mode, "all")
        self.assertEqual(prepared.required_scope_groups, (("local_plan",),))
        self.service.execute(prepared, [], reason="all")
        self.assertEqual(
            [event[0] for event in self.events], ["mark", "pending", "enqueue"]
        )
        self.assertEqual(self.events[-1][1], [])

    def test_the_receipt_names_the_units_intervals_icu_skips(self) -> None:
        # Only indoor and virtual rides go to Intervals.icu (#2419); the rest of
        # the selection is still queued, where the job skips it without a write.
        entries = [
            self.add_entry(UNIT_A, {"sport": "VirtualRide"}),
            self.add_entry(UNIT_B, {"sport": "Run"}),
            self.add_entry(str(uuid.uuid4()), {"sport": "Ride"}),
            self.add_entry(str(uuid.uuid4()), {"sport": "Run", "local_deleted": True}),
        ]
        prepared = self.service.prepare(entries, {"_sync_all_pending": True})

        result = self.service.execute(prepared, [], reason="all")

        self.assertEqual(4, len(self.queue.enqueue.call_args.args[0]))
        self.assertEqual(2, result["skipped"])
        self.assertEqual(
            "2 Einheiten nicht gesendet. Geht nicht an Intervals.icu: nur Indoor-Radeinheiten.",
            result["message"],
        )
        self.assertNotIn(
            "skipped", self.service.report_skips({"ok": True}, entries[:1])
        )

    def test_a_turn_that_changed_only_runs_is_a_receipted_no_op(self) -> None:
        run = self.add_entry(UNIT_A, {"sport": "Run"})
        self.pending.remove(run)
        intent = {
            "_sync_changed_entries_only": True,
            "_changed_sync_entry_ids": [UNIT_A],
        }

        prepared = self.service.prepare(None, intent)
        result = self.service.execute(prepared, [], reason="changed")

        self.assertEqual(
            ("changed", [], ()),
            (prepared.mode, prepared.entries, prepared.required_scope_groups),
        )
        self.assertEqual([], [event for event in self.events if event[0] == "mark"])
        self.assertEqual(1, result["skipped"])
        self.assertIn("Geht nicht an Intervals.icu", result["message"])

    def test_a_changed_run_is_left_out_while_the_changed_indoor_ride_syncs(
        self,
    ) -> None:
        self.add_entry(UNIT_A, {"sport": "Run"})
        ride = self.add_entry(UNIT_B, {"sport": "VirtualRide"})
        self.pending = [ride]
        intent = {
            "_sync_changed_entries_only": True,
            "_changed_sync_entry_ids": [UNIT_A, UNIT_B],
        }

        prepared = self.service.prepare(None, intent)
        result = self.service.execute(prepared, [], reason="changed")

        self.assertEqual([UNIT_B], [e["library_workout_id"] for e in prepared.entries])
        self.assertEqual(
            ((f"planned_unit:{UNIT_B}", f"library_workout:{UNIT_B}"),),
            prepared.required_scope_groups,
        )
        self.assertEqual([ride], self.events[-1][1])
        self.assertEqual(1, result["skipped"])

    def test_a_created_turn_of_runs_only_has_nothing_to_send(self) -> None:
        self.add_entry(UNIT_A, {"sport": "Run"})
        prepared = self.service.prepare(
            [], {"_skipped_sync_entry_ids": [UNIT_A], "_created_sync_entry_ids": []}
        )
        result = self.service.execute(prepared, [], reason="created")

        self.assertEqual([("enqueue", [])], self.events)
        self.assertEqual(1, result["skipped"])

    def test_changed_selection_scopes_each_id_and_queues_pre_mark_hash(self) -> None:
        first = self.add_entry(UNIT_B, {"name": "B", "sport": "VirtualRide"})
        first_hash = first["expected_payload_hash"]
        self.add_entry(UNIT_A, {"name": "A", "sport": "VirtualRide"})
        prepared = self.service.prepare(
            None,
            {
                "_sync_changed_entries_only": True,
                "_changed_sync_entry_ids": [f" {UNIT_B} ", UNIT_A],
            },
        )
        self.assertEqual(
            [entry["library_workout_id"] for entry in prepared.entries],
            [UNIT_A, UNIT_B],
        )
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
        # The mark rewrites only the sync status, so the content hash stays.
        self.assertEqual(self.pending[0]["expected_payload_hash"], first_hash)

    def test_selected_scope_and_all_pending_validation(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            [
                {
                    "library_workout_id": UNIT_A,
                    "expected_payload_hash": item["expected_payload_hash"],
                }
            ],
            {"_created_sync_entry_ids": [UNIT_A]},
        )
        self.assertEqual(
            prepared.required_scope_groups,
            ((f"planned_unit:{UNIT_A}", f"library_workout:{UNIT_A}"),),
        )
        all_pending = self.service.prepare(
            [
                {
                    "library_workout_id": UNIT_A,
                    "expected_payload_hash": item["expected_payload_hash"],
                }
            ],
            {"_sync_all_pending": True},
        )
        self.assertEqual(all_pending.required_scope_groups, (("local_plan",),))
        with self.assertRaises(AppError) as error:
            self.service.prepare(
                [
                    {
                        "library_workout_id": UNIT_A,
                        "expected_payload_hash": item["expected_payload_hash"],
                    }
                ],
                {"_created_sync_entry_ids": ["00000000-0000-0000-0000-000000000009"]},
            )
        self.assertEqual(error.exception.reason, "intent_scope_denied")
        with self.assertRaises(AppError) as all_pending_error:
            self.service.prepare(
                [
                    {
                        "library_workout_id": UNIT_A,
                        "expected_payload_hash": item["expected_payload_hash"],
                    }
                ],
                {
                    "_sync_all_pending": True,
                    "_created_sync_entry_ids": ["00000000-0000-0000-0000-000000000009"],
                },
            )
        self.assertEqual(all_pending_error.exception.reason, "intent_scope_denied")

    def test_a_turn_sync_accepts_only_the_leftovers_of_hidden_units(self) -> None:
        # Replacing a unit and sending the new one also removes the old event
        # (#2373); any other unit beyond the turn's stays refused.
        with self.manager.unit_of_work() as db:
            db.execute(
                "ALTER TABLE planned_units ADD COLUMN tombstone INTEGER NOT NULL DEFAULT 0"
            )
        new = self.add_entry(UNIT_A, {"name": "Run", "date": "2026-11-13"})
        replaced = self.add_entry(
            UNIT_B,
            {
                "name": "Ride",
                "date": "2026-11-13",
                "remote_event_id": "evt-1",
                "archived": True,
                "local_deleted": True,
            },
        )
        intent = {"_created_sync_entry_ids": [UNIT_A]}

        prepared = self.service.prepare([new, replaced], intent)

        self.assertEqual(
            [UNIT_A, UNIT_B],
            [entry["library_workout_id"] for entry in prepared.entries],
        )
        live = self.add_entry(
            "00000000-0000-0000-0000-000000000003",
            {"name": "Live", "date": "2026-11-14"},
        )
        for extra in (live, {**replaced, "library_workout_id": UNIT_A}):
            with self.subTest(extra=extra["library_workout_id"]):
                entries = [new, live] if extra is live else [replaced]
                with self.assertRaises(AppError) as error:
                    self.service.prepare(entries, intent)
                self.assertEqual("intent_scope_denied", error.exception.reason)

    def test_all_pending_manifest_uses_approval_limit_not_edit_limit(self) -> None:
        entries = [
            {
                "library_workout_id": str(uuid.uuid4()),
                "expected_payload_hash": "a" * 64,
            }
            for _ in range(367)
        ]
        self.pending = [dict(entry) for entry in entries]

        prepared = self.service.prepare(entries, {"_sync_all_pending": True})

        self.assertEqual(len(prepared.entries), 367)

    def test_all_pending_rejects_a_subset_of_the_pending_units(self) -> None:
        first = self.add_entry(UNIT_A, {"name": "A"})
        self.add_entry(UNIT_B, {"name": "B"})

        with self.assertRaises(AppError) as error:
            self.service.prepare([first], {"_sync_all_pending": True})

        self.assertEqual("intent_scope_denied", error.exception.reason)
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_stale_hash_rejected_before_authority_mutation(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            [
                {
                    "library_workout_id": UNIT_A,
                    "expected_payload_hash": item["expected_payload_hash"],
                }
            ],
            {},
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

    def test_all_pending_selection_validates_and_queues_workout_library_rows(
        self,
    ) -> None:
        raw = json.dumps({"name": "Template"}, sort_keys=True)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(local_id, payload) VALUES (?, ?)",
                (UNIT_A, raw),
            )
        entry = {
            "library_workout_id": UNIT_A,
            "expected_payload_hash": plan_push_payload_hash(raw),
            "entity": "workout_library",
        }
        self.pending = [dict(entry)]
        prepared = self.service.prepare([entry], {"_sync_all_pending": True})

        result = self.service.execute(prepared, [], reason="all pending")

        self.assertTrue(result["ok"])
        self.assertEqual(self.queue.enqueue.call_args.args[0], [entry])
        self.authority.mark_planning_authoritative.assert_not_called()

    def test_selected_rehashes_after_authority_mark_before_enqueue(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        original_hash = item["expected_payload_hash"]
        prepared = self.service.prepare(
            [
                {
                    "library_workout_id": UNIT_A,
                    "expected_payload_hash": item["expected_payload_hash"],
                }
            ],
            {},
        )
        self.service.execute(prepared, [], reason="selected")
        queued_hash = self.events[-1][1][0]["expected_payload_hash"]
        self.assertEqual(queued_hash, self.pending[0]["expected_payload_hash"])
        # The mark rewrites only the sync status, so the content hash stays.
        self.assertEqual(queued_hash, original_hash)
        self.assertEqual([event[0] for event in self.events[-2:]], ["mark", "enqueue"])

    def test_selected_authority_failure_rolls_back_database_mutation(self) -> None:
        item = self.add_entry(UNIT_A, {"name": "A"})
        prepared = self.service.prepare(
            [
                {
                    "library_workout_id": UNIT_A,
                    "expected_payload_hash": item["expected_payload_hash"],
                }
            ],
            {},
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
