"""Garmin daily-health normalization and aggregate projections."""

import math
from datetime import date, timedelta
from typing import Any

from backend.performance import freshness as performance_freshness
from backend.performance import recovery as performance_recovery

GARMIN_PERFORMANCE_SOURCE = "Garmin Connect"

GARMIN_DAILY_HEALTH_FIELDS = {
    "steps": ("totalSteps", "total_steps", "steps", "stepCount", "step_count"),
    "floors": (
        "floorsAscended",
        "floors_ascended",
        "floors",
        "floorsUp",
        "floors_up",
    ),
    "calories": (
        "totalKilocalories",
        "total_kilocalories",
        "totalCalories",
        "total_calories",
        "calories",
    ),
}


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _metric(
    value: Any, unit: str, source: str | None, note: str = ""
) -> dict[str, Any]:
    number = _as_number(value)
    return {
        "value": number,
        "unit": unit,
        "source": source if number is not None else None,
        "note": note if number is not None else "",
    }


def garmin_daily_health_by_date(
    snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build a small date-indexed view of Garmin's daily activity totals."""
    health_by_date: dict[str, dict[str, Any]] = {}
    for record_date, record in performance_recovery.dated_garmin_recovery_records(
        snapshot.get("daily_stats")
    ):
        health = health_by_date.setdefault(record_date, {})
        for metric_name, keys in GARMIN_DAILY_HEALTH_FIELDS.items():
            value = _as_number(_first_present(record, keys))
            if value is not None:
                health[metric_name] = (
                    round(float(value)) if metric_name in {"steps", "floors"} else value
                )
        if health:
            health["source"] = GARMIN_PERFORMANCE_SOURCE
    return health_by_date


def garmin_daily_health_metrics(
    snapshot: dict[str, Any], days: int, end_date: date, current_date: date
) -> dict[str, dict[str, Any]]:
    """Return daily Garmin health totals averaged over the requested window."""
    cutoff = end_date - timedelta(days=days - 1)
    values: dict[str, list[float]] = {key: [] for key in GARMIN_DAILY_HEALTH_FIELDS}
    for record_date, health in garmin_daily_health_by_date(snapshot).items():
        try:
            current = date.fromisoformat(record_date[:10])
        except ValueError:
            continue
        if not cutoff <= current <= end_date:
            continue
        for metric_name, _metric_values in values.items():
            number = _as_number(health.get(metric_name))
            if number is not None:
                _metric_values.append(float(number))
    units = {
        "steps": "Schritte/Tag",
        "floors": "Stockwerke/Tag",
        "calories": "kcal/Tag",
    }
    result = {}
    for metric_name, numbers in values.items():
        if not numbers:
            average = None
        elif metric_name in {"steps", "floors"}:
            average = round(sum(numbers) / len(numbers))
        else:
            average = round(sum(numbers) / len(numbers), 2)
        result[f"{metric_name}_7d"] = performance_freshness.garmin_metric_freshness(
            snapshot,
            "daily_stats",
            _metric(
                average,
                units[metric_name],
                GARMIN_PERFORMANCE_SOURCE,
                "Durchschnitt der letzten 7 Tage",
            ),
            current_date,
        )
    return result
