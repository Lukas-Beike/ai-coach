"""Pure helpers for provider token-usage accounting."""

from __future__ import annotations

import json
from typing import Any

_USAGE_FIELDS = ("requests", "input_tokens", "output_tokens", "total_tokens")


def _decoded(value: Any) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
    return value


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _provider(provider: Any) -> str:
    if provider not in ("openai", "gemini"):
        raise ValueError("provider must be exactly 'openai' or 'gemini'")
    return provider


def _null_stand(today: Any) -> dict[str, Any]:
    return {
        "date": today,
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def _date_value(today: Any) -> Any:
    isoformat = getattr(today, "isoformat", None)
    return isoformat() if callable(isoformat) else today


def daily_summary(
    raw_usage: Any,
    *,
    today: Any,
    raw_status: Any = None,
    raw_rate_limits: Any = None,
) -> dict[str, Any]:
    """Return a normalized, persistable usage summary for ``today``."""
    today_value = _date_value(today)
    usage = _decoded(raw_usage)
    if not isinstance(usage, dict) or usage.get("date") != today_value:
        summary = _null_stand(today_value)
    else:
        summary = {"date": today_value}
        for field in _USAGE_FIELDS:
            summary[field] = _count(usage.get(field))
        for field in ("last_operation", "last_request_at"):
            if field in usage:
                summary[field] = usage[field]

    status = _decoded(raw_status)
    rate_limits = _decoded(raw_rate_limits)
    summary["status"] = dict(status) if isinstance(status, dict) else {}
    summary["rate_limits"] = dict(rate_limits) if isinstance(rate_limits, dict) else {}
    return summary


def usage_counts(response: Any, *, provider: str) -> dict[str, int]:
    """Extract safe token counters from one provider response."""
    provider = _provider(provider)
    if not isinstance(response, dict):
        raw: dict[str, Any] = {}
    elif provider == "openai":
        candidate = response.get("usage")
        raw = candidate if isinstance(candidate, dict) else {}
    else:
        candidate = response.get("usageMetadata")
        raw = candidate if isinstance(candidate, dict) else {}

    if provider == "openai":
        input_tokens = _count(raw.get("input_tokens") or raw.get("prompt_tokens"))
        output_tokens = _count(raw.get("output_tokens") or raw.get("completion_tokens"))
        total_tokens = _count(raw.get("total_tokens"))
    else:
        input_tokens = _count(raw.get("promptTokenCount"))
        output_tokens = _count(raw.get("candidatesTokenCount"))
        total_tokens = _count(raw.get("totalTokenCount"))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def recorded_usage(
    summary: Any,
    response: Any,
    *,
    provider: str,
    operation: Any,
    recorded_at: Any,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Return an updated daily state and the response's safe counter delta."""
    counts = usage_counts(response, provider=provider)
    source = summary if isinstance(summary, dict) else {}
    updated: dict[str, Any] = {}
    if "date" in source:
        updated["date"] = source["date"]
    for field in ("status", "rate_limits"):
        value = source.get(field)
        updated[field] = dict(value) if isinstance(value, dict) else {}
    for field in _USAGE_FIELDS:
        updated[field] = _count(source.get(field))
    updated["requests"] += 1
    updated["input_tokens"] += counts["input_tokens"]
    updated["output_tokens"] += counts["output_tokens"]
    updated["total_tokens"] += counts["total_tokens"]
    updated["last_operation"] = operation
    updated["last_request_at"] = recorded_at
    return updated, counts
