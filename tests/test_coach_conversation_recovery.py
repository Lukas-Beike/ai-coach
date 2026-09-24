"""Direct contracts for structured Coach conversation recovery."""

from __future__ import annotations

import json
import logging
import threading
import unittest
from unittest.mock import MagicMock, Mock

from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.errors import AppError


class CoachConversationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MagicMock()
        self.db = object()
        self.manager.unit_of_work.return_value.__enter__ = Mock(return_value=self.db)
        self.manager.unit_of_work.return_value.__exit__ = Mock(return_value=False)
        self.key_values = Mock()
        self.jobs = Mock()
        self.logger = Mock(spec=logging.Logger)
        self.service = CoachConversationRecoveryService(
            self.manager, threading.RLock(), self.key_values, self.jobs, self.logger,
        )
        self.error = AppError(502, "private upstream detail", reason="conversation_state_invalid")

    def recover(self, *, payload=None, request_payload=None, ai_provider="openai", attempt=0,
                request_delta_emitted=False, recovery_state=None, attachments=None):
        payload = payload if payload is not None else {
            "conversation": "remote-id", "previous_response_id": "old-response",
            "input": "old", "instructions": "base",
        }
        request_payload = request_payload if request_payload is not None else {
            "conversation": "remote-id", "previous_response_id": "old-response",
        }
        recovery_state = recovery_state if recovery_state is not None else {"conversation_recovered": False}
        result = self.service.recover_if_invalid(
            self.error, payload, request_payload,
            context={"prior": "lokal"}, message="Bitte fortsetzen",
            command_receipts=[{"tool": "read_training_state", "result": {"ok": True}}],
            attachments=attachments or [], client_turn_id="turn-1", ai_provider=ai_provider,
            recovery_state=recovery_state, request_delta_emitted=request_delta_emitted,
            attempt=attempt,
        )
        return result, payload, request_payload, recovery_state

    def test_remote_conversation_is_cleared_and_local_context_checkpointed(self) -> None:
        recovered, payload, request_payload, state = self.recover()
        self.assertTrue(recovered)
        self.assertTrue(state["conversation_recovered"])
        self.assertNotIn("conversation", payload)
        self.assertNotIn("conversation", request_payload)
        self.assertNotIn("previous_response_id", payload)
        self.assertNotIn("previous_response_id", request_payload)
        self.key_values.set.assert_called_once_with(self.db, "openai_conversation_id", "")
        recovery_input = json.loads(payload["input"])
        self.assertEqual(recovery_input["dialogue"], {"prior": "lokal"})
        self.assertEqual(recovery_input["current_message"], "Bitte fortsetzen")
        self.assertTrue(recovery_input["confirmed_steps"][0]["result"]["ok"])
        self.assertIn("Never invent attachment details", payload["instructions"])
        self.jobs.merge_receipt.assert_called_once_with("turn-1", {
            "openai_response_id": None, "previous_response_id": None,
            "pending_tool_outputs": [], "response_input": payload["input"],
        })
        self.logger.warning.assert_called_once()

    def test_no_remote_conversation_does_not_clear_stored_conversation(self) -> None:
        recovered, _, _, _ = self.recover(payload={"input": "old", "instructions": "base"})
        self.assertTrue(recovered)
        self.manager.unit_of_work.assert_not_called()
        self.key_values.set.assert_not_called()
        self.jobs.merge_receipt.assert_called_once()

    def test_recovery_is_one_time_openai_only_before_delta_and_retry_limit(self) -> None:
        for kwargs in (
            {"ai_provider": "gemini"}, {"attempt": 2},
            {"request_delta_emitted": True},
            {"recovery_state": {"conversation_recovered": True}},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.recover(**kwargs)[0])
        self.error = AppError(502, "upstream", reason="provider_unavailable")
        self.assertFalse(self.recover()[0])
        self.manager.unit_of_work.assert_not_called()
        self.jobs.merge_receipt.assert_not_called()
        self.logger.warning.assert_not_called()

    def test_attachment_input_keeps_untrusted_name_and_image_evidence(self) -> None:
        attachment = {"type": "image", "name": "Beweis.png", "mime": "image/png", "data": "AA=="}
        recovered, payload, _, _ = self.recover(attachments=[attachment])
        self.assertTrue(recovered)
        self.assertEqual(payload["input"][0]["content"][1]["text"],
                         json.dumps({"untrusted_attachment_name": "Beweis.png"}, ensure_ascii=False))
        self.assertEqual(payload["input"][0]["content"][2]["image_url"], "data:image/png;base64,AA==")


if __name__ == "__main__":
    unittest.main()
