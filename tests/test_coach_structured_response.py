from __future__ import annotations

import logging
import threading
import unittest
from typing import Any
from unittest.mock import Mock, patch

from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.structured_response import CoachStructuredResponseService
from backend.errors import AppError
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.state import metered_turn


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
        self.payload = ModelRequest(
            model="synthetic", instructions="synthetic", input="synthetic"
        )
        self.options: dict[str, Any] = {
            "turn_request": self.payload,
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

    def test_request_streams_and_drops_deltas_when_no_stream_is_attached(self) -> None:
        expected = ModelTurn()
        self.transport.stream_request.return_value = expected

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.transport.stream_request.assert_called_once()
        args = self.transport.stream_request.call_args.args
        self.assertEqual(args[0], self.payload)
        self.assertIsNone(self.transport.stream_request.call_args.args[2])
        args[1]("dropped")
        self.transport.request.assert_not_called()
        self.jobs.merge_receipt.assert_not_called()

    def test_job_marks_that_openai_was_reached_without_keeping_the_response_id(
        self,
    ) -> None:
        expected = ModelTurn()

        def finish(_payload, _on_delta, _cancel_event, on_response_id):
            on_response_id("resp-new")
            return expected

        self.transport.stream_request.side_effect = finish
        self.options["background_owned"] = True

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.jobs.merge_receipt.assert_called_once_with(
            "turn-synthetic",
            {"status": "running", "phase": "waiting_openai", "openai_reached": True},
        )

    def test_background_job_keeps_the_usage_so_far_for_a_restart(self) -> None:
        self.transport.stream_request.return_value = ModelTurn()
        self.options["background_owned"] = True

        with metered_turn({"requests": 1, "output_tokens": 7}):
            self.service.respond(self.payload, **self.options)

        self.jobs.merge_receipt.assert_called_once_with(
            "turn-synthetic",
            {
                "usage": {
                    "requests": 1,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 7,
                }
            },
        )

    def test_rate_limit_retries_without_stream_delta(self) -> None:
        expected = ModelTurn()
        self.transport.stream_request.side_effect = [
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"),
            expected,
        ]
        self.retry.retry_delay.return_value = 0.01

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(self.transport.stream_request.call_count, 2)
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
        expected = ModelTurn()
        self.transport.stream_request.side_effect = [
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
        self.assertEqual(self.transport.stream_request.call_count, 2)
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
        self.transport.stream_request.assert_not_called()

    def test_cancellation_during_retry_wait_prevents_second_provider_call(self) -> None:
        cancelled = threading.Event()
        self.options["cancel_event"] = cancelled
        self.transport.stream_request.side_effect = AppError(
            429, "Synthetic rate limit", reason="rate_limit_exceeded"
        )
        self.retry.retry_delay.return_value = 0.01
        self.retry.wait.side_effect = lambda *_args: cancelled.set()

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.transport.stream_request.assert_called_once()

    @staticmethod
    def _incomplete(text: str = "", tool_calls: tuple[dict, ...] = ()) -> ModelTurn:
        return ModelTurn(
            text=text, tool_calls=list(tool_calls), stop_reason="max_tokens"
        )

    def test_reasoning_only_token_exhaustion_repeats_with_the_larger_budget(
        self,
    ) -> None:
        self.payload.max_output_tokens = 16_000
        expected = ModelTurn(text="Fertig")
        responses = [self._incomplete(), expected]
        sent: list[int] = []

        def serve(request, *_args, **_kwargs):
            sent.append(request.max_output_tokens)
            return responses.pop(0)

        self.transport.stream_request.side_effect = serve

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(sent, [16_000, 32_000])
        # Later tool rounds keep the larger budget.
        self.assertEqual(self.payload.max_output_tokens, 32_000)

    def test_token_exhaustion_is_returned_when_text_or_a_tool_call_exists(
        self,
    ) -> None:
        self.payload.max_output_tokens = 16_000
        for name, partial in (
            ("text", self._incomplete("Teilantwort")),
            (
                "tool_call",
                self._incomplete(
                    tool_calls=({"call_id": "call-1", "name": "read_profile"},)
                ),
            ),
        ):
            with self.subTest(item=name):
                self.transport.stream_request.reset_mock()
                response = partial
                self.transport.stream_request.return_value = response

                self.assertIs(
                    self.service.respond(self.payload, **self.options), response
                )
                self.transport.stream_request.assert_called_once()

    def test_token_exhaustion_is_not_repeated_in_a_server_side_conversation(
        self,
    ) -> None:
        self.payload.max_output_tokens = 16_000
        self.payload.conversation_id = "conv-synthetic"
        response = self._incomplete()
        self.transport.stream_request.return_value = response

        self.assertIs(self.service.respond(self.payload, **self.options), response)

        self.transport.stream_request.assert_called_once()

    def test_token_exhaustion_after_retryable_failures_still_gets_the_larger_budget(
        self,
    ) -> None:
        self.payload.max_output_tokens = 16_000
        self.retry.retry_delay.return_value = 0.01
        expected = ModelTurn(text="Fertig")
        sent: list[int] = []
        responses = [
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"),
            AppError(429, "Synthetic rate limit", reason="rate_limit_exceeded"),
            self._incomplete(),
            expected,
        ]

        def serve(request, *_args, **_kwargs):
            sent.append(request.max_output_tokens)
            result = responses.pop(0)
            if isinstance(result, AppError):
                raise result
            return result

        self.transport.stream_request.side_effect = serve

        self.assertIs(self.service.respond(self.payload, **self.options), expected)

        self.assertEqual(sent, [16_000, 16_000, 16_000, 32_000])

    def test_token_exhaustion_is_not_repeated_at_the_larger_budget(self) -> None:
        self.payload.max_output_tokens = 32_000
        response = self._incomplete()
        self.transport.stream_request.return_value = response

        self.assertIs(self.service.respond(self.payload, **self.options), response)

        self.transport.stream_request.assert_called_once()


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
        self.payload = ModelRequest(model="m", instructions="synthetic")
        self.options: dict[str, Any] = {
            "turn_request": self.payload,
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
        expected = ModelTurn()
        for status, reason in (
            (502, "provider_unavailable"),
            (503, "provider_unavailable"),
            (502, "network_error"),
        ):
            with self.subTest(reason=reason, status=status):
                self.sleep.reset_mock()
                self.transport.stream_request.reset_mock()
                self.transport.stream_request.side_effect = [
                    self.failure(status, reason),
                    self.failure(status, reason),
                    expected,
                ]
                self.assertIs(
                    self.service.respond(self.payload, **self.options), expected
                )
                self.assertEqual(self.transport.stream_request.call_count, 3)
                self.assertEqual(
                    [call.args[0] for call in self.sleep.call_args_list], [2, 5]
                )

    def test_provider_server_error_response_before_output_is_retried(self) -> None:
        failed = _ServerErrorFailure(
            502, "Synthetic provider failure", reason="response_failed"
        )
        expected = ModelTurn()
        self.transport.stream_request.side_effect = [failed, expected]

        self.assertIs(self.service.respond(self.payload, **self.options), expected)
        self.sleep.assert_called_once_with(2)

    def test_job_failure_after_the_response_started_is_requested_again(self) -> None:
        expected = ModelTurn()
        calls = 0

        def stream(_payload, _on_delta, _cancel_event, on_response_id):
            nonlocal calls
            calls += 1
            on_response_id("resp-started")
            if calls == 1:
                raise self.failure(503, "provider_unavailable")
            return expected

        self.transport.stream_request.side_effect = stream
        self.options["background_owned"] = True

        self.assertIs(self.service.respond(self.payload, **self.options), expected)
        self.assertEqual(calls, 2)
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
        self.transport.stream_request.side_effect = self.failure(
            503, "provider_unavailable"
        )

        with self.assertRaises(AppError) as raised:
            self.service.respond(self.payload, **self.options)

        self.assertEqual(raised.exception.reason, "provider_unavailable")
        self.assertEqual(self.transport.stream_request.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
