"""Pure projections for calendar conflicts during local planning."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

_UTC_OFFSET_SUFFIX = "+00:00"
_HARD_EFFORT_PATTERN = re.compile(
    r"\b(?:intervals?|vo2(?:max)?|threshold|tempo|sprints?|race|tabata|hiit|hard|sweet\s*spot)\b|\b(?:9[0-9]|100|10[5-9]|11[0-9])%"
)
_EASY_EFFORT_PATTERN = re.compile(
    r"\b(?:easy|recovery|regeneration|locker|ruhetag|z1|zone\s*1)\b"
)


def workout_is_explicitly_easy(workout: dict[str, Any]) -> bool:
    """Return whether a workout explicitly opts into easy effort."""
    text = (
        f"{workout.get('name', '')} {workout.get('description', '')} "
        f"{workout.get('target', '')} "
        f"{workout.get('steps', '')} {workout.get('intervals', '')} "
        f"{workout.get('workout_steps', '')}"
    ).casefold()
    if _HARD_EFFORT_PATTERN.search(text):
        return False
    return bool(_EASY_EFFORT_PATTERN.search(text))


def workout_is_rest(workout: dict[str, Any]) -> bool:
    text = f"{workout.get('name', '')} {workout.get('description', '')}".casefold()
    if _HARD_EFFORT_PATTERN.search(text):
        return False
    if any(
        workout.get(key) not in (None, "", [], {})
        for key in ("steps", "intervals", "distance", "distance_meters")
    ):
        return False
    duration = workout.get("duration_minutes")
    if duration in (None, "") and workout.get("moving_time") not in (None, ""):
        try:
            duration = float(workout["moving_time"]) / 60
        except (TypeError, ValueError):
            duration = None
    try:
        if duration not in (None, "") and float(duration) <= 0:
            return True
    except (TypeError, ValueError):
        pass
    if duration not in (None, ""):
        return False
    return bool(re.search(r"\b(?:rest|ruhetag|sportpause)\b", text))


def calendar_constraint_decision(
    workout: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any] | None:
    """Centralize external event constraints used by every planning mutation."""
    marker_text = f"{event.get('name', '')} {event.get('description', '')}".casefold()
    no_training = bool(event.get("no_training")) or "[no_training]" in marker_text
    no_intensity = bool(event.get("no_intensity")) or "[no_intensity]" in marker_text
    if no_training and not workout_is_rest(workout):
        return {
            "blocked": True,
            "reason": "no_training",
            "marker": "[NO_TRAINING]",
        }
    if no_intensity and not workout_is_explicitly_easy(workout):
        return {
            "blocked": True,
            "reason": "no_intensity",
            "marker": "[NO_INTENSITY]",
        }
    return None


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _naive_calendar_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", _UTC_OFFSET_SUFFIX)
        )
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _calendar_duration_minutes(value: dict[str, Any], default_minutes: int) -> int:
    duration = value.get("duration_minutes")
    if duration in (None, "") and value.get("moving_time") not in (None, ""):
        duration = float(value["moving_time"]) / 60
    try:
        return (
            max(1, int(float(duration)))
            if duration not in (None, "")
            else default_minutes
        )
    except (TypeError, ValueError):
        return default_minutes


def _calendar_interval_end(
    value: dict[str, Any], start: datetime, default_minutes: int
) -> datetime:
    end = _naive_calendar_datetime(
        _first_present(value, ("end_date_local", "end_local", "end"))
    )
    if end is None:
        end = start + timedelta(
            minutes=_calendar_duration_minutes(value, default_minutes)
        )
    return max(end, start + timedelta(minutes=1))


def _calendar_interval(
    value: dict[str, Any], default_minutes: int = 60
) -> tuple[datetime, datetime, bool] | None:
    raw_start = _first_present(
        value, ("start_date_local", "start_local", "start", "date")
    )
    if raw_start in (None, ""):
        return None
    raw_start = str(raw_start).strip()
    if len(raw_start) == 10:
        try:
            day_start = datetime.combine(
                date.fromisoformat(raw_start), datetime.min.time()
            )
        except ValueError:
            return None
        return day_start, day_start + timedelta(days=1), False
    start = _naive_calendar_datetime(raw_start)
    if start is None:
        return None
    end = _calendar_interval_end(value, start, default_minutes)
    return start, max(end, start + timedelta(minutes=1)), True


def _calendar_items_conflict(
    candidate: dict[str, Any], existing: dict[str, Any]
) -> tuple[bool, str]:
    candidate_date = str(
        _first_present(
            candidate, ("date", "event_date", "start_date_local", "start_local")
        )
        or ""
    )[:10]
    existing_date = str(
        _first_present(
            existing, ("date", "event_date", "start_date_local", "start_local")
        )
        or ""
    )[:10]
    candidate_interval = _calendar_interval(candidate)
    existing_interval = _calendar_interval(existing)
    if candidate_interval and existing_interval:
        overlaps = (
            candidate_interval[0] < existing_interval[1]
            and existing_interval[0] < candidate_interval[1]
        )
        if not candidate_interval[2] or not existing_interval[2]:
            return overlaps, "date"
        return (
            overlaps,
            "time_window",
        )
    return bool(candidate_date and candidate_date == existing_date), "date"


def _calendar_conflict_record(
    item: dict[str, Any], source: str, match: str
) -> dict[str, Any]:
    interval = _calendar_interval(item)
    return {
        "id": item.get("id") or item.get("local_id"),
        "name": item.get("name") or "Einheit",
        "date": str(
            _first_present(
                item, ("date", "event_date", "start_date_local", "start_local")
            )
            or ""
        )[:10],
        "source": source,
        "match": match,
        "start_local": interval[0].isoformat(timespec="minutes")
        if interval and interval[2]
        else None,
        "end_local": interval[1].isoformat(timespec="minutes")
        if interval and interval[2]
        else None,
    }


def calendar_conflicts_for_items(
    candidate: dict[str, Any], items: list[dict[str, Any]], source: str
) -> list[dict[str, Any]]:
    conflicts = []
    for item in items:
        matches, match = _calendar_items_conflict(candidate, item)
        if matches:
            if source == "local_library" and match != "time_window":
                continue
            conflicts.append(_calendar_conflict_record(item, source, match))
    return conflicts
