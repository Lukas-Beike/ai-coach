"""Strict, provenance preserving projections for optional Garmin history APIs."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

GARMIN_SOURCE = "Garmin Connect"

_DATE_KEYS = ("date", "calendarDate", "summaryDate")
_IGNORED_NUMERIC_KEYS = {"id", "activityId", "userId"}


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, (bool, dict, list)):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _observed(record: dict[str, Any]) -> date | None:
    days = {_day(record.get(key)) for key in _DATE_KEYS}
    days.discard(None)
    return next(iter(days)) if len(days) == 1 else None


def _scalar_fields(record: dict[str, Any]) -> dict[str, float]:
    fields: dict[str, float] = {}
    for key, value in record.items():
        if key in _IGNORED_NUMERIC_KEYS or key in _DATE_KEYS:
            continue
        number = _number(value)
        if number is not None:
            fields[str(key)[:80]] = number
    return fields


def ftp_points(value: Any, *, start: date, end: date) -> list[dict[str, Any]]:
    """Return only dated finite cycling FTP values from the range response."""
    points: dict[str, dict[str, Any]] = {}
    for record in _records(value):
        observed = _observed(record)
        if observed is None or not start <= observed <= end:
            continue
        candidate = _number(record.get("functionalThresholdPower"))
        if candidate is None or not 20 <= candidate <= 2000:
            continue
        points[observed.isoformat()] = {
            "date": observed.isoformat(),
            "value": round(candidate, 2),
            "source": GARMIN_SOURCE,
            "field": "functionalThresholdPower",
        }
    return [points[key] for key in sorted(points)]


def metric_points(value: Any, *, start: date, end: date) -> list[dict[str, Any]]:
    """Return dated numeric fields without assigning unknown Garmin units."""
    points: dict[str, dict[str, Any]] = {}
    for record in _records(value):
        observed = _observed(record)
        if observed is None or not start <= observed <= end:
            continue
        fields = _scalar_fields(record)
        if not fields:
            continue
        point = points.setdefault(
            observed.isoformat(),
            {"date": observed.isoformat(), "values": {}, "source": GARMIN_SOURCE},
        )
        point["values"].update(fields)
    return [points[key] for key in sorted(points)]


def projected_metric(
    value: Any,
    *,
    start: date,
    end: date,
    aggregation: str,
    metric: str,
    synced_at: Any,
) -> dict[str, Any]:
    points = metric_points(value, start=start, end=end)
    return {
        "status": "current" if points else "unavailable",
        "aggregation": aggregation,
        "source": GARMIN_SOURCE,
        "unit": "unknown",
        "points": points,
        "observed_at": points[-1]["date"] if points else None,
        "fetched_at": synced_at,
        "metric": metric,
    }
