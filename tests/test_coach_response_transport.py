from __future__ import annotations

import threading
import unittest
from typing import Any, ClassVar
from unittest.mock import Mock

from backend.coach.response_transport import (
    CoachResponseTransport,
    raise_if_chat_cancelled,
)
from backend.errors import AppError
from backend.providers import openai_responses_adapter as responses_adapter
from backend.providers.model_seam import ModelRequest, ModelStep, ModelTurn


class CoachResponseTransportTests(unittest.TestCase):
    """The Coach sends neutral requests; the model transport picks the provider."""

    def setUp(self) -> None:
        self.complete = Mock(return_value=ModelTurn(text="answer"))
        self.stream = Mock(return_value=ModelTurn(stop_reason="completed"))
        self.transport = CoachResponseTransport(self.complete, self.stream)

    def test_request_goes_to_the_one_shot_transport(self) -> None:
        request = ModelRequest(model="m", instructions="i")

        self.assertEqual(self.transport.request(request), ModelTurn(text="answer"))

        self.complete.assert_called_once_with(request)
        self.stream.assert_not_called()

    def test_stream_forwards_delta_callback_cancel_and_response_id(self) -> None:
        request = ModelRequest(model="m", instructions="i", input="hello")
        cancel_event = threading.Event()
        on_delta = Mock()
        on_response_id = Mock()

        turn = self.transport.stream_request(
            request, on_delta, cancel_event, on_response_id
        )

        self.assertEqual(turn, ModelTurn(stop_reason="completed"))
        self.stream.assert_called_once_with(
            request,
            on_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )

    def test_cancel_helper_is_noop_without_cancel_and_raises_when_set(self) -> None:
        raise_if_chat_cancelled(None)
        raise_if_chat_cancelled(threading.Event())
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(AppError) as raised:
            raise_if_chat_cancelled(cancelled)
        self.assertEqual(
            (raised.exception.status, raised.exception.reason), (499, "chat_cancelled")
        )


class ResponsesAdapterTests(unittest.TestCase):
    """The OpenAI adapter is the only code that reads or writes Responses items."""

    CALL: ClassVar[dict[str, str]] = {
        "type": "function_call",
        "call_id": "c-1",
        "name": "t",
        "arguments": "{}",
    }

    def test_reply_becomes_text_calls_replayable_state_usage_and_stop_reason(
        self,
    ) -> None:
        reasoning = {"type": "reasoning", "id": "rs-1", "encrypted_content": "enc"}
        bare = {"type": "reasoning", "id": "rs-2"}
        message = {
            "type": "message",
            "content": [{"type": "output_text", "text": "Hallo"}],
        }
        turn = responses_adapter.model_turn(
            {
                "status": "completed",
                "usage": {"total_tokens": 7},
                "output": [reasoning, bare, self.CALL, message, "junk"],
            }
        )

        self.assertEqual(turn.text, "Hallo")
        self.assertEqual(
            turn.tool_calls, [{"call_id": "c-1", "name": "t", "arguments": "{}"}]
        )
        # A reasoning item without encrypted content cannot be replayed.
        self.assertEqual(turn.opaque_state, [reasoning, self.CALL, message])
        self.assertEqual(turn.usage, {"total_tokens": 7})
        self.assertEqual(turn.stop_reason, "completed")
        self.assertFalse(turn.incomplete)

    def test_stop_reasons(self) -> None:
        def reason(response):
            return responses_adapter.model_turn(response).stop_reason

        budget = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        }
        self.assertEqual(reason(budget), "max_tokens")
        self.assertEqual(reason({"status": "incomplete"}), "incomplete")
        self.assertEqual(reason({"status": "failed"}), "failed")
        self.assertEqual(reason({"status": "cancelled"}), "cancelled")
        self.assertEqual(reason({"status": "queued"}), "")
        self.assertTrue(responses_adapter.model_turn(budget).incomplete)

    def test_unusable_reply_is_an_empty_turn(self) -> None:
        replies: tuple[Any, ...] = (None, "text", [], {})
        for response in replies:
            with self.subTest(response=response):
                self.assertEqual(responses_adapter.model_turn(response), ModelTurn())

    def test_stateless_follow_up_resends_the_turn_items(self) -> None:
        reasoning = {"type": "reasoning", "id": "rs-1", "encrypted_content": "enc"}
        request = ModelRequest(
            model="m",
            instructions="i",
            input="hello",
            reasoning_effort="low",
            max_output_tokens=10,
            steps=[
                ModelStep([reasoning, self.CALL], [{"call_id": "c-1", "output": "{}"}])
            ],
        )

        payload = responses_adapter.request_payload(request)

        self.assertEqual(
            payload["input"],
            [
                {"role": "user", "content": "hello"},
                reasoning,
                self.CALL,
                {"type": "function_call_output", "call_id": "c-1", "output": "{}"},
            ],
        )
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["include"], ["reasoning.encrypted_content"])
        self.assertNotIn("conversation", payload)

    def test_conversation_follow_up_sends_only_the_new_results(self) -> None:
        request = ModelRequest(
            model="m",
            instructions="i",
            conversation_id="conv-1",
            stateless=False,
            steps=[ModelStep([], [{"call_id": "c-2", "output": "{}"}])],
        )

        payload = responses_adapter.request_payload(request)

        self.assertEqual(payload["conversation"], "conv-1")
        self.assertEqual(
            payload["input"],
            [{"type": "function_call_output", "call_id": "c-2", "output": "{}"}],
        )
        self.assertIs(payload["store"], True)
        self.assertNotIn("include", payload)

    def test_one_shot_json_request_with_an_image(self) -> None:
        request = ModelRequest(
            model="m",
            input="Lies das Etikett",
            images=[{"mime": "image/png", "data": "QUJD"}],
            json_output=True,
            stateless=False,
        )

        self.assertEqual(
            responses_adapter.request_payload(request),
            {
                "model": "m",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Lies das Etikett"},
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,QUJD",
                            },
                        ],
                    }
                ],
                "text": {"format": {"type": "json_object"}},
            },
        )

    def test_one_shot_schema_request_is_stateless_without_tools(self) -> None:
        request = ModelRequest(
            model="m",
            instructions="i",
            input="x",
            max_output_tokens=5,
            output_schema={"name": "verdict", "schema": {"type": "object"}},
        )

        payload = responses_adapter.request_payload(request)

        self.assertEqual(
            payload["text"],
            {
                "format": {
                    "type": "json_schema",
                    "name": "verdict",
                    "strict": True,
                    "schema": {"type": "object"},
                }
            },
        )
        self.assertIs(payload["store"], False)
        self.assertNotIn("tools", payload)
        self.assertNotIn("reasoning", payload)


if __name__ == "__main__":
    unittest.main()
