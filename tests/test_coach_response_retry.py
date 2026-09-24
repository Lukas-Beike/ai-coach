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
    def error(*, reason: str = "rate_limit_exceeded", provider_error_code: str | None = None) -> AppError:
        error = AppError(429, "Synthetic rate limit", reason=reason)
        if provider_error_code is not None:
            error.provider_error_code = provider_error_code
        return error

    def delay(self, exc: AppError, *, ai_provider: str = "openai", attempt: int = 0, request_delta_emitted: bool = False) -> float | None:
        return self.policy.retry_delay(
            exc,
            ai_provider=ai_provider,
            attempt=attempt,
            request_delta_emitted=request_delta_emitted,
        )

    def test_openai_rate_limit_reason_and_provider_code_are_retryable(self) -> None:
        with patch("backend.coach.response_retry.secrets.randbelow", return_value=250) as randbelow:
            self.assertEqual(self.delay(self.error()), 5.25)
            self.assertEqual(
                self.delay(self.error(reason="provider_error", provider_error_code="rate_limit_exceeded")),
                5.25,
            )
        self.assertEqual(randbelow.call_count, 2)
        randbelow.assert_called_with(1000)

    def test_gemini_non_rate_limit_attempt_two_and_streamed_delta_do_not_retry(self) -> None:
        with patch("backend.coach.response_retry.secrets.randbelow") as randbelow:
            self.assertIsNone(self.delay(self.error(), ai_provider="gemini"))
            self.assertIsNone(self.delay(self.error(reason="provider_error")))
            self.assertIsNone(self.delay(self.error(), attempt=2))
            self.assertIsNone(self.delay(self.error(), request_delta_emitted=True))
        randbelow.assert_not_called()

    def test_integer_retry_after_is_used_and_over_budget_is_rejected(self) -> None:
        allowed = self.error()
        allowed.retry_after_seconds = 7
        too_long = self.error()
        too_long.retry_after_seconds = CoachResponseRetryPolicy.MAX_RETRY_DELAY_SECONDS + 1
        with patch("backend.coach.response_retry.secrets.randbelow", return_value=999) as randbelow:
            self.assertEqual(self.delay(allowed), 7.999)
            self.assertIsNone(self.delay(too_long))
        randbelow.assert_called_once_with(1000)

    def test_fallback_delay_scales_by_attempt_and_adds_jitter(self) -> None:
        with patch("backend.coach.response_retry.secrets.randbelow", return_value=99) as randbelow:
            self.assertEqual(self.delay(self.error(), attempt=1), 10.099)
        randbelow.assert_called_once_with(1000)

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
