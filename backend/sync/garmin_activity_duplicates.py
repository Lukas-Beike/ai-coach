"""Garmin snapshot rows against Intervals.icu rows: the duplicate rules of sync.

Sync may read provider fields, so these rules match the raw rows of both
providers before a Garmin activity is stored."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from backend.activities.duplicates import deduplicate_api_records
from backend.activities.identity import activity_datetime, activity_kind
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.vocabulary import RecordingOrigin
from backend.providers.garmin_gear_fields import activity_start_local
from backend.providers.intervals_activity_fields import (
    intervals_activity_device_source,
    intervals_activity_recorded_by_wahoo,
)

_GARMIN_DUPLICATE_START_WINDOW = timedelta(minutes=30)

__all__ = [
    "deduplicated_rows",
    "garmin_activity_duplicates_intervals",
    "intervals_cycling_activities_match",
]


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _number(value: Any) -> float | int | None:
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _garmin_duplicate_measurements(
    garmin_activity: dict[str, Any], intervals_activity: dict[str, Any]
) -> tuple[int, int]:
    compared = 0
    matches = 0
    # Garmin ``duration`` is elapsed time and Intervals.icu ``moving_time`` is
    # moving time, so Garmin ``movingDuration`` is a second candidate. Without a
    # Garmin moving time (walks), Garmin ``duration`` may also agree with the
    # Intervals.icu ``elapsed_time``.
    garmin_durations = [
        number
        for number in (
            _number(
                garmin_activity.get("duration") or garmin_activity.get("movingTime")
            ),
            _number(garmin_activity.get("movingDuration")),
        )
        if number is not None
    ]
    moving_time = _number(intervals_activity.get("moving_time"))
    if garmin_durations and moving_time is not None:
        compared += 1
        if any(
            abs(duration - moving_time) <= max(120, moving_time * 0.10)
            for duration in garmin_durations
        ) or _elapsed_times_agree(garmin_activity, intervals_activity):
            matches += 1
    left = _number(garmin_activity.get("distance"))
    right = _number(intervals_activity.get("distance"))
    if left is not None and right is not None and left > 0 and right > 0:
        compared += 1
        if abs(left - right) <= max(500, right * 0.10):
            matches += 1
    return compared, matches


def _elapsed_times_agree(
    garmin_activity: dict[str, Any], intervals_activity: dict[str, Any]
) -> bool:
    elapsed = _number(garmin_activity.get("duration"))
    other = _number(intervals_activity.get("elapsed_time"))
    return (
        elapsed is not None
        and other is not None
        and abs(elapsed - other) <= max(120, other * 0.10)
    )


def _intervals_start(intervals_activity: dict[str, Any]) -> datetime | None:
    return activity_datetime(
        intervals_activity.get("start_date_local")
        or intervals_activity.get("start_date")
    )


def _garmin_activity_matches(
    garmin_activity: dict[str, Any], intervals_activity: dict[str, Any]
) -> bool:
    garmin_start = activity_datetime(activity_start_local(garmin_activity))
    intervals_start = _intervals_start(intervals_activity)
    if garmin_start is None or intervals_start is None:
        return False
    if abs(garmin_start - intervals_start) > _GARMIN_DUPLICATE_START_WINDOW:
        return False
    garmin_kind = activity_kind(garmin_activity)
    intervals_kind = activity_kind(intervals_activity)
    if (
        garmin_kind != intervals_kind
        and garmin_kind != "other"
        and intervals_kind != "other"
    ):
        return False
    compared, matches = _garmin_duplicate_measurements(
        garmin_activity, intervals_activity
    )
    return bool(compared and matches == compared)


def garmin_activity_duplicates_intervals(
    garmin_activity: Any, intervals_activities: list[dict[str, Any]]
) -> bool:
    """Treat the Intervals/Wahoo recording as canonical when Garmin is a near duplicate."""
    if not isinstance(garmin_activity, dict):
        return False
    return any(
        _garmin_activity_matches(garmin_activity, item)
        for item in intervals_activities
        if isinstance(item, dict)
    )


def intervals_cycling_activities_match(left: Any, right: Any) -> bool:
    """Conservatively match duplicate ride recordings by start, time and distance."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if activity_kind(left) != "cycling" or activity_kind(right) != "cycling":
        return False
    left_start = activity_datetime(
        left.get("start_date_local") or left.get("start_date")
    )
    right_start = activity_datetime(
        right.get("start_date_local") or right.get("start_date")
    )
    left_duration = _number(_first_present(left, ("moving_time", "elapsed_time")))
    right_duration = _number(_first_present(right, ("moving_time", "elapsed_time")))
    left_distance = _number(left.get("distance"))
    right_distance = _number(right.get("distance"))
    if (
        left_start is None
        or right_start is None
        or left_duration is None
        or right_duration is None
        or left_distance is None
        or right_distance is None
    ):
        return False
    if (
        float(left_duration) <= 0
        or float(right_duration) <= 0
        or float(left_distance) <= 0
        or float(right_distance) <= 0
    ):
        return False
    return (
        abs((left_start - right_start).total_seconds()) <= 30 * 60
        and abs(float(left_duration) - float(right_duration))
        <= max(120, max(float(left_duration), float(right_duration)) * 0.10)
        and abs(float(left_distance) - float(right_distance))
        <= max(500, max(float(left_distance), float(right_distance)) * 0.10)
    )


def deduplicated_rows(rows: Sequence[Any]) -> tuple[list[dict[str, Any]], int]:
    """Drop duplicate raw Intervals.icu rows and Garmin copies of a Wahoo ride.

    Raw-row readers that are not on activity summaries yet (equipment) use it;
    summaries are already one per session.

    Returns the kept rows and how many rows were dropped.
    """
    unique = [
        row for row in deduplicate_api_records(list(rows)) if isinstance(row, dict)
    ]
    wahoo = [row for row in unique if intervals_activity_recorded_by_wahoo(row)]
    indexed = sorted(
        (started, index)
        for index, row in enumerate(wahoo)
        if (
            started := activity_datetime(
                row.get("start_date_local") or row.get("start_date")
            )
        )
        is not None
    )
    starts = [started for started, _ in indexed]
    window = timedelta(minutes=30)

    def matches_wahoo(row: dict[str, Any]) -> bool:
        started = activity_datetime(
            row.get("start_date_local") or row.get("start_date")
        )
        if started is None:
            return False
        minimum = datetime.min.replace(tzinfo=started.tzinfo)
        maximum = datetime.max.replace(tzinfo=started.tzinfo)
        low = bisect_left(
            starts,
            started - window if started >= minimum + window else minimum,
        )
        high = bisect_right(
            starts,
            started + window if started <= maximum - window else maximum,
        )
        return any(
            intervals_cycling_activities_match(wahoo[index], row)
            for _, index in indexed[low:high]
        )

    kept = [
        row
        for row in unique
        if not (
            intervals_activity_device_source(row) == RecordingOrigin.GARMIN
            and matches_wahoo(row)
        )
    ]
    return kept, len(unique) - len(kept)
