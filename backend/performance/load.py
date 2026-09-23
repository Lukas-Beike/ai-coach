"""Training-load rollups and reconstructed actual ATL series."""

import math
from datetime import date, timedelta
from typing import Any


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


def _activity_rollup_date(activity: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(activity.get("start_date_local") or "")[:10])
    except ValueError:
        return None


def _activity_rollup_number(activity: dict[str, Any], key: str) -> float:
    try:
        return float(activity.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _activity_rollup_totals(
    activities: list[Any],
    cutoff: date,
    anchor: date,
) -> tuple[int, float, float]:
    count = 0
    moving_seconds = 0.0
    training_load = 0.0
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        activity_date = _activity_rollup_date(activity)
        if activity_date is None or not cutoff <= activity_date <= anchor:
            continue
        count += 1
        moving_seconds += _activity_rollup_number(activity, "moving_time")
        training_load += _activity_rollup_number(activity, "icu_training_load")
    return count, moving_seconds, training_load


def activity_rollup(activities: list[Any], days: int, end_date: date) -> dict[str, Any]:
    cutoff = end_date - timedelta(days=days - 1)
    count, moving_seconds, training_load = _activity_rollup_totals(
        activities, cutoff, end_date
    )
    return {
        "days": days,
        "sessions": count,
        "duration_hours": round(moving_seconds / 3600, 1),
        "training_load": round(training_load, 1),
    }


def _atl_wellness_rows(
    wellness_rows: list[dict[str, Any]],
) -> list[tuple[date, dict[str, Any]]]:
    dated_rows: list[tuple[date, dict[str, Any]]] = []
    for row in wellness_rows:
        try:
            row_date = date.fromisoformat(
                str(row.get("id") or row.get("date") or "")[:10]
            )
        except (AttributeError, TypeError, ValueError):
            continue
        if (
            isinstance(row, dict)
            and _as_number(_first_present(row, ("atl",))) is not None
        ):
            dated_rows.append((row_date, row))
    dated_rows.sort(key=lambda item: item[0])
    return dated_rows


def _activity_load_by_date(activities: list[Any], anchor: date) -> dict[date, float]:
    load_by_date: dict[date, float] = {}
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        try:
            activity_date = date.fromisoformat(
                str(activity.get("start_date_local") or "")[:10]
            )
        except (TypeError, ValueError):
            continue
        if activity_date > anchor:
            continue
        load = _as_number(_first_present(activity, ("icu_training_load",)))
        if load is not None:
            load_by_date[activity_date] = load_by_date.get(activity_date, 0.0) + float(
                load
            )
    return load_by_date


def _atl_series_from_rows(
    dated_wellness: list[tuple[date, dict[str, Any]]],
    load_by_date: dict[date, float],
) -> dict[date, float]:
    first_date, first_row = dated_wellness[0]
    retention = math.exp(-1.0 / 7.0)
    decay = 1.0 - retention
    previous = (
        float(_as_number(_first_present(first_row, ("atl",))) or 0)
        - load_by_date.get(first_date, 0.0) * decay
    ) / retention
    series = {
        first_date: round(
            previous * retention + load_by_date.get(first_date, 0.0) * decay, 2
        )
    }
    previous = series[first_date]
    cursor = first_date
    for row_date, _row in dated_wellness[1:]:
        while cursor + timedelta(days=1) < row_date:
            previous *= retention
            cursor += timedelta(days=1)
        previous = previous * retention + load_by_date.get(row_date, 0.0) * decay
        series[row_date] = round(previous, 2)
        cursor = row_date
    return series


def actual_atl_series(
    wellness_rows: list[dict[str, Any]],
    activities: list[Any],
    end_date: date,
) -> dict[date, float]:
    """Reconstruct ATL from completed activity load only (default 7-day ATL decay)."""
    dated_wellness = _atl_wellness_rows(wellness_rows)
    if not dated_wellness:
        return {}
    return _atl_series_from_rows(
        dated_wellness, _activity_load_by_date(activities, end_date)
    )
