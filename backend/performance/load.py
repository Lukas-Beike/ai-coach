"""Training-load rollups.

A summary's ``training_load`` is the local TSS-scale load of card M6, stored by
``backend.sync.local_load`` and set on the summaries by ``with_local_loads``;
provider loads (for example Garmin's EPOC-based value) are never summed. A
session without a local load, for lack of the thresholds, heart rate or power
the method needs, is left out of the sum and counted as
``load_missing_sessions``. Its session-RPE load, when rated, is reported beside
the sum in AU (``load_missing_session_rpe_au``, with the labels of its RPE
sources in ``load_missing_session_rpe_source``) and never added to it. Hours of
e-bike sessions count in the time-based volume and are also reported on their
own as ``electric_assist_hours``.
"""

import math
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import summary_local_date
from backend.canonical.activity_summary import (
    stored_activity_key,
    summary_is_electric,
    summary_leading_duration_s,
)
from backend.performance.session_rpe_load import session_load

type SessionFeedback = Mapping[str, Mapping[str, Any]]


def _activity_rollup_date(activity: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(summary_local_date(activity))
    except ValueError:
        return None


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
) -> dict[str, Any]:
    """The rollup keys of sessions without a TSS-scale load, empty without any.

    Their known session-RPE load in AU keeps the labels of the RPE sources it
    came from (athlete feedback, or the provider RPE as a fallback).
    """
    missing = [row for row in window if _tss_load(row) is None]
    if not missing:
        return {}
    loads = [
        session_load(row, session_feedback.get(stored_activity_key(row) or ""))
        for row in missing
    ]
    keys: dict[str, Any] = {"load_missing_sessions": len(missing)}
    rated = [(entry, value) for entry, value in loads if value is not None]
    if rated:
        keys["load_missing_session_rpe_au"] = round(
            math.fsum(value for _entry, value in rated), 1
        )
        keys["load_missing_session_rpe_source"] = ", ".join(
            sorted({str(entry["rpe_source_label"]) for entry, _value in rated})
        )
    return keys


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
    moving_seconds = sum(_rollup_seconds(activity) for activity in window)
    training_load = sum(_tss_load(activity) or 0.0 for activity in window)
    rollup: dict[str, Any] = {
        "days": days,
        "sessions": len(window),
        "duration_hours": round(moving_seconds / 3600, 1),
        "training_load": round(training_load, 1),
    }
    electric = [activity for activity in window if summary_is_electric(activity)]
    if electric:
        rollup["electric_assist_hours"] = round(
            sum(_rollup_seconds(activity) for activity in electric) / 3600, 1
        )
    return rollup | _missing_load(window, session_feedback or {})


def _rollup_seconds(activity: dict[str, Any]) -> float:
    # A strength session counts with its total time, like its compact row (#2317).
    return summary_leading_duration_s(activity) or 0.0
