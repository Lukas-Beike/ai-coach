"""Shared lifecycle observation for provider synchronization operations."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any

from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.refresh import ProviderRefreshTracker

OPERATION_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "operation_context", default=None
)

_TRIGGERS = {
    "startup": "startup",
    "manuell": "manual",
    "manual": "manual",
    "chat-anfrage": "chat",
    "morgen-check-in": "checkin",
    "vollständiger resync": "full_resync",
    "background": "background",
}
_COUNT_KEYS = (
    "activities",
    "records",
    "events",
    "wellness",
    "total",
    "imported",
    "updated",
    "pushed",
)


def operation_context() -> dict[str, str] | None:
    """Return the current operation correlation without exposing its owner."""
    return OPERATION_CONTEXT.get()


def operation_trigger(reason: Any) -> str:
    """Reduce an internal reason to a safe, bounded operation class."""
    normalized = str(reason or "background").strip().casefold()
    return _TRIGGERS.get(normalized, "background")


def operation_error_code(error: BaseException) -> str:
    """Return a stable technical code without logging exception contents."""
    if isinstance(error, AppError) and error.reason:
        return (
            re.sub(r"[^a-z0-9_]+", "_", str(error.reason).casefold()).strip("_")[:80]
            or "application_error"
        )
    if isinstance(error, TimeoutError):
        return "timeout"
    return "internal_error"


def operation_result_count(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None
    for key in _COUNT_KEYS:
        value = result.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def refresh_status(result: Any) -> str:
    status = result.get("status") if isinstance(result, dict) else None
    return {
        "not_configured": "skipped",
        "stale": "error",
        "error": "error",
        "failed": "error",
        "partial": "partial",
    }.get(status, "success")


def log_operation_event(
    logger: logging.Logger,
    event: str,
    operation_id: str,
    trigger: str,
    provider: str,
    phase: str,
    started: float,
    *,
    count: int | None = None,
    error_code: str | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> None:
    context: dict[str, Any] = {
        "operation_id": operation_id,
        "trigger": trigger,
        "provider": provider,
        "phase": phase,
        "duration_ms": round((monotonic() - started) * 1000, 1),
    }
    if count is not None:
        context["count"] = count
    if error_code:
        context["error_code"] = error_code
    logger.log(
        logging.ERROR if error_code else logging.INFO,
        "Synchronization operation",
        extra={"event": event, "context": context},
    )


@dataclass
class OperationScope:
    operation_id: str
    trigger: str
    started: float
    result: Any = None


class SyncOperationObserver:
    """Own maintenance, correlation, refresh history, and safe operation logs."""

    def __init__(
        self,
        refresh_tracker: ProviderRefreshTracker,
        maintenance_gate: MaintenanceGate,
        logger: logging.Logger,
        *,
        monotonic: Callable[[], float] = time.perf_counter,
        operation_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._refresh_tracker = refresh_tracker
        self._maintenance_gate = maintenance_gate
        self._logger = logger
        self._monotonic = monotonic
        self._operation_id_factory = operation_id_factory

    @contextmanager
    def observe(
        self,
        provider: str,
        area: str,
        reason: Any = "background",
        operation_id: str | None = None,
    ) -> Iterator[OperationScope]:
        """Observe one sync while preserving nested operation correlation."""
        with self._maintenance_gate.operation():
            current = OPERATION_CONTEXT.get() or {}
            resolved_id = (
                operation_id
                or current.get("operation_id")
                or self._operation_id_factory()
            )
            trigger = current.get("trigger") or operation_trigger(reason)
            token = OPERATION_CONTEXT.set(
                {"operation_id": resolved_id, "trigger": trigger}
            )
            scope = OperationScope(resolved_id, trigger, self._monotonic())
            self._log("operation_started", provider, "start", scope)
            try:
                refresh_id = self._refresh_tracker.start(
                    provider, area, scope.operation_id, scope.trigger
                )
                try:
                    yield scope
                except Exception as error:
                    self._finish_error(refresh_id, error)
                    raise
                self._refresh_tracker.finish(
                    refresh_id, refresh_status(scope.result), "complete"
                )
                self._log(
                    "operation_count",
                    provider,
                    "complete",
                    scope,
                    count=operation_result_count(scope.result),
                )
            except Exception as error:
                self._log(
                    "operation_failed",
                    provider,
                    "failed",
                    scope,
                    error_code=operation_error_code(error),
                )
                raise
            else:
                self._log("operation_completed", provider, "complete", scope)
            finally:
                OPERATION_CONTEXT.reset(token)

    def _finish_error(self, refresh_id: str, error: BaseException) -> None:
        if isinstance(error, AppError) and error.reason == "chat_cancelled":
            self._refresh_tracker.finish(refresh_id, "skipped", "cancelled")
            return
        self._refresh_tracker.finish(
            refresh_id,
            "error",
            "failed",
            error_code=ProviderRefreshTracker.error_code(error),
        )

    def _log(
        self,
        event: str,
        provider: str,
        phase: str,
        scope: OperationScope,
        *,
        count: int | None = None,
        error_code: str | None = None,
    ) -> None:
        log_operation_event(
            self._logger,
            event,
            scope.operation_id,
            scope.trigger,
            provider,
            phase,
            scope.started,
            count=count,
            error_code=error_code,
            monotonic=self._monotonic,
        )


def observed_sync(
    observer_factory: Callable[[], SyncOperationObserver],
    provider: str,
    area: str = "default",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a transitional composition-root sync with backend observation."""

    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            reason = kwargs.get("reason")
            if reason is None and args:
                reason = args[0]
            with observer_factory().observe(
                provider, area, reason, kwargs.get("operation_id")
            ) as scope:
                result = function(*args, **kwargs)
                scope.result = result
                return result

        return wrapped

    return decorator
