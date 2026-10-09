"""Focused tests for structured Coach provider payload construction."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from backend.coach.request_payload import CoachRequestPayloadService


class CoachRequestPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.training_context = Mock()
        self.training_context.build.return_value = "training context"
        self.settings = Mock()
        self.settings.selected_model.return_value = "configured-model"
        self.settings.selected_thinking_level.return_value = "high"
        self.service = CoachRequestPayloadService(
            self.training_context, self.settings, max_output_tokens=32_000
        )
        self.context = {
            "current_user_message_id": "msg-1",
            "local_date": "2026-09-23",
            "timezone": "Europe/Berlin",
            "pending_request": None,
            "messages": [{"role": "user", "content": "prior local turn"}],
        }

    def build(self, **overrides):
        arguments = {
            "message": "current turn",
            "context": self.context,
            "command_receipts": [],
            "tools": [{"name": "read_context"}],
            "allow_mutations": True,
            "model": "selected-model",
            "thinking_level": "low",
            "conversation_id": "conversation-1",
            "attachments": [],
            "retain_openai_attachment_context": False,
            "has_prior_openai_attachments": False,
        }
        arguments.update(overrides)
        return self.service.build(**arguments)

    def test_openai_keeps_conversation_only_for_attachment_continuity(self) -> None:
        _, retained = self.build(
            retain_openai_attachment_context=True,
            has_prior_openai_attachments=True,
        )
        _, local = self.build(has_prior_openai_attachments=True)

        self.assertEqual(retained["conversation"], "conversation-1")
        self.assertTrue(retained["store"])
        retained_input = json.loads(retained["input"])
        self.assertNotIn("dialogue", retained_input)
        self.assertEqual(retained_input["timezone"], "Europe/Berlin")

        self.assertNotIn("conversation", local)
        self.assertTrue(local["store"])
        self.assertIs(local["parallel_tool_calls"], False)
        self.assertIn("dialogue", json.loads(local["input"]))
        self.assertIn("Earlier image pixels are unavailable", local["instructions"])

    def test_advisory_request_adds_no_mutation_instruction(self) -> None:
        model_instructions, payload = self.build(allow_mutations=False)

        advisory = (
            "This is an automatic advisory run. Do not change data or pending requests."
        )
        self.assertIn(advisory, model_instructions)
        self.assertIn(advisory, payload["instructions"])

    def test_settings_fallback_and_output_limit(self) -> None:
        _, payload = self.build(model=None, thinking_level=None)

        self.settings.selected_model.assert_called_once_with()
        self.settings.selected_thinking_level.assert_called_once_with()
        self.assertEqual(payload["model"], "configured-model")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertEqual(payload["max_output_tokens"], 32_000)

    def test_current_message_is_sent_once_with_full_provenance(
        self,
    ) -> None:
        message = "Synthetic current question with spaces and \u00e4"
        context = {
            **self.context,
            "current_user_message_id": 24,
            "messages": [
                {"id": index, "role": "user", "content": "Synthetic earlier dialogue"}
                for index in range(1, 24)
            ]
            + [{"id": 24, "role": "user", "content": message}],
            "pending_request": {
                "source_message_ids": [1, 24],
                "question": "Which day?",
            },
        }
        _, payload = self.build(message=message, context=context)
        parsed = json.loads(payload["input"])
        self.assertEqual(parsed["current_message"], message)
        self.assertEqual(parsed["dialogue"]["current_user_message_id"], 24)
        self.assertEqual(parsed["dialogue"]["messages"], context["messages"][:-1])
        self.assertEqual(
            parsed["dialogue"]["pending_request"], context["pending_request"]
        )
        self.assertEqual(payload["input"].count(message), 1)
        self.assertEqual(
            payload["input"],
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        )
        self.assertEqual(len(context["messages"]), 24)


if __name__ == "__main__":
    unittest.main()
