"""Free time per day: effective weekly-plan windows minus timed calendar events.

All-day events are listed, never subtracted. A free block is a contiguous
stretch of a window without a timed event.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from backend.athlete import weekly_plan
from backend.planning import calendar_load
from backend.planning.conflicts import calendar_item_window


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def busy_spans(events: Sequence[Mapping[str, Any]], day: date) -> list[tuple[int, int]]:
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
                (round(left.total_seconds() / 60), round(right.total_seconds() / 60))
            )
    return spans


def free_blocks(
    windows: Sequence[str], spans: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Contiguous free ``(start, end)`` minutes of each window outside ``spans``."""
    ordered = sorted(spans)
    blocks = []
    for text in windows:
        parsed = weekly_plan.parse_window(text)
        if not parsed:
            continue
        cursor = parsed[0]
        for left, right in ordered:
            if right <= cursor or left >= parsed[1]:
                continue
            if left > cursor:
                blocks.append((cursor, left))
            cursor = max(cursor, right)
        if parsed[1] > cursor:
            blocks.append((cursor, parsed[1]))
    return blocks


def free_minutes(
    day: date, windows: Sequence[str], events: Sequence[Mapping[str, Any]]
) -> int:
    """Minutes of ``windows`` not covered by any timed event; overlaps count once."""
    return sum(
        right - left for left, right in free_blocks(windows, busy_spans(events, day))
    )


def longest_block(
    day: date, windows: Sequence[str], events: Sequence[Mapping[str, Any]]
) -> int:
    """Minutes of the longest contiguous free block within ``windows``."""
    blocks = free_blocks(windows, busy_spans(events, day))
    return max((right - left for left, right in blocks), default=0)


def free_time_brief(
    plan: Any, events: Sequence[Mapping[str, Any]], first: date, days: int
) -> dict[str, dict[str, Any]]:
    """Per local date: free and longest contiguous minutes, per window, all-day events."""
    week = weekly_plan.effective_week(plan)
    result = {}
    for offset in range(days):
        day = first + timedelta(days=offset)
        effective = week[day.weekday()]
        entry: dict[str, Any] = {
            "minutes": free_minutes(day, effective.windows, events),
            "longest_block_minutes": longest_block(day, effective.windows, events),
            "source": effective.source,
        }
        if len(effective.windows) > 1:
            entry["windows"] = [
                {
                    "window": text,
                    "minutes": free_minutes(day, [text], events),
                    "longest_block_minutes": longest_block(day, [text], events),
                }
                for text in effective.windows
            ]
        if all_day := calendar_load.all_day_events(events, day):
            entry["all_day_events"] = all_day
        result[day.isoformat()] = entry
    return result
