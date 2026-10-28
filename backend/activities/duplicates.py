"""Pure duplicate rules for provider activity rows and the duplicate-delete contract."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from typing import Any

from backend.activities.identity import activity_datetime, activity_kind
from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.providers.garmin_gear_fields import activity_start_local
from backend.providers.source_labels import SourceView, provider_label

_GARMIN_DUPLICATE_START_WINDOW = timedelta(minutes=30)
_DUPLICATE_DELETE_STALE_ERROR = (
    "Das Wahoo-/Garmin-Duplikat ist nicht mehr aktuell. "
    "Bitte die letzte Einheit erneut analysieren."
)

__all__ = [
    "deduplicate_api_records",
    "duplicate_delete_action",
    "filter_garmin_activities",
    "garmin_activity_duplicates_intervals",
    "intervals_cycling_activities_match",
    "validate_duplicate_delete",
]


def duplicate_delete_action(pair: dict[str, Any]) -> dict[str, Any]:
    """Describe the explicit confirmation required to delete the Garmin copy."""
    return {
        "action_type": "delete_duplicate_intervals_activity",
        "target_system": ProviderId.INTERVALS,
        "object_ids": {
            "keep_activity_id": pair["canonical_id"],
            "delete_activity_id": pair["duplicate_id"],
        },
        "diff": [
            {
                "type": "delete",
                "id": pair["duplicate_id"],
                "name": pair["duplicate_name"],
                "date": iso_date_prefix(str(pair.get("start_date_local") or "")),
                "source": provider_label(ProviderId.GARMIN, SourceView.DUPLICATE),
                "kept_source": provider_label(ProviderId.WAHOO, SourceView.DUPLICATE),
            }
        ],
        "payload": {
            "canonical_id": pair["canonical_id"],
            "duplicate_id": pair["duplicate_id"],
            "snapshot_synced_at": pair.get("snapshot_synced_at"),
        },
    }


def validate_duplicate_delete(payload: Any, current: Any) -> tuple[str, str]:
    """Fail closed unless the confirmation matches the current duplicate snapshot."""
    keys = ("canonical_id", "duplicate_id", "snapshot_synced_at")
    if (
        not isinstance(payload, dict)
        or not isinstance(current, dict)
        or not current
        or any(
            str(payload.get(key) or "") != str(current.get(key) or "") for key in keys
        )
    ):
        raise AppError(409, _DUPLICATE_DELETE_STALE_ERROR)
    return str(payload.get("canonical_id") or ""), str(
        payload.get("duplicate_id") or ""
    )


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


def deduplicate_api_records(records: list[Any]) -> list[Any]:
    """Merge date-window responses without duplicating identified rows."""
    result: list[Any] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            result.append(record)
            continue
        identifier = _first_present(record, ("id", "activityId", "external_id"))
        if identifier in (None, ""):
            result.append(record)
            continue
        key = str(identifier)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


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


def _window_bound(start: datetime, offset: timedelta) -> datetime:
    """Shift a start by the window, clamped at the datetime range limits."""
    try:
        return start + offset
    except OverflowError:
        if offset > timedelta(0):
            return datetime.max.replace(tzinfo=start.tzinfo)
        return datetime.min.replace(tzinfo=start.tzinfo)


def filter_garmin_activities(
    activities: Any, intervals_activities: Any
) -> tuple[list[dict[str, Any]], int]:
    garmin_list = (
        [item for item in activities if isinstance(item, dict)]
        if isinstance(activities, list)
        else []
    )
    intervals_list = (
        [item for item in intervals_activities if isinstance(item, dict)]
        if isinstance(intervals_activities, list)
        else []
    )
    # Only recordings that start within the match window can be duplicates, so
    # each Garmin activity is compared with that slice of the sorted starts.
    indexed = sorted(
        (start, index)
        for index, item in enumerate(intervals_list)
        if (start := _intervals_start(item)) is not None
    )
    starts = [start for start, _ in indexed]

    def duplicates_intervals(item: dict[str, Any]) -> bool:
        garmin_start = activity_datetime(activity_start_local(item))
        if garmin_start is None:
            return False
        low = bisect_left(
            starts, _window_bound(garmin_start, -_GARMIN_DUPLICATE_START_WINDOW)
        )
        high = bisect_right(
            starts, _window_bound(garmin_start, _GARMIN_DUPLICATE_START_WINDOW)
        )
        return any(
            _garmin_activity_matches(item, intervals_list[index])
            for _, index in indexed[low:high]
        )

    filtered = [item for item in garmin_list if not duplicates_intervals(item)]
    return filtered, len(garmin_list) - len(filtered)


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
