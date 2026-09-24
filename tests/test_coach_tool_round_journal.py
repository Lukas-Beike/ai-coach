"""Direct contracts for durable structured Coach tool-round journaling."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

from backend.coach.job_store import CoachJobStore
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal


class StructuredToolRoundJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job_store = Mock(spec=CoachJobStore)
        self.journal = CoachStructuredToolRoundJournal(self.job_store)

    def test_function_calls_filters_non_dict_and_non_function_items(self) -> None:
        calls = [{"type": "function_call", "name": "read_profile"}]

        self.assertEqual(
            self.journal.function_calls(
                {"output": [None, "text", {"type": "message"}, *calls]}
            ),
            calls,
        )
        self.assertEqual(self.journal.function_calls({"output": [1, "x", None]}), [])
        self.assertEqual(self.journal.function_calls({}), [])

    def test_start_round_projects_missing_ids_and_names_as_strings(self) -> None:
        calls = [
            {"call_id": "c-1", "name": "read_profile"},
            {"call_id": None, "name": None},
            {},
        ]

        pending = self.journal.start_round("turn-1", calls)

        self.assertEqual(
            pending,
            [
                {"call_id": "c-1", "tool": "read_profile"},
                {"call_id": "", "tool": ""},
                {"call_id": "", "tool": ""},
            ],
        )
        self.job_store.merge_receipt.assert_called_once_with(
            "turn-1",
            {
                "phase": "executing_tools",
                "pending_tool_calls": pending,
                "pending_tool_outputs": [],
            },
        )

    def test_two_call_round_persists_pending_then_ordered_unicode_outputs(self) -> None:
        calls = [
            {"call_id": "a", "name": "read_profile"},
            {"call_id": "b", "name": "read_training_state"},
        ]
        pending = self.journal.start_round("turn-2", calls)
        outputs: list[dict[str, Any]] = []
        receipts = [{"call_id": "a"}, {"call_id": "b"}]

        question, cancelled, pending = self.journal.record_output(
            client_turn_id="turn-2",
            name="read_profile",
            call_id="a",
            result={"ok": True, "name": "ä"},
            outputs=outputs,
            pending=pending,
            command_receipts=receipts,
            question="",
            cancelled=False,
        )
        self.assertEqual((question, cancelled), ("", False))
        self.assertEqual(pending, [{"call_id": "b", "tool": "read_training_state"}])
        self.assertEqual(outputs[0]["output"], '{"ok": true, "name": "ä"}')
        self.assertEqual(
            self.job_store.merge_receipt.call_args_list[-1].args[1],
            {
                "command_receipts": receipts,
                "pending_tool_calls": pending,
                "phase": "executing_tools",
                "pending_tool_outputs": [],
            },
        )

        question, cancelled, pending = self.journal.record_output(
            client_turn_id="turn-2",
            name="read_training_state",
            call_id="b",
            result={"ok": True, "value": 2},
            outputs=outputs,
            pending=pending,
            command_receipts=receipts,
            question=question,
            cancelled=cancelled,
        )
        self.assertEqual((question, cancelled, pending), ("", False, []))
        self.assertEqual([item["call_id"] for item in outputs], ["a", "b"])
        self.assertEqual(
            self.job_store.merge_receipt.call_args_list[-1].args[1],
            {
                "command_receipts": receipts,
                "pending_tool_calls": [],
                "phase": "waiting_final_response",
                "pending_tool_outputs": outputs,
            },
        )

    def test_clarification_and_cancel_only_change_state_after_success(self) -> None:
        calls = [{"call_id": "clarify", "name": "clarify_coach_request"}]
        pending = self.journal.start_round("turn-3", calls)
        outputs: list[dict[str, Any]] = []
        base: dict[str, Any] = {
            "client_turn_id": "turn-3",
            "outputs": outputs,
            "pending": pending,
            "command_receipts": [],
            "question": "existing question",
            "cancelled": False,
        }

        failed_question = self.journal.record_output(
            name="clarify_coach_request", call_id="clarify", result={"ok": False}, **base
        )
        self.assertEqual(failed_question[:2], ("existing question", False))

        pending = self.journal.start_round(
            "turn-3", [{"call_id": "clarify-2", "name": "clarify_coach_request"}]
        )
        question_result = self.journal.record_output(
            name="clarify_coach_request",
            call_id="clarify-2",
            result={"ok": True, "question": "Which day?"},
            **{**base, "pending": pending},
        )
        self.assertEqual(question_result[:2], ("Which day?", False))

        pending = self.journal.start_round(
            "turn-3", [{"call_id": "cancel", "name": "cancel_coach_request"}]
        )
        cancel_result = self.journal.record_output(
            name="cancel_coach_request",
            call_id="cancel",
            result={"ok": True},
            **{**base, "pending": pending, "question": "", "cancelled": False},
        )
        self.assertEqual(cancel_result[:2], ("", True))

        pending = self.journal.start_round(
            "turn-3", [{"call_id": "cancel-2", "name": "cancel_coach_request"}]
        )
        failed_cancel = self.journal.record_output(
            name="cancel_coach_request",
            call_id="cancel-2",
            result={"ok": False},
            **{**base, "pending": pending, "question": "", "cancelled": False},
        )
        self.assertEqual(failed_cancel[:2], ("", False))

    def test_finish_and_clear_persist_in_order(self) -> None:
        self.journal.finish_round("turn-4", 3)
        self.journal.clear_outputs("turn-4")

        self.assertEqual(
            self.job_store.merge_receipt.call_args_list,
            [
                unittest.mock.call("turn-4", {"tool_rounds": 3}),
                unittest.mock.call("turn-4", {"pending_tool_outputs": []}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
