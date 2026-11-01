"""Thirty-day cycling eFTP aggregation."""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import summary_local_date
from backend.performance import activity_validation


def _activity_eftp_value(activity: Any, cutoff: date, anchor: date) -> float | None:
    if not isinstance(activity, dict) or activity.get("sport") != "ride":
        return None
    try:
        activity_date = date.fromisoformat(summary_local_date(activity))
    except ValueError:
        return None
    if not cutoff <= activity_date <= anchor:
        return None
    value = activity_validation.bounded_performance_metric(
        "cycling_eftp_watts", activity.get("eftp_w")
    )
    return float(value) if value is not None else None


def eftp_30_day_average(
    eftp_by_day: Mapping[date, float] | None, activities: list[Any], end_date: date
) -> float | None:
    cutoff = end_date - timedelta(days=29)
    values = list(eftp_daily_values(eftp_by_day, activities, cutoff, end_date).values())
    return round(sum(values) / len(values), 1) if values else None


def eftp_daily_values(
    eftp_by_day: Mapping[date, float] | None,
    activities: Sequence[Any],
    start: date,
    end: date,
) -> dict[str, float]:
    """Prefer the canonical wellness-day eFTP, else the day's latest ride summary.

    ``eftp_by_day`` holds the ride eFTP observations of Intervals.icu wellness days.
    Each day contributes at most one value, so a same-day wellness and activity
    eFTP are not both counted.
    """
    observations: dict[str, float] = {}
    summaries = [row for row in activities if isinstance(row, dict)]
    for activity in sorted(
        summaries, key=lambda row: str(row.get("started_at_local") or "")
    ):
        value = _activity_eftp_value(activity, start, end)
        if value is not None:
            observations[summary_local_date(activity)] = value
    for day, raw in (eftp_by_day or {}).items():
        if not start <= day <= end:
            continue
        value = activity_validation.bounded_performance_metric(
            "cycling_eftp_watts", raw
        )
        if value is not None:
            observations[day.isoformat()] = float(value)
    return observations
