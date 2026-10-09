"""Match planned workout events to completed activity records."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from backend.activities.identity import activity_datetime as _activity_datetime
from backend.activities.identity import activity_kind as _activity_kind
from backend.athlete.local_date import iso_date_prefix

# Planned units without a start time are stored as a bare date or as the
# midnight placeholder used by the planning and calendar modules.
_DATE_ONLY_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]00:00(?::00(?:\.0+)?)?)?", re.ASCII
)
_PLANNED_START_KEYS = ("start_date_local", "date", "start")
_ACTIVITY_START_KEYS = ("start_date_local", "start_date", "start")
_DURATION_KEYS = ("moving_time", "elapsed_time")
_LOAD_KEYS = ("icu_training_load", "training_load", "tss")


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
    except TypeError, ValueError:
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
    return parsed.date().isoformat() if parsed else iso_date_prefix(str(value or ""))


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


def _is_date_only(value: Any) -> bool:
    return _DATE_ONLY_PATTERN.fullmatch(str(value or "").strip()) is not None


def _non_negative_number(record: Any, keys: tuple[str, ...]) -> float | int | None:
    number = _as_number(_first_present(record, keys))
    return number if number is not None and number >= 0 else None


def _unpaired_candidates(
    event_date: str,
    event_kind: str,
    activity_rows: list[dict[str, Any]],
    unused: set[int],
) -> list[int]:
    candidates: list[int] = []
    for activity_index in unused:
        activity = activity_rows[activity_index]
        if _first_present(activity, ("paired_event_id", "pairedEventId")) not in (
            None,
            "",
        ):
            continue
        if record_date(_first_present(activity, _ACTIVITY_START_KEYS)) != event_date:
            continue
        if _activity_kind(activity) != event_kind:
            continue
        candidates.append(activity_index)
    return candidates


def _planned_duration_seconds(event: dict[str, Any]) -> float | int | None:
    # Local library units carry duration_minutes; provider events carry seconds.
    seconds = _non_negative_number(event, _DURATION_KEYS)
    if seconds is not None:
        return seconds
    minutes = _non_negative_number(event, ("duration_minutes",))
    return minutes * 60 if minutes is not None else None


def _date_only_fit_key(
    event: dict[str, Any], activity: dict[str, Any], activity_index: int
) -> tuple[float, float, tuple[int, datetime | None], int]:
    """Rank a same-day activity for a planned unit without a start time.

    Sport family is already enforced by the caller. Smaller keys fit better:
    relative duration gap, then absolute load gap, then earliest start, then
    the original index as a deterministic tie-break. Missing data ranks last.
    """
    planned_duration = _planned_duration_seconds(event)
    actual_duration = _non_negative_number(activity, _DURATION_KEYS)
    duration_gap = (
        abs(actual_duration - planned_duration) / planned_duration
        if planned_duration and actual_duration is not None
        else math.inf
    )
    planned_load = _non_negative_number(event, _LOAD_KEYS)
    actual_load = _non_negative_number(activity, _LOAD_KEYS)
    load_gap = (
        abs(actual_load - planned_load)
        if planned_load is not None and actual_load is not None
        else math.inf
    )
    start = _activity_datetime(_first_present(activity, _ACTIVITY_START_KEYS))
    # Known starts sort before unknown ones; (1, None) ties fall to the index.
    start_key = (0, start) if start is not None else (1, None)
    return (duration_gap, load_gap, start_key, activity_index)


def _unpaired_activity_match(
    event: dict[str, Any], activity_rows: list[dict[str, Any]], unused: set[int]
) -> int | None:
    event_value = _first_present(event, _PLANNED_START_KEYS)
    event_date = record_date(event_value)
    event_kind = _activity_kind(event)
    if event_kind == "other":
        return None
    candidates = _unpaired_candidates(event_date, event_kind, activity_rows, unused)
    if not candidates:
        return None
    if _is_date_only(event_value):
        return min(
            candidates,
            key=lambda index: _date_only_fit_key(event, activity_rows[index], index),
        )
    event_start = _activity_datetime(event_value)
    ranked: list[tuple[float, int]] = []
    for activity_index in candidates:
        activity_start = _activity_datetime(
            _first_present(activity_rows[activity_index], _ACTIVITY_START_KEYS)
        )
        distance = (
            abs((activity_start - event_start).total_seconds())
            if activity_start and event_start
            else 0
        )
        ranked.append((distance, activity_index))
    return min(ranked)[1]


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
