"""Thirty-day cycling eFTP aggregation."""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.performance import activity_validation
from backend.providers import intervals_performance_fields as intervals_perf_fields
from backend.providers.garmin_fields import first_present as _first_present


def _activity_eftp_value(activity: Any, cutoff: date, anchor: date) -> float | None:
    if not isinstance(activity, dict):
        return None
    try:
        activity_date = date.fromisoformat(
            iso_date_prefix(str(activity.get("start_date_local") or ""))
        )
    except TypeError, ValueError:
        return None
    if not cutoff <= activity_date <= anchor:
        return None
    raw_type = str(
        _first_present(
            activity, ("type", "sport", "sport_type", "activity_type", "name")
        )
        or ""
    ).casefold()
    if not any(term in raw_type for term in ("ride", "rad", "bike", "cycling")):
        return None
    value = activity_validation.bounded_performance_metric(
        "cycling_eftp_watts",
        _first_present(activity, intervals_perf_fields.ESTIMATED_FTP_ALIASES),
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
    activities: list[Any],
    start: date,
    end: date,
) -> dict[str, float]:
    """Prefer the canonical wellness-day eFTP, else the day's latest cycling activity.

    ``eftp_by_day`` holds the ride eFTP observations of Intervals.icu wellness days.
    Each day contributes at most one value, so a same-day wellness and activity
    eFTP are not both counted.
    """
    observations: dict[str, float] = {}
    activity_rows = [row for row in activities if isinstance(row, dict)]
    for activity in sorted(
        activity_rows, key=lambda row: str(row.get("start_date_local") or "")
    ):
        value = _activity_eftp_value(activity, start, end)
        if value is not None:
            observations[iso_date_prefix(str(activity["start_date_local"]))] = value
    for day, raw in (eftp_by_day or {}).items():
        if not start <= day <= end:
            continue
        value = activity_validation.bounded_performance_metric(
            "cycling_eftp_watts", raw
        )
        if value is not None:
            observations[day.isoformat()] = float(value)
    return observations
