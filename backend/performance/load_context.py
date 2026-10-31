"""Stateless performance load context composition."""

from datetime import date, timedelta
from typing import Any

from backend.canonical.vocabulary import MetricKind
from backend.performance import load as performance_load
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.wellness_days import WellnessDay, latest, series

RAMP_RATE_SOURCE = "Intervals.icu CTL (berechnet)"


def performance_load_context(
    activities: list[Any],
    days: tuple[WellnessDay, ...],
    today: date,
    *,
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Any]:
    last_7 = performance_load.activity_rollup(activities, 7, today)
    previous_7 = performance_load.activity_rollup(
        activities, 7, today - timedelta(days=7)
    )
    last_30 = performance_load.activity_rollup(activities, 30, today)
    previous_30 = performance_load.activity_rollup(
        activities, 30, today - timedelta(days=30)
    )
    actual_atl = performance_load.actual_atl_series(
        series(days, MetricKind.ATL), activities, today
    )
    actual_atl_date = max(
        (row_date for row_date in actual_atl if row_date <= today), default=None
    )
    actual_atl_current = actual_atl.get(actual_atl_date) if actual_atl_date else None
    actual_atl_values = [
        value
        for row_date, value in actual_atl.items()
        if today - timedelta(days=6) <= row_date <= today
    ]
    actual_atl_average = (
        round(sum(actual_atl_values) / len(actual_atl_values), 2)
        if actual_atl_values
        else None
    )
    latest_day = latest(days)
    load = {
        "id": latest_day.day.isoformat() if latest_day else None,
        "ctl": canonical.ctl,
        "atl": canonical.atl,
        "tsb": None,
        "ramp_rate": None,
        "ramp_rate_source": None,
    }
    if canonical.wellness_day is not None:
        form_by_day = canonical.form_by_day or {}
        load["tsb"] = form_by_day.get(canonical.wellness_day)
        load["ramp_rate"] = canonical.ramp_rate
        if canonical.ramp_rate is not None:
            load["ramp_rate_source"] = RAMP_RATE_SOURCE
    return {
        "load": load,
        "last_7": last_7,
        "previous_7": previous_7,
        "last_30": last_30,
        "previous_30": previous_30,
        "actual_atl_current": actual_atl_current,
        "actual_atl_date": actual_atl_date,
        "actual_atl_average": actual_atl_average,
    }
