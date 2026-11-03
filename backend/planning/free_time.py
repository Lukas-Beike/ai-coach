"""Free minutes per day: effective weekly-plan windows minus timed calendar events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from backend.athlete import weekly_plan
from backend.planning.conflicts import calendar_item_window


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _busy_spans(
    events: Sequence[Mapping[str, Any]], day: date
) -> list[tuple[int, int]]:
    """Minute spans of the timed events on one local day; all-day events are ignored."""
    start = _day_start(day)
    end = start + timedelta(days=1)
    spans = []
    for event in events:
        window = None if event.get("all_day") else calendar_item_window(dict(event))
        if window and window[0] < end and window[1] > start:
            left = max(window[0], start) - start
            right = min(window[1], end) - start
            spans.append(
                (int(left.total_seconds() // 60), round(right.total_seconds() / 60))
            )
    return spans


def free_minutes(
    day: date, windows: Sequence[str], events: Sequence[Mapping[str, Any]]
) -> int:
    """Minutes of ``windows`` not covered by any timed event; overlaps count once."""
    spans = sorted(_busy_spans(events, day))
    total = 0
    for text in windows:
        parsed = weekly_plan.parse_window(text)
        if not parsed:
            continue
        cursor = parsed[0]
        for left, right in spans:
            if right <= cursor or left >= parsed[1]:
                continue
            total += max(0, left - cursor)
            cursor = max(cursor, right)
        total += max(0, parsed[1] - cursor)
    return total


def free_time_brief(
    plan: Any, events: Sequence[Mapping[str, Any]], first: date, days: int
) -> dict[str, dict[str, Any]]:
    """Per local date: free minutes in the effective windows and their source."""
    week = weekly_plan.effective_week(plan)
    result = {}
    for offset in range(days):
        day = first + timedelta(days=offset)
        effective = week[day.weekday()]
        result[day.isoformat()] = {
            "minutes": free_minutes(day, effective.windows, events),
            "source": effective.source,
        }
    return result
