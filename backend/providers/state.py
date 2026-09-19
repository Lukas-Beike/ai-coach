"""Durable provider status, usage, and OpenAI rate-limit state."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from backend import observability
from backend.providers import openai as openai_provider
from backend.providers import usage as provider_usage

_PROVIDERS = frozenset({"openai", "gemini"})
_STATUS_KEYS = {provider: f"{provider}_status" for provider in _PROVIDERS}
_USAGE_KEYS = {provider: f"{provider}_usage" for provider in _PROVIDERS}
_OPENAI_RATE_LIMITS_KEY = "openai_rate_limits"
_SAFE_CODE = re.compile(r"(?a)^[a-z0-9][a-z0-9_.:/-]{0,79}$")


def _provider(value: Any) -> str:
    if value not in _PROVIDERS:
        raise ValueError("provider must be exactly 'openai' or 'gemini'")
    return value


def _safe_code(value: Any, default: str = "unknown") -> str:
    candidate = value.strip() if isinstance(value, str) else ""
    return candidate if _SAFE_CODE.fullmatch(candidate) else default


def _safe_message(value: Any) -> str:
    return str(value or "")[:300]


def _timestamp(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value or "")


def _safe_http_status(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        try:
            return int(value.strip())
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _safe_json_value(value: Any) -> Any:
    """Return a JSON value without allowing non-finite or custom objects."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _safe_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item) for item in value]
    return str(value)[:300]


def _json(value: Any) -> str:
    return json.dumps(
        _safe_json_value(value), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


class ProviderStateService:
    """Own persisted provider observability state and its transaction boundary."""

    def __init__(
        self,
        manager: Any,
        repository: Any,
        lock: Any,
        now: Callable[[], Any],
        today: Callable[[], Any],
        logger: Any | None = None,
    ) -> None:
        self._manager = manager
        self._repository = repository
        self._lock = lock
        self._now = now
        self._today = today
        self._logger = logger

    def _summary_unlocked(self, db: Any, provider: str) -> dict[str, Any]:
        raw_rate_limits = (
            self._repository.get(db, _OPENAI_RATE_LIMITS_KEY) if provider == "openai" else None
        )
        summary = provider_usage.daily_summary(
            self._repository.get(db, _USAGE_KEYS[provider]),
            today=self._today(),
            raw_status=self._repository.get(db, _STATUS_KEYS[provider]),
            raw_rate_limits=raw_rate_limits,
        )
        if provider == "gemini":
            summary.pop("rate_limits", None)
        return summary

    def summary(self, provider: str) -> dict[str, Any]:
        provider = _provider(provider)
        with self._lock, self._manager.unit_of_work() as db:
            return self._summary_unlocked(db, provider)

    def record_status(
        self,
        provider: str,
        *,
        state: Any,
        reason: Any,
        message: Any,
        http_status: Any = None,
        provider_error_code: Any = None,
    ) -> None:
        provider = _provider(provider)
        with self._lock, self._manager.unit_of_work() as db:
            self._record_status_unlocked(
                db,
                provider,
                state=state,
                reason=reason,
                message=message,
                http_status=http_status,
                provider_error_code=provider_error_code,
            )

    def _record_status_unlocked(
        self,
        db: Any,
        provider: str,
        *,
        state: Any,
        reason: Any,
        message: Any,
        http_status: Any,
        provider_error_code: Any,
    ) -> None:
        status: dict[str, Any] = {
            "state": _safe_code(state),
            "reason": _safe_code(reason),
            "message": _safe_message(message),
            "http_status": _safe_http_status(http_status),
            "updated_at": _timestamp(self._now()),
        }
        if (
            provider == "openai"
            and isinstance(provider_error_code, str)
            and provider_error_code in observability.OPENAI_RESPONSE_ERROR_CODES
        ):
            status["provider_error_code"] = provider_error_code
        self._repository.set(db, _STATUS_KEYS[provider], _json(status))

    def record_success(self, provider: str, http_status: Any = 200) -> None:
        provider = _provider(provider)
        with self._lock, self._manager.unit_of_work() as db:
            self._record_status_unlocked(
                db,
                provider,
                state="ok",
                reason="ok",
                message=("OpenAI" if provider == "openai" else "Gemini") + " ist verfügbar.",
                http_status=http_status,
                provider_error_code=None,
            )

    def record_rate_limits(self, headers: Any) -> None:
        with self._lock, self._manager.unit_of_work() as db:
            snapshot = openai_provider.rate_limit_snapshot(
                headers, updated_at=_timestamp(self._now())
            )
            if snapshot:
                self._repository.set(db, _OPENAI_RATE_LIMITS_KEY, _json(snapshot))

    def record_usage(
        self, provider: str, response: Any, operation: Any
    ) -> dict[str, int]:
        provider = _provider(provider)
        safe_operation = _safe_code(operation, default="unknown")
        with self._lock, self._manager.unit_of_work() as db:
            summary = self._summary_unlocked(db, provider)
            updated, counts = provider_usage.recorded_usage(
                summary,
                response,
                provider=provider,
                operation=safe_operation,
                recorded_at=_timestamp(self._now()),
            )
            self._repository.set(db, _USAGE_KEYS[provider], _json(updated))
        if self._logger is not None:
            self._logger.info(
                "Provider usage recorded",
                extra={
                    "event": "provider_usage",
                    "context": {"operation": safe_operation, **counts},
                },
            )
        return counts
