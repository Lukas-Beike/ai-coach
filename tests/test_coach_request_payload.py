"""Focused tests for structured Coach provider payload construction."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import Mock

from backend.coach import dialogue
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

    def _dialogue_text(self, payload: dict) -> str:
        """Dialogue JSON text of a payload whose input carries attachment parts."""
        return payload["input"][0]["content"][0]["text"]

    def test_attachment_turn_sends_dialogue_conversation_and_summary_notice(
        self,
    ) -> None:
        attachment = {
            "type": "image",
            "name": "synthetic.png",
            "mime": "image/png",
            "data": "AAAA",
        }
        _, payload = self.build(
            attachments=[attachment],
            retain_openai_attachment_context=True,
            has_prior_openai_attachments=True,
        )

        self.assertEqual(payload["conversation"], "conversation-1")
        self.assertIn("dialogue", json.loads(self._dialogue_text(payload)))
        self.assertIn("Earlier image pixels are unavailable", payload["instructions"])

    def test_in_window_follow_up_keeps_conversation_without_dialogue_or_notice(
        self,
    ) -> None:
        _, payload = self.build(
            retain_openai_attachment_context=True,
            has_prior_openai_attachments=True,
        )

        self.assertEqual(payload["conversation"], "conversation-1")
        self.assertNotIn("dialogue", json.loads(payload["input"]))
        self.assertNotIn(
            "Earlier image pixels are unavailable", payload["instructions"]
        )

    def test_post_window_local_turn_sends_dialogue_and_notice_without_conversation(
        self,
    ) -> None:
        _, payload = self.build(
            retain_openai_attachment_context=False,
            has_prior_openai_attachments=True,
        )

        self.assertNotIn("conversation", payload)
        self.assertIn("dialogue", json.loads(payload["input"]))
        self.assertIn("Earlier image pixels are unavailable", payload["instructions"])

    def test_request_size_log_reports_attachment_mode_without_content(self) -> None:
        cases = (
            ({"retain_openai_attachment_context": True}, "retained"),
            ({"retain_openai_attachment_context": False}, "local"),
        )
        for overrides, expected in cases:
            with self.subTest(mode=expected):
                with self.assertLogs("intervals_coach", level="INFO") as logs:
                    self.build(has_prior_openai_attachments=True, **overrides)
                record = logs.records[0]
                self.assertEqual(getattr(record, "event", None), "coach_request_sizes")
                context = getattr(record, "context", {})
                self.assertEqual(context["attachment_mode"], expected)
                self.assertNotIn("current turn", str(context))

    def test_advisory_request_adds_no_mutation_instruction(self) -> None:
        model_instructions, payload = self.build(allow_mutations=False)

        advisory = (
            "This is an automatic advisory run. Do not change data or pending requests."
        )
        self.assertIn(advisory, model_instructions)
        self.assertIn(advisory, payload["instructions"])

    def test_static_instructions_precede_dynamic_training_context(self) -> None:
        self.training_context.build.return_value = "dynamic training context 2026-09-23"
        for allow_mutations in (True, False):
            for prior in (False, True):
                with self.subTest(allow_mutations=allow_mutations, prior=prior):
                    model_instructions, payload = self.build(
                        allow_mutations=allow_mutations,
                        has_prior_openai_attachments=prior,
                    )
                    instructions = payload["instructions"]
                    context_at = instructions.index("dynamic training context")
                    self.assertTrue(instructions.startswith(dialogue.INSTRUCTIONS))
                    self.assertLess(
                        instructions.index("untrusted evidence"), context_at
                    )
                    self.assertEqual(
                        "Earlier image pixels are unavailable" in instructions, prior
                    )
                    if prior:
                        self.assertGreater(
                            instructions.index("Earlier image pixels"), context_at
                        )
                    # Tool-round follow-ups resend exactly this text.
                    self.assertEqual(model_instructions, instructions)
                    advisory = "This is an automatic advisory run."
                    self.assertEqual(advisory in instructions, not allow_mutations)
                    if not allow_mutations:
                        self.assertGreater(instructions.index(advisory), context_at)

    def test_instruction_prefix_is_identical_when_only_the_context_changes(
        self,
    ) -> None:
        self.training_context.build.return_value = "context for Monday"
        _, monday = self.build()
        self.training_context.build.return_value = "context for Tuesday, longer"
        _, tuesday = self.build()

        prefix = monday["instructions"].index("context for Monday")
        self.assertEqual(
            monday["instructions"][:prefix], tuesday["instructions"][:prefix]
        )

    def test_tool_round_instructions_keep_the_attachment_policy(self) -> None:
        model_instructions, _ = self.build()

        self.assertIn("untrusted evidence", model_instructions)

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
        context: dict[str, Any] = {
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
