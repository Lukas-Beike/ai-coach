"""Calendar occupancy and non-blocking planning observations."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from backend.planning.conflicts import calendar_item_window, calendar_items_conflict

HEAVY_DAY_MINUTES = 8 * 60
ALL_DAY_FLAGS = (
    "training_impact",
    "training_relevant",
    "no_training",
    "no_intensity",
    "short_only",
)


def _timed(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """All-day events are day-level context, not busy time."""
    return [event for event in events if not event.get("all_day")]


def all_day_events(
    events: Sequence[Mapping[str, Any]], day: date
) -> list[dict[str, Any]]:
    """All-day events of one local day with their training-impact flags.

    They are day-level context: never subtracted from free or busy minutes.
    """
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    result = []
    for event in events:
        window = calendar_item_window(dict(event)) if event.get("all_day") else None
        if window and window[0] < end and window[1] > start:
            result.append(
                {
                    "name": str(event.get("name") or "")[:80],
                    **{
                        flag: bool(event[flag])
                        for flag in ALL_DAY_FLAGS
                        if flag in event
                    },
                    "all_day": True,
                }
            )
    return result


def busy_minutes(
    events: Sequence[Mapping[str, Any]], first: date, days: int
) -> dict[str, int]:
    """Union event intervals per local day, clipping to the requested horizon."""
    result = {}
    intervals = [calendar_item_window(dict(event)) for event in _timed(events)]
    for offset in range(days):
        day = first + timedelta(days=offset)
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        segments = sorted(
            (max(start, item[0]), min(end, item[1]))
            for item in intervals
            if item and item[0] < end and item[1] > start
        )
        merged: list[tuple[datetime, datetime]] = []
        for left, right in segments:
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        if merged:
            result[day.isoformat()] = round(
                sum((right - left).total_seconds() for left, right in merged) / 60
            )
    return result


def calendar_risk(
    unit: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    occupied: Mapping[str, int],
) -> tuple[bool, int]:
    day = str(unit.get("date") or unit.get("starts_at_local") or "")[:10]
    overlap = any(
        conflict and match == "time_window"
        for conflict, match in (
            calendar_items_conflict(dict(unit), dict(event)) for event in _timed(events)
        )
    )
    return overlap, occupied.get(day, 0)
