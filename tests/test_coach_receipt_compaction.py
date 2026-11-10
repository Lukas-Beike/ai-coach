"""Finished Coach receipts drop bulky tool results but stay readable."""

from __future__ import annotations

import json
import unittest
from typing import Any

from backend.coach.dialogue import CoachDialogueReadService
from backend.coach.receipt_compaction import compact_receipt, compact_tool_result

BULK = "synthetic plan text " * 2000


class CompactToolResultTests(unittest.TestCase):
    def test_keeps_status_ids_proposed_action_and_drops_bulk(self) -> None:
        result = {
            "ok": True,
            "status": "applied",
            "artifact_id": "art-1",
            "library_entry_ids": ["a", "b"],
            "sync_job_id": "job-1",
            "proposed_action": {"id": "p1", "diff": {"x": 1}},
            "job": {"id": "job-1", "status": "queued", "payload": {"big": BULK}},
            "workouts": [{"description": BULK}],
            "plan": {"days": [BULK]},
            "summary": BULK,
        }

        compact = compact_tool_result("apply_training_changes", result)

        self.assertEqual(compact["ok"], True)
        self.assertEqual(compact["status"], "applied")
        self.assertEqual(compact["artifact_id"], "art-1")
        self.assertEqual(compact["library_entry_ids"], ["a", "b"])
        self.assertEqual(compact["sync_job_id"], "job-1")
        self.assertEqual(compact["proposed_action"], {"id": "p1", "diff": {"x": 1}})
        self.assertEqual(compact["job"], {"id": "job-1", "status": "queued"})
        self.assertNotIn("workouts", compact)
        self.assertNotIn("plan", compact)
        self.assertLessEqual(len(compact["summary"]), 500)
        self.assertLess(len(json.dumps(compact)), 1500)

    def test_lookup_food_keeps_the_matches_the_next_turn_reuses(self) -> None:
        result = {
            "ok": True,
            "results": [
                {
                    "ok": True,
                    "query": "haferflocken",
                    "local_products": [{"id": "lp1", "name": "Hafer", "x": BULK}],
                    "foods": [{"id": "f1", "name": "Flocken", "nutrients": [BULK]}],
                }
            ],
        }

        compact = compact_tool_result("lookup_food", result)

        steps = [{"tool": "lookup_food", "result": compact, "request": {}}]
        projected = CoachDialogueReadService._command_result(
            {
                "client_turn_id": "t",
                "receipt": json.dumps(
                    {"status": "completed", "command_receipts": steps}
                ),
            }
        )
        self.assertEqual(
            [match["id"] for match in projected["steps"][0]["found"]], ["lp1", "f1"]
        )
        self.assertNotIn(BULK, json.dumps(compact))

    def test_receipt_copy_keeps_undo_references_and_leaves_the_input_alone(
        self,
    ) -> None:
        changes = [{"id": "11111111-1111-1111-1111-111111111111", "after_hash": "h"}]
        receipt: dict[str, Any] = {
            "status": "completed",
            "change_summary": {"undoable": True, "undone_at": None},
            "command_receipts": [
                {
                    "tool": "update_profile",
                    "call_id": "c1",
                    "result": {"ok": True, "profile": {"notes": BULK}},
                    "changes": changes,
                }
            ],
        }

        compact = compact_receipt(receipt)

        self.assertEqual(compact["command_receipts"][0]["changes"], changes)
        self.assertEqual(compact["command_receipts"][0]["call_id"], "c1")
        self.assertEqual(compact["command_receipts"][0]["result"], {"ok": True})
        self.assertIn("profile", receipt["command_receipts"][0]["result"])
        self.assertEqual(compact["change_summary"], receipt["change_summary"])

    def test_older_receipts_with_full_results_stay_readable(self) -> None:
        old = {
            "client_turn_id": "t",
            "receipt": json.dumps(
                {
                    "status": "completed",
                    "command_receipts": [
                        {
                            "tool": "get_plan",
                            "result": {"ok": True, "days": [BULK]},
                            "request": {"scope": ["a"]},
                        }
                    ],
                }
            ),
        }

        step = CoachDialogueReadService._command_result(old)["steps"][0]

        self.assertEqual(
            (step["tool"], step["ok"], step["scope"]), ("get_plan", True, ["a"])
        )

    def test_receipt_without_steps_is_returned_unchanged(self) -> None:
        receipt = {"status": "failed"}
        self.assertIs(compact_receipt(receipt), receipt)


if __name__ == "__main__":
    unittest.main()
