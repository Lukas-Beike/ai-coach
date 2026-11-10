from __future__ import annotations

import logging
import threading
import unittest
from typing import Any
from unittest.mock import Mock, patch

from backend.coach.response_retry import CoachResponseRetryPolicy
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
        self.payload: dict[str, Any] = {
            "input": [{"role": "user", "content": "synthetic"}],
            "model": "synthetic",
        }
        self.options: dict[str, Any] = {
            "request_payload": self.payload,
            "context": {"synthetic": True},
            "message": "Synthetic question",
            "command_receipts": [],
            "attachments": [],
            "client_turn_id": "turn-synthetic",
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

        self.assertEqual(
            self.transport.background_request.call_args.kwargs["response_id"],
            "resp-prior",
        )
        self.jobs.merge_receipt.assert_called_once_with(
            "turn-synthetic",
            {
                "status": "running",
                "phase": "waiting_openai",
                "openai_response_id": "resp-new",
                "pending_tool_outputs": [],
                "response_input": self.payload["input"],
                "previous_response_id": None,
            },
        )

    def test_transient_background_error_resumes_the_checkpointed_response(self) -> None:
        expected = {"id": "resumed-response"}

        calls = 0

        def respond(_payload, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                kwargs["on_response_id"]("resp-new")
                raise AppError(
                    503, "Synthetic provider unavailable", reason="provider_unavailable"
                )
            return expected

        self.transport.background_request.side_effect = respond
        self.options["background_owned"] = True

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(self.transport.background_request.call_count, 2)
        self.assertEqual(
            [
                item.kwargs["response_id"]
                for item in self.transport.background_request.call_args_list
            ],
            [None, "resp-new"],
        )
        self.retry.retry_delay.assert_not_called()
        self.recovery.recover_if_invalid.assert_not_called()

    def test_rate_limit_retries_without_stream_delta(self) -> None:
        expected = {"id": "after-retry"}
        self.transport.request.side_effect = [
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"),
            expected,
        ]
        self.retry.retry_delay.return_value = 0.01

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(self.transport.request.call_count, 2)
        self.retry.retry_delay.assert_called_once()
        self.assertEqual(
            self.retry.retry_delay.call_args.kwargs["request_delta_emitted"], False
        )
        self.retry.wait.assert_called_once_with(0.01, None, 0, "rate_limit_exceeded")

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
        self.assertEqual(
            self.retry.retry_delay.call_args.kwargs["request_delta_emitted"], True
        )
        self.transport.stream_request.assert_called_once()

    def test_invalid_conversation_recovery_retries_once_with_shared_payload(
        self,
    ) -> None:
        expected = {"id": "recovered"}
        self.transport.request.side_effect = [
            AppError(
                409,
                "Synthetic invalid conversation",
                reason="conversation_state_invalid",
            ),
            expected,
        ]
        self.recovery.recover_if_invalid.return_value = True

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.recovery.recover_if_invalid.assert_called_once()
        self.assertIs(self.recovery.recover_if_invalid.call_args.args[1], self.payload)
        self.assertEqual(
            self.recovery.recover_if_invalid.call_args.kwargs["attempt"], 0
        )
        self.assertEqual(self.transport.request.call_count, 2)
        self.retry.retry_delay.assert_not_called()

    def test_cancellation_before_request_never_calls_provider(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        self.options["cancel_event"] = cancelled

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(
            (raised.exception.status, raised.exception.reason), (499, "chat_cancelled")
        )
        self.transport.request.assert_not_called()

    def test_cancellation_during_retry_wait_prevents_second_provider_call(self) -> None:
        cancelled = threading.Event()
        self.options["cancel_event"] = cancelled
        self.transport.request.side_effect = AppError(
            429, "Synthetic rate limit", reason="rate_limit_exceeded"
        )
        self.retry.retry_delay.return_value = 0.01
        self.retry.wait.side_effect = lambda *_args: cancelled.set()

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.transport.request.assert_called_once()

    @staticmethod
    def _incomplete(*output: dict) -> dict:
        return {
            "id": "synthetic-incomplete",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": list(output),
        }

    def test_reasoning_only_token_exhaustion_repeats_with_the_larger_budget(
        self,
    ) -> None:
        self.payload["max_output_tokens"] = 16_000
        expected = {"id": "after-escalation", "status": "completed"}
        responses = [self._incomplete({"type": "reasoning"}), expected]
        sent: list[int] = []

        def request(payload):
            sent.append(payload["max_output_tokens"])
            return responses.pop(0)

        self.transport.request.side_effect = request

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(sent, [16_000, 32_000])
        # Later tool rounds keep the larger budget.
        self.assertEqual(self.payload["max_output_tokens"], 32_000)

    def test_token_exhaustion_is_returned_when_text_or_a_tool_call_exists(
        self,
    ) -> None:
        self.payload["max_output_tokens"] = 16_000
        for item in (
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Teilantwort"}],
            },
            {"type": "function_call", "name": "read_profile", "call_id": "call-1"},
        ):
            with self.subTest(item=item["type"]):
                self.transport.request.reset_mock()
                response = self._incomplete(item)
                self.transport.request.return_value = response

                self.assertIs(
                    self.service.respond(self.payload, **self.options), response
                )
                self.transport.request.assert_called_once()

    def test_token_exhaustion_is_not_repeated_in_a_server_side_conversation(
        self,
    ) -> None:
        self.payload["max_output_tokens"] = 16_000
        self.payload["conversation"] = "conv-synthetic"
        response = self._incomplete({"type": "reasoning"})
        self.transport.request.return_value = response

        self.assertIs(self.service.respond(self.payload, **self.options), response)

        self.transport.request.assert_called_once()

    def test_token_exhaustion_after_retryable_failures_still_gets_the_larger_budget(
        self,
    ) -> None:
        self.payload["max_output_tokens"] = 16_000
        self.retry.retry_delay.return_value = 0.01
        expected = {"id": "after-escalation", "status": "completed"}
        sent: list[int] = []
        responses = [
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"),
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"),
            self._incomplete({"type": "reasoning"}),
            expected,
        ]

        def request(payload):
            sent.append(payload["max_output_tokens"])
            result = responses.pop(0)
            if isinstance(result, AppError):
                raise result
            return result

        self.transport.request.side_effect = request

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(sent, [16_000, 16_000, 16_000, 32_000])

    def test_token_exhaustion_in_a_resumed_background_response_is_repeated(
        self,
    ) -> None:
        self.payload["max_output_tokens"] = 16_000
        self.options["background_owned"] = True
        self.options["resume_id"] = "resp-prior"
        expected = {"id": "after-escalation", "status": "completed"}
        responses = [
            AppError(
                503, "Synthetic provider unavailable", reason="provider_unavailable"
            ),
            self._incomplete({"type": "reasoning"}),
            expected,
        ]
        sent: list[int] = []

        def background(payload, **_kwargs):
            sent.append(payload["max_output_tokens"])
            result = responses.pop(0)
            if isinstance(result, AppError):
                raise result
            return result

        self.transport.background_request.side_effect = background

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(sent, [16_000, 16_000, 32_000])
        self.assertEqual(
            self.transport.background_request.call_args.kwargs["response_id"], None
        )

    def test_token_exhaustion_is_not_repeated_at_the_larger_budget(self) -> None:
        self.payload["max_output_tokens"] = 32_000
        response = self._incomplete({"type": "reasoning"})
        self.transport.request.return_value = response

        self.assertIs(self.service.respond(self.payload, **self.options), response)

        self.transport.request.assert_called_once()


class _ServerErrorFailure(AppError):
    provider_error_code = "server_error"


class CoachTransientRetryTests(unittest.TestCase):
    """The real retry policy with mocked transports and no real sleeping."""

    def setUp(self) -> None:
        self.transport = Mock()
        self.recovery = Mock()
        self.recovery.recover_if_invalid.return_value = False
        self.service = CoachStructuredResponseService(
            self.transport,
            self.recovery,
            CoachResponseRetryPolicy(Mock(spec=logging.Logger)),
            Mock(),
        )
        self.payload: dict[str, Any] = {"input": [{"role": "user"}], "model": "m"}
        self.options: dict[str, Any] = {
            "request_payload": self.payload,
            "context": {},
            "message": "Synthetic question",
            "command_receipts": [],
            "attachments": [],
            "client_turn_id": "turn-synthetic",
            "background_owned": False,
            "on_text_delta": None,
            "cancel_event": None,
            "recovery_state": {"conversation_recovered": False},
        }
        sleep = patch("backend.coach.response_retry.time.sleep")
        jitter = patch("backend.coach.response_retry.secrets.randbelow", return_value=0)
        self.sleep = sleep.start()
        jitter.start()
        self.addCleanup(sleep.stop)
        self.addCleanup(jitter.stop)

    @staticmethod
    def failure(status: int, reason: str) -> AppError:
        return AppError(status, "Synthetic provider failure", reason=reason)

    def test_gateway_and_network_failures_before_output_are_retried(self) -> None:
        expected = {"id": "completed"}
        for status, reason in (
            (502, "provider_unavailable"),
            (503, "provider_unavailable"),
            (502, "network_error"),
        ):
            with self.subTest(reason=reason, status=status):
                self.sleep.reset_mock()
                self.transport.request.reset_mock()
                self.transport.request.side_effect = [
                    self.failure(status, reason),
                    self.failure(status, reason),
                    expected,
                ]
                self.assertIs(
                    self.service.respond(self.payload, **self.options), expected
                )
                self.assertEqual(self.transport.request.call_count, 3)
                self.assertEqual(
                    [call.args[0] for call in self.sleep.call_args_list], [2, 5]
                )

    def test_provider_server_error_response_before_output_is_retried(self) -> None:
        failed = _ServerErrorFailure(
            502, "Synthetic provider failure", reason="response_failed"
        )
        expected = {"id": "completed"}
        self.transport.request.side_effect = [failed, expected]

        self.assertIs(self.service.respond(self.payload, **self.options), expected)
        self.sleep.assert_called_once_with(2)

    def test_stream_failure_after_output_is_not_retried(self) -> None:
        def stream(_payload, on_delta, *_args, **_kwargs):
            on_delta("partial")
            raise self.failure(503, "provider_unavailable")

        self.transport.stream_request.side_effect = stream
        self.options["on_text_delta"] = lambda _delta: None

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "provider_unavailable")
        self.transport.stream_request.assert_called_once()
        self.sleep.assert_not_called()

    def test_retries_stay_within_three_attempts(self) -> None:
        self.transport.request.side_effect = self.failure(503, "provider_unavailable")

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "provider_unavailable")
        self.assertEqual(self.transport.request.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_budget_exhaustion_is_neither_resumed_nor_retried(self) -> None:
        def run(_payload, **kwargs):
            kwargs["on_response_id"]("resp-budget")
            raise self.failure(504, "background_budget_exceeded")

        self.transport.background_request.side_effect = run
        self.options["background_owned"] = True

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "background_budget_exceeded")
        self.transport.background_request.assert_called_once()
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
