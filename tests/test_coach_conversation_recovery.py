"""Direct contracts for structured Coach conversation recovery."""

from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import MagicMock, Mock

from backend.coach.attachments import model_attachments
from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.errors import AppError
from backend.providers.model_seam import ModelRequest, ModelStep
from backend.providers.openai_responses_adapter import request_payload

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFOsAAAAA"
    "SUVORK5CYII="
)


class CoachConversationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MagicMock()
        self.db = object()
        self.manager.unit_of_work.return_value.__enter__ = Mock(return_value=self.db)
        self.manager.unit_of_work.return_value.__exit__ = Mock(return_value=False)
        self.key_values = Mock()
        self.logger = Mock(spec=logging.Logger)
        self.service = CoachConversationRecoveryService(
            self.manager,
            self.key_values,
            self.logger,
        )
        self.error = AppError(
            502, "private upstream detail", reason="conversation_state_invalid"
        )

    def recover(
        self,
        *,
        remote=True,
        attempt=0,
        request_delta_emitted=False,
        recovery_state=None,
        attachments=None,
    ):
        conversation_id = "remote-id" if remote else None
        request = ModelRequest(
            model="m",
            instructions="base",
            input="old",
            attachments=model_attachments(attachments or []),
            conversation_id=conversation_id,
            steps=[ModelStep([], [{"call_id": "c", "output": "{}"}])],
        )
        turn_request = ModelRequest(
            model="m", instructions="base", conversation_id=conversation_id
        )
        recovery_state = (
            recovery_state
            if recovery_state is not None
            else {"conversation_recovered": False}
        )
        result = self.service.recover_if_invalid(
            self.error,
            request,
            turn_request,
            context={"prior": "lokal"},
            message="Bitte fortsetzen",
            command_receipts=[{"tool": "read_training_state", "result": {"ok": True}}],
            attachments=attachments or [],
            recovery_state=recovery_state,
            request_delta_emitted=request_delta_emitted,
            attempt=attempt,
        )
        return result, request, turn_request, recovery_state

    def test_remote_conversation_is_cleared_and_local_context_rebuilt(
        self,
    ) -> None:
        recovered, request, turn_request, state = self.recover()
        self.assertTrue(recovered)
        self.assertTrue(state["conversation_recovered"])
        self.assertIsNone(request.conversation_id)
        self.assertIsNone(turn_request.conversation_id)
        # The rebuilt dialogue replaces the tool results of the failed follow-up.
        self.assertEqual(request.steps, [])
        self.key_values.set.assert_called_once_with(
            self.db, "openai_conversation_id", ""
        )
        recovery_input = json.loads(request.input)
        self.assertEqual(recovery_input["dialogue"], {"prior": "lokal"})
        self.assertEqual(recovery_input["current_message"], "Bitte fortsetzen")
        self.assertTrue(recovery_input["confirmed_steps"][0]["result"]["ok"])
        self.assertIn("Never invent attachment details", request.instructions)
        # Later stateless tool rounds seed their chain from the request's input.
        self.assertEqual(turn_request.input, request.input)
        self.logger.warning.assert_called_once()

    def test_no_remote_conversation_does_not_clear_stored_conversation(self) -> None:
        recovered, _, _, _ = self.recover(remote=False)
        self.assertTrue(recovered)
        self.manager.unit_of_work.assert_not_called()
        self.key_values.set.assert_not_called()

    def test_recovery_is_one_time_before_delta_and_retry_limit(
        self,
    ) -> None:
        for kwargs in (
            {"attempt": 2},
            {"request_delta_emitted": True},
            {"recovery_state": {"conversation_recovered": True}},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.recover(**kwargs)[0])
        self.error = AppError(502, "upstream", reason="provider_unavailable")
        self.assertFalse(self.recover()[0])
        self.manager.unit_of_work.assert_not_called()
        self.logger.warning.assert_not_called()

    def test_attachment_input_keeps_untrusted_name_and_image_evidence(self) -> None:
        attachment = {
            "type": "image",
            "name": "Beweis.png",
            "mime": "image/png",
            "data": PNG,
        }
        recovered, request, _, _ = self.recover(attachments=[attachment])
        self.assertTrue(recovered)
        parts = request_payload(request)["input"][0]["content"]
        self.assertEqual(
            parts[1]["text"],
            json.dumps({"untrusted_attachment_name": "Beweis.png"}, ensure_ascii=False),
        )
        self.assertEqual(
            parts[2]["image_url"],
            "data:image/png;base64," + PNG,
        )


if __name__ == "__main__":
    unittest.main()
