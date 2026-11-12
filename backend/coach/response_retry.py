"""Bounded retry policy and wait behavior for Coach provider responses."""

from __future__ import annotations

import logging
import secrets
import threading
import time

from backend.errors import AppError


class CoachResponseRetryPolicy:
    """Decide whether to retry a transient provider failure and perform its wait."""

    MAX_RETRY_DELAY_SECONDS = 60
    # Failures that leave nothing durable behind. Tools run locally and the
    # request is unchanged, so a repeat is idempotent while no output was shown.
    TRANSIENT_REASONS = frozenset(
        {"provider_unavailable", "network_error", "provider_timeout"}
    )
    TRANSIENT_BACKOFF_SECONDS = (2, 5)

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def retry_delay(
        self,
        exc: AppError,
        *,
        attempt: int,
        request_delta_emitted: bool,
        remote_conversation: bool = False,
    ) -> float | None:
        if self._transient(exc, remote_conversation=remote_conversation):
            if attempt >= len(self.TRANSIENT_BACKOFF_SECONDS) or request_delta_emitted:
                return None
            return (
                self.TRANSIENT_BACKOFF_SECONDS[attempt] + secrets.randbelow(1000) / 1000
            )
        rate_limited = (
            exc.reason == "rate_limit_exceeded"
            or getattr(exc, "provider_error_code", None) == "rate_limit_exceeded"
        )
        if not rate_limited or attempt == 2 or request_delta_emitted:
            return None
        retry_after = getattr(exc, "retry_after_seconds", None)
        if isinstance(retry_after, int):
            if retry_after > self.MAX_RETRY_DELAY_SECONDS:
                return None
            base_delay = retry_after
        else:
            base_delay = 5 * (attempt + 1)
        return base_delay + secrets.randbelow(1000) / 1000

    def _transient(self, exc: AppError, *, remote_conversation: bool) -> bool:
        if remote_conversation:
            # The provider may already hold this turn in a server-side
            # conversation; a repeat could duplicate it.
            return False
        return exc.reason in self.TRANSIENT_REASONS or (
            exc.reason == "response_failed"
            and getattr(exc, "provider_error_code", None) == "server_error"
        )

    def wait(
        self,
        delay: float,
        cancel_event: threading.Event | None,
        attempt: int,
        reason: str | None = None,
    ) -> None:
        context: dict[str, object] = {
            "attempt": attempt + 1,
            "retry_in_seconds": delay,
        }
        if reason in self.TRANSIENT_REASONS | {"response_failed"}:
            context["reason"] = reason
        self._logger.warning(
            "Coach response rate limited; retrying"
            if "reason" not in context
            else "Coach provider failure; retrying",
            extra={"event": "coach_response_retry", "context": context},
        )
        if cancel_event is not None:
            cancel_event.wait(delay)
        else:
            time.sleep(delay)
