"""Pure duplicate detection for provider activity snapshots."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from backend.activities.identity import (
    activity_datetime,
    activity_kind,
    intervals_activity_device_source,
)
from backend.errors import AppError

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
    "latest_wahoo_garmin_duplicate",
    "remove_activity_from_snapshot",
    "validate_duplicate_delete",
]


def duplicate_delete_action(pair: dict[str, Any]) -> dict[str, Any]:
    """Describe the explicit confirmation required to delete the Garmin copy."""
    return {
        "action_type": "delete_duplicate_intervals_activity",
        "target_system": "intervals",
        "object_ids": {
            "keep_activity_id": pair["canonical_id"],
            "delete_activity_id": pair["duplicate_id"],
        },
        "diff": [
            {
                "type": "delete",
                "id": pair["duplicate_id"],
                "name": pair["duplicate_name"],
                "date": str(pair.get("start_date_local") or "")[:10],
                "source": "Garmin",
                "kept_source": "Wahoo",
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


def remove_activity_from_snapshot(
    snapshot: Any, activity_id: str, *, synced_at: Any
) -> dict[str, Any] | None:
    """Return a copied snapshot with only exact matching activity IDs removed."""
    if not isinstance(snapshot, dict):
        return None

    def retained(activities: Any) -> Any:
        if not isinstance(activities, list):
            return []
        return [
            activity
            for activity in activities
            if not isinstance(activity, dict)
            or str(_first_present(activity, ("id", "activityId")) or "") != activity_id
        ]

    updated = dict(snapshot)
    updated["recent_activities"] = retained(snapshot.get("recent_activities"))
    raw = snapshot.get("raw_provider_data")
    if isinstance(raw, dict):
        updated["raw_provider_data"] = {
            **raw,
            "activities": retained(raw.get("activities")),
        }
    updated["synced_at"] = synced_at
    return updated


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
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
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
    pairs = (
        (
            _number(
                garmin_activity.get("duration") or garmin_activity.get("movingTime")
            ),
            _number(intervals_activity.get("moving_time")),
            120,
        ),
        (
            _number(garmin_activity.get("distance")),
            _number(intervals_activity.get("distance")),
            500,
        ),
    )
    for index, (left, right, minimum) in enumerate(pairs):
        if left is None or right is None or index == 1 and (left <= 0 or right <= 0):
            continue
        compared += 1
        if abs(left - right) <= max(minimum, right * 0.10):
            matches += 1
    return compared, matches


def _garmin_activity_matches(
    garmin_activity: dict[str, Any], intervals_activity: dict[str, Any]
) -> bool:
    garmin_start = activity_datetime(
        garmin_activity.get("startTimeLocal") or garmin_activity.get("start_time_local")
    )
    intervals_start = activity_datetime(
        intervals_activity.get("start_date_local")
        or intervals_activity.get("start_date")
    )
    if garmin_start is None or intervals_start is None:
        return False
    if abs((garmin_start - intervals_start).total_seconds()) > 30 * 60:
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
    filtered = [
        item
        for item in garmin_list
        if not garmin_activity_duplicates_intervals(item, intervals_list)
    ]
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
    if None in (
        left_start,
        right_start,
        left_duration,
        right_duration,
        left_distance,
        right_distance,
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


def _latest_activity_id(activities: list[dict[str, Any]]) -> str | None:
    dated = [
        (started, item)
        for item in activities
        if (
            started := activity_datetime(
                item.get("start_date_local") or item.get("start_date")
            )
        )
        is not None
    ]
    if not dated:
        return None
    latest = max(dated, key=lambda item: item[0])[1]
    value = str(_first_present(latest, ("id", "activityId")) or "").strip()
    return value or None


def _wahoo_garmin_pairs(
    activities: list[dict[str, Any]], latest_id: str
) -> list[tuple[datetime, dict[str, Any], dict[str, Any]]]:
    candidates = [item for item in activities if activity_kind(item) == "cycling"]
    candidates.sort(
        key=lambda item: (
            activity_datetime(item.get("start_date_local") or item.get("start_date"))
            or datetime.min  # noqa: DTZ901 - identity timestamps are intentionally naive
        ),
        reverse=True,
    )
    wahoo = [
        item for item in candidates if intervals_activity_device_source(item) == "wahoo"
    ]
    garmin = [
        item
        for item in candidates
        if intervals_activity_device_source(item) == "garmin"
    ]
    pairs: list[tuple[datetime, dict[str, Any], dict[str, Any]]] = []
    for canonical in wahoo:
        for duplicate in garmin:
            if not intervals_cycling_activities_match(canonical, duplicate):
                continue
            started = activity_datetime(
                canonical.get("start_date_local") or canonical.get("start_date")
            )
            canonical_id = str(
                _first_present(canonical, ("id", "activityId")) or ""
            ).strip()
            duplicate_id = str(
                _first_present(duplicate, ("id", "activityId")) or ""
            ).strip()
            if started is not None and latest_id in {canonical_id, duplicate_id}:
                pairs.append((started, canonical, duplicate))
    return pairs


def _wahoo_garmin_duplicate_view(
    snapshot: dict[str, Any], pair: tuple[datetime, dict[str, Any], dict[str, Any]]
) -> dict[str, Any] | None:
    _started, canonical, duplicate = pair
    canonical_id = str(_first_present(canonical, ("id", "activityId")) or "").strip()
    duplicate_id = str(_first_present(duplicate, ("id", "activityId")) or "").strip()
    if not canonical_id or not duplicate_id or canonical_id == duplicate_id:
        return None
    return {
        "canonical_id": canonical_id,
        "canonical_name": str(canonical.get("name") or "Wahoo-Radeinheit")[:200],
        "duplicate_id": duplicate_id,
        "duplicate_name": str(duplicate.get("name") or "Garmin-Radeinheit")[:200],
        "start_date_local": str(
            canonical.get("start_date_local") or canonical.get("start_date") or ""
        )[:40],
        "moving_time": canonical.get("moving_time") or canonical.get("elapsed_time"),
        "distance": canonical.get("distance"),
        "snapshot_synced_at": snapshot.get("synced_at"),
    }


def latest_wahoo_garmin_duplicate(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest exact-source ride pair, always keeping Wahoo canonical."""
    if not isinstance(snapshot, dict):
        return None
    raw = snapshot.get("raw_provider_data")
    raw = raw if isinstance(raw, dict) else {}
    activities = (
        raw.get("activities")
        if isinstance(raw.get("activities"), list)
        else snapshot.get("recent_activities", [])
    )
    all_activities = [item for item in activities if isinstance(item, dict)]
    latest_id = _latest_activity_id(all_activities)
    if not latest_id:
        return None
    pairs = _wahoo_garmin_pairs(all_activities, latest_id)
    if not pairs:
        return None
    return _wahoo_garmin_duplicate_view(snapshot, max(pairs, key=lambda item: item[0]))
