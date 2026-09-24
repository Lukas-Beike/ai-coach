"""Stateless performance load context composition."""

from datetime import date, timedelta
from typing import Any

from backend.performance import load as performance_load
from backend.performance import wellness as performance_wellness


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def performance_load_context(
    activities: list[Any],
    wellness_rows: list[dict[str, Any]],
    latest_wellness: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    last_7 = performance_load.activity_rollup(activities, 7, today)
    previous_7 = performance_load.activity_rollup(
        activities, 7, today - timedelta(days=7)
    )
    last_30 = performance_load.activity_rollup(activities, 30, today)
    previous_30 = performance_load.activity_rollup(
        activities, 30, today - timedelta(days=30)
    )
    actual_atl = performance_load.actual_atl_series(wellness_rows, activities, today)
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
    return {
        "load": {
            "id": latest_wellness.get("id"),
            "ctl": _first_present(latest_wellness, ("ctl", "ctLoad")),
            "atl": _first_present(latest_wellness, ("atl", "atlLoad")),
            "tsb": performance_wellness.wellness_form_value(latest_wellness),
            "rampRate": _first_present(latest_wellness, ("rampRate",)),
        },
        "last_7": last_7,
        "previous_7": previous_7,
        "last_30": last_30,
        "previous_30": previous_30,
        "actual_atl_current": actual_atl_current,
        "actual_atl_date": actual_atl_date,
        "actual_atl_average": actual_atl_average,
    }
