"""Direct contracts for bounded Coach response retry behavior."""

from __future__ import annotations

import logging
import threading
import unittest
from unittest.mock import Mock, patch

from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.errors import AppError


class CoachResponseRetryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = Mock(spec=logging.Logger)
        self.policy = CoachResponseRetryPolicy(self.logger)

    @staticmethod
    def error(
        *, reason: str = "rate_limit_exceeded", provider_error_code: str | None = None
    ) -> AppError:
        error = AppError(429, "Synthetic rate limit", reason=reason)
        if provider_error_code is not None:
            error.provider_error_code = provider_error_code
        return error

    def delay(
        self,
        exc: AppError,
        *,
        attempt: int = 0,
        request_delta_emitted: bool = False,
    ) -> float | None:
        return self.policy.retry_delay(
            exc,
            attempt=attempt,
            request_delta_emitted=request_delta_emitted,
        )

    def test_openai_rate_limit_reason_and_provider_code_are_retryable(self) -> None:
        with patch(
            "backend.coach.response_retry.secrets.randbelow", return_value=250
        ) as randbelow:
            self.assertEqual(self.delay(self.error()), 5.25)
            self.assertEqual(
                self.delay(
                    self.error(
                        reason="provider_error",
                        provider_error_code="rate_limit_exceeded",
                    )
                ),
                5.25,
            )
        self.assertEqual(randbelow.call_count, 2)
        randbelow.assert_called_with(1000)

    def test_integer_retry_after_is_used_and_over_budget_is_rejected(self) -> None:
        allowed = self.error()
        allowed.retry_after_seconds = 7
        too_long = self.error()
        too_long.retry_after_seconds = (
            CoachResponseRetryPolicy.MAX_RETRY_DELAY_SECONDS + 1
        )
        with patch(
            "backend.coach.response_retry.secrets.randbelow", return_value=999
        ) as randbelow:
            self.assertEqual(self.delay(allowed), 7.999)
            self.assertIsNone(self.delay(too_long))
        randbelow.assert_called_once_with(1000)

    def test_fallback_delay_scales_by_attempt_and_adds_jitter(self) -> None:
        with patch(
            "backend.coach.response_retry.secrets.randbelow", return_value=99
        ) as randbelow:
            self.assertEqual(self.delay(self.error(), attempt=1), 10.099)
        randbelow.assert_called_once_with(1000)

    def test_transient_provider_failures_back_off_two_then_five_seconds(self) -> None:
        failures = (
            self.error(reason="provider_unavailable"),
            self.error(reason="network_error"),
            self.error(reason="provider_timeout"),
            self.error(reason="response_failed", provider_error_code="server_error"),
        )
        with patch("backend.coach.response_retry.secrets.randbelow", return_value=500):
            for failure in failures:
                with self.subTest(reason=failure.reason):
                    self.assertEqual(self.delay(failure, attempt=0), 2.5)
                    self.assertEqual(self.delay(failure, attempt=1), 5.5)
                    # Three attempts in total: nothing is scheduled after the third.
                    self.assertIsNone(self.delay(failure, attempt=2))

    def test_transient_failure_is_not_retried_after_output_was_emitted(self) -> None:
        self.assertIsNone(
            self.delay(
                self.error(reason="provider_unavailable"), request_delta_emitted=True
            )
        )

    def test_provider_timeout_after_a_response_exists_is_left_to_resume(self) -> None:
        failure = self.error(reason="provider_timeout")
        self.assertIsNone(
            self.policy.retry_delay(
                failure, attempt=0, request_delta_emitted=False, response_id_exists=True
            )
        )

    def test_other_failures_are_not_retried(self) -> None:
        for failure in (
            self.error(reason="response_failed"),
            self.error(reason="response_failed", provider_error_code="other"),
            self.error(reason="background_budget_exceeded"),
            self.error(reason="authentication_or_permission"),
            self.error(reason="chat_cancelled"),
        ):
            with self.subTest(reason=failure.reason):
                self.assertIsNone(self.delay(failure))

    def test_transient_wait_logs_the_failure_reason(self) -> None:
        self.policy.wait(2.5, None, 0, "provider_unavailable")
        context = self.logger.warning.call_args.kwargs["extra"]["context"]
        self.assertEqual(context["reason"], "provider_unavailable")
        self.assertEqual(context["attempt"], 1)

    def test_wait_uses_cancel_event_and_logs_retry_context(self) -> None:
        event = Mock(spec=threading.Event)

        self.policy.wait(7.25, event, 1)

        event.wait.assert_called_once_with(7.25)
        self.logger.warning.assert_called_once_with(
            "Coach response rate limited; retrying",
            extra={
                "event": "coach_response_retry",
                "context": {"attempt": 2, "retry_in_seconds": 7.25},
            },
        )

    def test_wait_without_cancel_event_uses_stdlib_sleep(self) -> None:
        with patch("backend.coach.response_retry.time.sleep") as sleep:
            self.policy.wait(5.125, None, 0)
        sleep.assert_called_once_with(5.125)


if __name__ == "__main__":
    unittest.main()
