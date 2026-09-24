"""Bounded retry policy and wait behavior for Coach provider responses."""

from __future__ import annotations

import logging
import secrets
import threading
import time

from backend.errors import AppError


class CoachResponseRetryPolicy:
    """Decide whether to retry a rate-limited response and perform its wait."""

    MAX_RETRY_DELAY_SECONDS = 60

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def retry_delay(
        self,
        exc: AppError,
        *,
        ai_provider: str,
        attempt: int,
        request_delta_emitted: bool,
    ) -> float | None:
        rate_limited = (
            exc.reason == "rate_limit_exceeded"
            or getattr(exc, "provider_error_code", None) == "rate_limit_exceeded"
        )
        if ai_provider != "openai" or not rate_limited or attempt == 2 or request_delta_emitted:
            return None
        retry_after = getattr(exc, "retry_after_seconds", None)
        if isinstance(retry_after, int):
            if retry_after > self.MAX_RETRY_DELAY_SECONDS:
                return None
            base_delay = retry_after
        else:
            base_delay = 5 * (attempt + 1)
        return base_delay + secrets.randbelow(1000) / 1000

    def wait(
        self, delay: float, cancel_event: threading.Event | None, attempt: int
    ) -> None:
        self._logger.warning(
            "Coach response rate limited; retrying",
            extra={
                "event": "coach_response_retry",
                "context": {"attempt": attempt + 1, "retry_in_seconds": delay},
            },
        )
        if cancel_event is not None:
            cancel_event.wait(delay)
        else:
            time.sleep(delay)
