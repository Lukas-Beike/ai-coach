"""Stateless Garmin recovery record search and aggregation."""

from collections.abc import Sequence
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import flatten_daily_summary

UTC_OFFSET_SUFFIX = "+00:00"
AVERAGE_DAYS = 7


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _planning_context_date(value: Any) -> str:
    raw = iso_date_prefix(str(value or "").replace("Z", UTC_OFFSET_SUFFIX))
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return ""


def dated_garmin_recovery_records(value: Any) -> list[tuple[str, dict[str, Any]]]:
    """Find dated recovery records without returning Garmin's raw payload."""
    records: list[tuple[str, dict[str, Any]]] = []
    pending: list[Any] = [value]
    visited = 0
    while pending and visited < 2000:
        current = pending.pop()
        visited += 1
        if isinstance(current, dict):
            record_date = _planning_context_date(
                _first_present(current, garmin_perf_fields.RECORD_IDENTITY_KEYS)
            )
            if record_date:
                records.append((record_date, dict(flatten_daily_summary(current))))
            pending.extend(
                item for item in current.values() if isinstance(item, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend(
                item for item in current[:500] if isinstance(item, (dict, list))
            )
    return records


def rounded_average(values: Sequence[float]) -> float | None:
    """Average to two decimals, or None for no values."""
    return round(sum(values) / len(values), 2) if values else None
