"""Match planned workout events to completed activity records."""

from __future__ import annotations

import math
from typing import Any

from backend.activities.identity import activity_datetime as _activity_datetime
from backend.activities.identity import activity_kind as _activity_kind


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


def is_planned_workout_event(event: Any) -> bool:
    """Return whether a calendar record represents a workout to execute."""
    if not isinstance(event, dict):
        return False
    category = str(event.get("category") or "").strip().upper()
    if category:
        return category == "WORKOUT"
    # Provider records may omit category. Only infer a workout when the record
    # has a duration, so races and calendar notes are not counted as missed
    # training.
    return (
        _as_number(_first_present(event, ("moving_time", "elapsed_time"))) is not None
    )


def record_date(value: Any) -> str:
    parsed = _activity_datetime(value)
    return parsed.date().isoformat() if parsed else str(value or "")[:10]


def _planned_workout_rows(planned: list[Any]) -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, event)
        for index, event in enumerate(planned)
        if is_planned_workout_event(event)
    ]


def _activities_by_paired_event_id(
    activity_rows: list[dict[str, Any]],
) -> dict[str, list[int]]:
    by_paired_id: dict[str, list[int]] = {}
    for activity_index, activity in enumerate(activity_rows):
        paired_id = _first_present(activity, ("paired_event_id", "pairedEventId"))
        if paired_id not in (None, ""):
            by_paired_id.setdefault(str(paired_id), []).append(activity_index)
    return by_paired_id


def _paired_activity_match(
    event: dict[str, Any],
    activity_rows: list[dict[str, Any]],
    by_paired_id: dict[str, list[int]],
    unused: set[int],
) -> int | None:
    event_id = _first_present(event, ("id", "event_id"))
    if event_id in (None, ""):
        return None
    candidates = [
        index for index in by_paired_id.get(str(event_id), []) if index in unused
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda index: str(activity_rows[index].get("start_date_local") or ""),
    )


def _unpaired_activity_match(
    event: dict[str, Any], activity_rows: list[dict[str, Any]], unused: set[int]
) -> int | None:
    event_date = record_date(
        _first_present(event, ("start_date_local", "date", "start"))
    )
    event_kind = _activity_kind(event)
    if event_kind == "other":
        return None
    event_start = _activity_datetime(
        _first_present(event, ("start_date_local", "date", "start"))
    )
    candidates: list[tuple[float, int]] = []
    for activity_index in unused:
        activity = activity_rows[activity_index]
        if _first_present(activity, ("paired_event_id", "pairedEventId")) not in (
            None,
            "",
        ):
            continue
        if (
            record_date(
                _first_present(activity, ("start_date_local", "start_date", "start"))
            )
            != event_date
        ):
            continue
        if _activity_kind(activity) != event_kind:
            continue
        activity_start = _activity_datetime(
            _first_present(activity, ("start_date_local", "start_date", "start"))
        )
        distance = (
            abs((activity_start - event_start).total_seconds())
            if activity_start and event_start
            else 0
        )
        candidates.append((distance, activity_index))
    return min(candidates)[1] if candidates else None


def match_planned_workouts(
    planned: list[Any], activities: list[Any]
) -> dict[int, dict[str, Any]]:
    """Match completed activities to planned workouts without reusing one activity."""
    activity_rows = [item for item in activities if isinstance(item, dict)]
    unused = set(range(len(activity_rows)))
    matches: dict[int, dict[str, Any]] = {}
    workout_rows = _planned_workout_rows(planned)
    by_paired_id = _activities_by_paired_event_id(activity_rows)

    # paired_event_id is the reliable Intervals.icu association.
    for event_index, event in workout_rows:
        selected_index = _paired_activity_match(
            event, activity_rows, by_paired_id, unused
        )
        if selected_index is not None:
            matches[event_index] = activity_rows[selected_index]
            unused.remove(selected_index)

    # Handle manually logged workouts conservatively, without stealing an
    # activity that is explicitly paired with another event.
    for event_index, event in workout_rows:
        if event_index in matches:
            continue
        selected_index = _unpaired_activity_match(event, activity_rows, unused)
        if selected_index is not None:
            matches[event_index] = activity_rows[selected_index]
            unused.remove(selected_index)
    return matches
