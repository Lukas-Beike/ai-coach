"""Direct contracts for a complete structured Coach turn."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.coach.structured_turn import (
    CoachStructuredTurnDependencies,
    CoachStructuredTurnService,
)
from backend.coach.turn_failures import coach_error_metadata
from backend.errors import AppError


class StructuredTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.opening = Mock()
        self.opening.open.return_value = {"mode": "background", "tool_rounds": 0}
        self.attachments = Mock()
        self.attachments.load_for_receipt.return_value = ([], False)
        self.dialogue = Mock()
        self.dialogue.context.return_value = {"synthetic": True}
        self.payload = Mock()
        self.payload.build.return_value = ("synthetic-instructions", {"input": []})
        self.response = Mock()
        self.response.respond.return_value = {"output": []}
        self.rounds = Mock()
        self.rounds.run.return_value = ({"output": []}, 0, "", False, "synthetic-instructions")
        self.outcome = Mock()
        self.outcome.finalize.return_value = ("completed", "synthetic-answer", [])
        self.final = Mock()
        self.final.build.return_value = {"status": "completed"}
        self.final.persist.return_value = {"status": "completed", "session_key": "private", "text": "synthetic-answer"}
        self.failure = Mock()
        self.service = CoachStructuredTurnService(CoachStructuredTurnDependencies(
            opening=self.opening, attachments=self.attachments, dialogue=self.dialogue,
            payload=self.payload, response=self.response, rounds=self.rounds,
            outcome=self.outcome, final_receipt=self.final, failure=self.failure,
            tools=[{"name": "read_profile"}, {"name": "update_profile"}],
            read_only_tools=frozenset({"read_profile"}), logger=Mock(),
            root=Path("synthetic-root"),
        ))

    def run_turn(self, **kwargs):
        return self.service.run(
            "synthetic-question", intent={"allow_mutations": False},
            conversation_id="synthetic-conversation", client_turn_id="synthetic-turn",
            session_csrf_hash="synthetic-session", ai_provider="openai",
            **kwargs,
        )

    def test_complete_turn_filters_tools_and_private_session_key(self) -> None:
        result = self.run_turn(background_job=True)

        self.assertEqual(result, {"status": "completed", "text": "synthetic-answer"})
        self.assertEqual(self.payload.build.call_args.kwargs["tools"], [{"name": "read_profile"}])
        self.assertTrue(self.response.respond.call_args.kwargs["background_owned"])
        self.assertEqual(self.rounds.run.call_args.kwargs["state"].session_csrf_hash, "synthetic-session")
        self.assertEqual(self.final.build.call_args.kwargs["rounds"], 0)
        self.assertEqual(self.final.persist.call_args.kwargs["ai_provider"], "openai")
        self.failure.persist.assert_not_called()

    def test_background_checkpoint_restores_exact_request_input_and_previous_id(self) -> None:
        self.opening.open.return_value.update({
            "openai_response_id": "response-one", "response_input": [{"synthetic": "input"}],
            "previous_response_id": "response-before",
        })

        self.run_turn(background_job=True)

        submitted = self.response.respond.call_args.args[0]
        self.assertEqual(submitted["input"], [{"synthetic": "input"}])
        self.assertEqual(submitted["previous_response_id"], "response-before")
        self.assertEqual(self.response.respond.call_args.kwargs["resume_id"], "response-one")

    def test_pending_tool_outputs_override_checkpoint_for_restart(self) -> None:
        self.opening.open.return_value.update({
            "openai_response_id": "response-one", "response_input": [{"synthetic": "old"}],
            "pending_tool_outputs": [{"synthetic": "output"}],
        })

        self.run_turn(background_job=True)

        submitted = self.response.respond.call_args.args[0]
        self.assertEqual(submitted["input"], [{"synthetic": "output"}])
        self.assertEqual(submitted["previous_response_id"], "response-one")
        self.assertEqual(self.response.respond.call_args.kwargs["resume_id"], "")

    def test_failure_persists_safe_receipt_without_session_key(self) -> None:
        self.response.respond.side_effect = AppError(502, "synthetic outage", reason="provider_unavailable")
        self.failure.persist.return_value = {"status": "failed", "session_key": "private"}

        result = self.run_turn()

        self.assertEqual(result, {"status": "failed"})
        self.failure.persist.assert_called_once()
        self.final.persist.assert_not_called()

    def test_scope_denial_is_not_projected_as_terminal_failure(self) -> None:
        self.opening.open.side_effect = AppError(403, "synthetic denial", reason="command_scope_denied")

        with self.assertRaises(AppError):
            self.run_turn()

        self.failure.persist.assert_not_called()

    def test_diagnostics_keep_only_installed_backend_frames_with_split_server_root(self) -> None:
        try:
            self.service._resume_id(None, {}, ai_provider="openai", background_owned=True)
        except AttributeError as exc:
            metadata = coach_error_metadata(exc, Path("different-server-root"))
        else:
            self.fail("synthetic invalid receipt must raise")

        self.assertTrue(metadata["frames"])
        self.assertTrue(all(frame["file"] == "backend/coach/structured_turn.py" for frame in metadata["frames"]))
        try:
            raise RuntimeError("synthetic private payload")
        except RuntimeError as exc:
            external = coach_error_metadata(exc, Path("different-server-root"))
        self.assertEqual(external["frames"], [])
        self.assertNotIn("synthetic private payload", str(metadata))


if __name__ == "__main__":
    unittest.main()
