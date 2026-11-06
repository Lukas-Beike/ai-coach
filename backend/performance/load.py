"""Training-load rollups and reconstructed actual ATL series.

Loads are summed on the TSS scale only (Intervals.icu training load or TSS). A
session without such a load, such as a Garmin-only session whose Garmin load is
EPOC-based, is left out of the sum and counted as ``load_missing_sessions``. Its
session-RPE load, when rated, is reported beside the sum in AU
(``load_missing_session_rpe_au``) and never added to it.
"""

import math
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import summary_local_date
from backend.canonical.activity_summary import stored_activity_key
from backend.canonical.decimal_text import provider_number as _as_number
from backend.performance.session_rpe_load import session_load

type SessionFeedback = Mapping[str, Mapping[str, Any]]


def _activity_rollup_date(activity: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(summary_local_date(activity))
    except ValueError:
        return None


def _activity_rollup_number(activity: dict[str, Any], key: str) -> float:
    try:
        return float(activity.get(key) or 0)
    except TypeError, ValueError:
        return 0.0


def _tss_load(activity: Mapping[str, Any]) -> float | None:
    """The session's TSS-scale load as the rollup sums it, or None without one."""
    try:
        number = float(activity.get("training_load"))  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def _activities_in(activities: list[Any], cutoff: date, anchor: date) -> list[dict]:
    return [
        activity
        for activity in activities
        if isinstance(activity, dict)
        and (activity_date := _activity_rollup_date(activity)) is not None
        and cutoff <= activity_date <= anchor
    ]


def _missing_load(
    window: list[dict], session_feedback: SessionFeedback
) -> tuple[int, float | None]:
    """Sessions without a TSS-scale load, and their known session-RPE load in AU."""
    missing = [row for row in window if _tss_load(row) is None]
    rated = [
        value
        for row in missing
        if (
            value := session_load(
                row, session_feedback.get(stored_activity_key(row) or "")
            )[1]
        )
        is not None
    ]
    return len(missing), (sum(rated) if rated else None)


def activity_rollup(
    activities: list[Any],
    days: int,
    end_date: date,
    *,
    session_feedback: SessionFeedback | None = None,
) -> dict[str, Any]:
    """Sessions, hours and TSS-scale load of the ``days`` ending on ``end_date``.

    ``session_feedback`` maps a summary's stored key to its local feedback, for
    the session-RPE load of sessions left out of the load sum.
    """
    window = _activities_in(activities, end_date - timedelta(days=days - 1), end_date)
    moving_seconds = sum(
        _activity_rollup_number(activity, "moving_duration_s")
        or _activity_rollup_number(activity, "elapsed_duration_s")
        for activity in window
    )
    training_load = sum(_tss_load(activity) or 0.0 for activity in window)
    rollup: dict[str, Any] = {
        "days": days,
        "sessions": len(window),
        "duration_hours": round(moving_seconds / 3600, 1),
        "training_load": round(training_load, 1),
    }
    missing, rpe_au = _missing_load(window, session_feedback or {})
    if missing:
        rollup["load_missing_sessions"] = missing
    if rpe_au is not None:
        rollup["load_missing_session_rpe_au"] = round(rpe_au, 1)
    return rollup


def _activity_load_by_date(activities: list[Any], anchor: date) -> dict[date, float]:
    load_by_date: dict[date, float] = {}
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        activity_date = _activity_rollup_date(activity)
        if activity_date is None or activity_date > anchor:
            continue
        load = _as_number(activity.get("training_load"))
        if load is not None:
            load_by_date[activity_date] = load_by_date.get(activity_date, 0.0) + float(
                load
            )
    return load_by_date


def _atl_series_from_rows(
    dated_wellness: list[tuple[date, float]],
    load_by_date: dict[date, float],
) -> dict[date, float]:
    first_date, first_atl = dated_wellness[0]
    retention = math.exp(-1.0 / 7.0)
    decay = 1.0 - retention
    previous = (first_atl - load_by_date.get(first_date, 0.0) * decay) / retention
    series = {
        first_date: round(
            previous * retention + load_by_date.get(first_date, 0.0) * decay, 2
        )
    }
    previous = series[first_date]
    cursor = first_date
    for row_date, _row in dated_wellness[1:]:
        while cursor + timedelta(days=1) < row_date:
            cursor += timedelta(days=1)
            previous = previous * retention + load_by_date.get(cursor, 0.0) * decay
        previous = previous * retention + load_by_date.get(row_date, 0.0) * decay
        series[row_date] = round(previous, 2)
        cursor = row_date
    return series


def actual_atl_series(
    atl_by_day: dict[date, float],
    activities: list[Any],
    end_date: date,
) -> dict[date, float]:
    """Reconstruct ATL from completed activity load only (default 7-day ATL decay)."""
    dated_wellness = sorted(atl_by_day.items())
    if not dated_wellness:
        return {}
    return _atl_series_from_rows(
        dated_wellness, _activity_load_by_date(activities, end_date)
    )
