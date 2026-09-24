from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock

from backend.coach.structured_response import CoachStructuredResponseService
from backend.errors import AppError


class CoachStructuredResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = Mock()
        self.recovery = Mock()
        self.recovery.recover_if_invalid.return_value = False
        self.retry = Mock()
        self.retry.retry_delay.return_value = None
        self.jobs = Mock()
        self.service = CoachStructuredResponseService(
            self.transport, self.recovery, self.retry, self.jobs
        )
        self.payload = {"input": [{"role": "user", "content": "synthetic"}], "model": "synthetic"}
        self.options = {
            "request_payload": self.payload,
            "context": {"synthetic": True},
            "message": "Synthetic question",
            "command_receipts": [],
            "attachments": [],
            "client_turn_id": "turn-synthetic",
            "ai_provider": "openai",
            "background_owned": False,
            "on_text_delta": None,
            "cancel_event": None,
            "recovery_state": {"conversation_recovered": False},
        }

    def test_attached_request_uses_one_transport_without_job_checkpoint(self) -> None:
        expected = {"id": "synthetic-response"}
        self.transport.request.return_value = expected

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.transport.request.assert_called_once_with(self.payload)
        self.transport.background_request.assert_not_called()
        self.jobs.merge_receipt.assert_not_called()

    def test_background_checkpoint_persists_response_id_before_result(self) -> None:
        expected = {"id": "synthetic-response"}

        def finish(_payload, **kwargs):
            kwargs["on_response_id"]("resp-new")
            return expected

        self.transport.background_request.side_effect = finish
        self.options["background_owned"] = True
        self.options["resume_id"] = "resp-prior"

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(self.transport.background_request.call_args.kwargs["response_id"], "resp-prior")
        self.jobs.merge_receipt.assert_called_once_with("turn-synthetic", {
            "status": "running", "phase": "waiting_openai", "openai_response_id": "resp-new",
            "pending_tool_outputs": [], "response_input": self.payload["input"],
            "previous_response_id": None,
        })

    def test_transient_background_error_resumes_the_checkpointed_response(self) -> None:
        expected = {"id": "resumed-response"}

        calls = 0

        def respond(_payload, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                kwargs["on_response_id"]("resp-new")
                raise AppError(503, "Synthetic provider unavailable", reason="provider_unavailable")
            return expected

        self.transport.background_request.side_effect = respond
        self.options["background_owned"] = True

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(self.transport.background_request.call_count, 2)
        self.assertEqual(
            [item.kwargs["response_id"] for item in self.transport.background_request.call_args_list],
            [None, "resp-new"],
        )
        self.retry.retry_delay.assert_not_called()
        self.recovery.recover_if_invalid.assert_not_called()

    def test_rate_limit_retries_without_stream_delta(self) -> None:
        expected = {"id": "after-retry"}
        self.transport.request.side_effect = [
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"), expected,
        ]
        self.retry.retry_delay.return_value = 0.01

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(self.transport.request.call_count, 2)
        self.retry.retry_delay.assert_called_once()
        self.assertEqual(self.retry.retry_delay.call_args.kwargs["request_delta_emitted"], False)
        self.retry.wait.assert_called_once_with(0.01, None, 0)

    def test_stream_delta_disables_response_retry(self) -> None:
        deltas: list[str] = []

        def stream(_payload, on_delta, *_args, **_kwargs):
            on_delta("partial")
            raise AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded")

        self.transport.stream_request.side_effect = stream
        self.options["on_text_delta"] = deltas.append

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "rate_limit_exceeded")
        self.assertEqual(deltas, ["partial"])
        self.assertEqual(self.retry.retry_delay.call_args.kwargs["request_delta_emitted"], True)
        self.transport.stream_request.assert_called_once()

    def test_invalid_conversation_recovery_retries_once_with_shared_payload(self) -> None:
        expected = {"id": "recovered"}
        self.transport.request.side_effect = [
            AppError(409, "Synthetic invalid conversation", reason="conversation_state_invalid"),
            expected,
        ]
        self.recovery.recover_if_invalid.return_value = True

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.recovery.recover_if_invalid.assert_called_once()
        self.assertIs(self.recovery.recover_if_invalid.call_args.args[1], self.payload)
        self.assertEqual(self.recovery.recover_if_invalid.call_args.kwargs["attempt"], 0)
        self.assertEqual(self.transport.request.call_count, 2)
        self.retry.retry_delay.assert_not_called()

    def test_cancellation_before_request_never_calls_provider(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        self.options["cancel_event"] = cancelled

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual((raised.exception.status, raised.exception.reason), (499, "chat_cancelled"))
        self.transport.request.assert_not_called()

    def test_cancellation_during_retry_wait_prevents_second_provider_call(self) -> None:
        cancelled = threading.Event()
        self.options["cancel_event"] = cancelled
        self.transport.request.side_effect = AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded")
        self.retry.retry_delay.return_value = 0.01
        self.retry.wait.side_effect = lambda *_args: cancelled.set()

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.transport.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
