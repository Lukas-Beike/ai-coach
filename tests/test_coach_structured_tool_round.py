"""Direct contracts for structured Coach tool-round orchestration."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundService,
    StructuredCoachRoundState,
)
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal
from backend.errors import AppError


class StructuredToolRoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = Mock()
        self.manager.unit_of_work.return_value = MagicMock()
        self.lock = MagicMock()
        self.replay = Mock()
        self.replay.lookup.return_value = None
        self.preparation = Mock()
        self.preparation.prepare.return_value = {"operation": "read_profile", "authorization_scope": []}
        self.execution = Mock()
        self.execution.execute.return_value = {"ok": True, "profile": "synthetic"}
        self.failure = Mock()
        self.jobs = Mock()
        self.response = Mock()
        self.response.respond.return_value = {"output": []}
        self.service = CoachStructuredToolRoundService(
            lambda: self.manager, self.lock, self.replay, self.preparation,
            self.execution, self.failure, CoachStructuredToolRoundJournal(self.jobs),
            self.jobs, Mock(), self.response, max_rounds=1,
            background_horizon_days=7, default_max_output_tokens=6000,
            long_plan_max_output_tokens=32000,
        )

    @staticmethod
    def state(*, cancelled_event: threading.Event | None = None) -> StructuredCoachRoundState:
        return StructuredCoachRoundState(
            tools=[{"name": "read_profile"}], command_receipts=[], sync_job_ids=[],
            context={}, allow_mutations=False, conversation_id="synthetic-conversation",
            client_turn_id="synthetic-turn", session_csrf_hash="synthetic-session",
            cancel_event=cancelled_event, ai_provider="openai", request_payload={"input": []},
            model_instructions="synthetic-instructions", message="synthetic-message",
            attachments=[], background_owned=True, on_text_delta=None,
            recovery_state={"conversation_recovered": False},
        )

    @staticmethod
    def call() -> dict[str, str]:
        return {"type": "function_call", "name": "read_profile", "call_id": "call-one", "arguments": "{}"}

    def test_local_tool_execution_and_receipt_share_transaction(self) -> None:
        state = self.state()

        name, call_id, result, _action = self.service._execute_tool_call(
            self.call(), state=state, question="", cancelled=False,
        )

        self.assertEqual((name, call_id, result), ("read_profile", "call-one", {"ok": True, "profile": "synthetic"}))
        self.lock.__enter__.assert_called_once()
        self.manager.unit_of_work.return_value.__enter__.assert_called_once()
        self.execution.execute.assert_called_once()
        self.assertEqual(len(state.command_receipts), 1)
        self.jobs.merge_receipt.assert_called_once_with(
            "synthetic-turn", {"command_receipts": state.command_receipts, "sync_job_ids": []},
        )

    def test_cached_tool_result_never_reexecutes_or_opens_transaction(self) -> None:
        state = self.state()
        self.replay.lookup.return_value = {"result": {"ok": True, "cached": True}}

        name, call_id, result, _action = self.service._execute_tool_call(
            self.call(), state=state, question="", cancelled=False,
        )

        self.assertEqual((name, call_id, result), ("read_profile", "call-one", {"ok": True, "cached": True}))
        self.execution.execute.assert_not_called()
        self.manager.unit_of_work.assert_not_called()
        self.jobs.merge_receipt.assert_not_called()

    def test_failed_local_tool_rolls_back_before_failure_projection(self) -> None:
        state = self.state()
        self.execution.execute.side_effect = ValueError("synthetic-invalid")
        self.failure.project.return_value = {"ok": False, "reason": "synthetic-invalid"}

        _name, _call_id, result, _action = self.service._execute_tool_call(
            self.call(), state=state, question="", cancelled=False,
        )

        self.assertEqual(result, {"ok": False, "reason": "synthetic-invalid"})
        self.manager.unit_of_work.return_value.__exit__.assert_called_once()
        self.assertIs(self.manager.unit_of_work.return_value.__exit__.call_args.args[0], ValueError)
        self.assertEqual(state.command_receipts, [])
        self.jobs.merge_receipt.assert_not_called()
        self.failure.project.assert_called_once()

    def test_round_records_output_then_forces_no_more_tools_at_limit(self) -> None:
        state = self.state()
        first_response = {"id": "response-one", "output": [self.call()]}

        with patch.object(self.service, "_execute_tool_call", return_value=(
            "read_profile", "call-one", {"ok": True}, {"operation": "read_profile"},
        )):
            result = self.service.run(first_response, rounds=0, question="", cancelled=False, state=state)

        self.assertEqual(result[:4], ({"output": []}, 1, "", False))
        followup = self.response.respond.call_args.args[0]
        self.assertEqual(followup["tool_choice"], "none")
        self.assertEqual(followup["previous_response_id"], "response-one")
        self.assertEqual(followup["input"][0]["call_id"], "call-one")
        self.assertEqual(followup["input"][0]["output"], '{"ok": true}')
        phases = [call.args[1] for call in self.jobs.merge_receipt.call_args_list]
        self.assertEqual(phases[0]["phase"], "executing_tools")
        self.assertEqual(phases[1]["phase"], "waiting_final_response")
        self.assertEqual(phases[-1], {"pending_tool_outputs": []})

    def test_cancelled_round_does_not_execute_tool_or_followup(self) -> None:
        event = threading.Event()
        event.set()
        state = self.state(cancelled_event=event)

        with patch.object(self.service, "_execute_tool_call") as execute, self.assertRaises(AppError):
            self.service.run({"output": [self.call()]}, rounds=0, question="", cancelled=False, state=state)

        execute.assert_not_called()
        self.response.respond.assert_not_called()


if __name__ == "__main__":
    unittest.main()
