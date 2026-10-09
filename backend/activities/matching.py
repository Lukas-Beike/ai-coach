"""Match planned workout events to completed activity records."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any

from backend.activities.identity import activity_datetime as _activity_datetime
from backend.activities.identity import activity_kind as _activity_kind
from backend.athlete.local_date import iso_date_prefix

# Units without a planned time are stored as a bare date or at local midnight.
_DATE_ONLY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]00:00(?::00(?:\.0+)?)?)?")
_UNIT_START_FIELDS = ("start_date_local", "date", "start")
_ACTIVITY_START_FIELDS = ("start_date_local", "start_date", "start")
_DURATION_FIELDS = ("moving_time", "elapsed_time")
_LOAD_FIELDS = ("icu_training_load", "training_load", "tss")


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


def _number_field(record: Any, keys: tuple[str, ...]) -> float | None:
    number = _as_number(_first_present(record, keys))
    return None if number is None else float(number)


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


def _has_start_time(value: Any) -> bool:
    """Return whether a unit start carries a planned time rather than only a date."""
    text = str(value or "").strip()
    return bool(text) and not _DATE_ONLY_PATTERN.fullmatch(text)


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


def _is_unpaired(activity: dict[str, Any]) -> bool:
    return _first_present(activity, ("paired_event_id", "pairedEventId")) in (None, "")


def _same_day_candidates(
    event: dict[str, Any], activity_rows: list[dict[str, Any]], unused: set[int]
) -> list[int]:
    """Return unused, unpaired activities on the unit's day and sport family."""
    event_kind = _activity_kind(event)
    if event_kind == "other":
        return []
    event_date = record_date(_first_present(event, _UNIT_START_FIELDS))
    return [
        activity_index
        for activity_index in unused
        if _is_unpaired(activity_rows[activity_index])
        and record_date(
            _first_present(activity_rows[activity_index], _ACTIVITY_START_FIELDS)
        )
        == event_date
        and _activity_kind(activity_rows[activity_index]) == event_kind
    ]


def _start_distance(activity: dict[str, Any], event_start: datetime | None) -> float:
    activity_start = _activity_datetime(
        _first_present(activity, _ACTIVITY_START_FIELDS)
    )
    if activity_start and event_start:
        return abs((activity_start - event_start).total_seconds())
    return 0


def _duration_gap(unit: dict[str, Any], activity: dict[str, Any]) -> float:
    """Relative duration difference from the planned duration."""
    planned = _number_field(unit, _DURATION_FIELDS)
    actual = _number_field(activity, _DURATION_FIELDS)
    if planned is None or actual is None or planned <= 0:
        return math.inf
    return abs(actual - planned) / planned


def _load_gap(unit: dict[str, Any], activity: dict[str, Any]) -> float:
    """Absolute training-load difference; unknown when either side lacks load."""
    planned = _number_field(unit, _LOAD_FIELDS)
    actual = _number_field(activity, _LOAD_FIELDS)
    if planned is None or actual is None:
        return math.inf
    return abs(actual - planned)


def _record_order(record: Any, start_fields: tuple[str, ...]) -> tuple[str, str, str]:
    """Input-order-independent key: start time, identity, then full content."""
    return (
        str(_first_present(record, start_fields) or ""),
        str(_first_present(record, ("id", "event_id")) or ""),
        json.dumps(record, sort_keys=True, default=str),
    )


def _best_fit_rank(
    unit: dict[str, Any], activity: dict[str, Any], activity_index: int
) -> tuple[Any, ...]:
    """Rank a same-day candidate; smaller ranks are better fits.

    Sport family is a gate applied by `_same_day_candidates`, so only same-family
    candidates are ranked. Then: duration gap, load gap, activity start time, and
    stable identity ordering.
    """
    return (
        _duration_gap(unit, activity),
        _load_gap(unit, activity),
        _record_order(activity, _ACTIVITY_START_FIELDS),
        _record_order(unit, _UNIT_START_FIELDS),
        activity_index,
    )


def _best_fit_date_only_matches(
    units: list[tuple[int, dict[str, Any]]],
    activity_rows: list[dict[str, Any]],
    unused: set[int],
) -> dict[int, int]:
    """Assign date-only units to activities one-to-one, best-ranked pairs first."""
    ranked: list[tuple[tuple[Any, ...], int, int]] = []
    for unit_index, unit in units:
        for activity_index in _same_day_candidates(unit, activity_rows, unused):
            rank = _best_fit_rank(unit, activity_rows[activity_index], activity_index)
            ranked.append((rank, unit_index, activity_index))
    assignments: dict[int, int] = {}
    taken: set[int] = set()
    for _rank, unit_index, activity_index in sorted(ranked):
        if unit_index in assignments or activity_index in taken:
            continue
        assignments[unit_index] = activity_index
        taken.add(activity_index)
    return assignments


def _unpaired_activity_match(
    event: dict[str, Any], activity_rows: list[dict[str, Any]], unused: set[int]
) -> int | None:
    event_start = _activity_datetime(_first_present(event, _UNIT_START_FIELDS))
    candidates = [
        (_start_distance(activity_rows[index], event_start), index)
        for index in _same_day_candidates(event, activity_rows, unused)
    ]
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

    unmatched = [
        (index, event) for index, event in workout_rows if index not in matches
    ]
    timed_units = [
        (index, event)
        for index, event in unmatched
        if _has_start_time(_first_present(event, _UNIT_START_FIELDS))
    ]
    date_only_units = [
        (index, event)
        for index, event in unmatched
        if not _has_start_time(_first_present(event, _UNIT_START_FIELDS))
    ]

    # Manually logged units with a start time keep the nearest-start rule.
    for event_index, event in timed_units:
        selected_index = _unpaired_activity_match(event, activity_rows, unused)
        if selected_index is not None:
            matches[event_index] = activity_rows[selected_index]
            unused.remove(selected_index)

    # Date-only units are paired by best fit, so input order cannot decide who wins
    # a same-day activity. Pairing is one-to-one and never steals a paired activity.
    for event_index, activity_index in _best_fit_date_only_matches(
        date_only_units, activity_rows, unused
    ).items():
        matches[event_index] = activity_rows[activity_index]
        unused.remove(activity_index)
    return matches
