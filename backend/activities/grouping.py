"""Grouping for planned cycling events with overlapping or vague times."""

import math
from datetime import datetime, timedelta
from typing import Any

from backend.activities.identity import activity_datetime, activity_kind


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _cycling_event_candidates(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    return [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("id") not in (None, "")
        and activity_kind(event) == "cycling"
    ]


def _cycling_event_interval(
    event: dict[str, Any],
) -> tuple[datetime, datetime, bool] | None:
    raw_start = str(event.get("start_date_local") or event.get("date") or "")
    start = activity_datetime(raw_start)
    if start is None:
        return None
    explicit_time = "T" in raw_start and start.time() != datetime.min.time()
    duration = _as_number(event.get("moving_time"))
    seconds = (
        max(60, float(duration)) if duration is not None and duration > 0 else 3600
    )
    return start, start + timedelta(seconds=seconds), explicit_time


def _cycling_intervals_share_group(
    left: tuple[datetime, datetime, bool],
    right: tuple[datetime, datetime, bool],
) -> bool:
    left_start, left_end, left_has_time = left
    right_start, right_end, right_has_time = right
    if left_start.date() != right_start.date():
        return False
    overlap = left_start < right_end and right_start < left_end
    return overlap or not (left_has_time and right_has_time)


def _cycling_event_edges(
    intervals: list[tuple[datetime, datetime, bool] | None],
) -> list[set[int]]:
    edges = [set() for _ in intervals]
    for left_index, left in enumerate(intervals):
        if left is None:
            continue
        for right_index in range(left_index + 1, len(intervals)):
            right = intervals[right_index]
            if right is None:
                continue
            if _cycling_intervals_share_group(left, right):
                edges[left_index].add(right_index)
                edges[right_index].add(left_index)
    return edges


def _cycling_event_group(
    start_index: int,
    candidates: list[dict[str, Any]],
    edges: list[set[int]],
    visited: set[int],
) -> list[dict[str, Any]]:
    stack = [start_index]
    visited.add(start_index)
    group: list[dict[str, Any]] = []
    while stack:
        index = stack.pop()
        group.append(candidates[index])
        for neighbour in edges[index]:
            if neighbour not in visited:
                visited.add(neighbour)
                stack.append(neighbour)
    return sorted(
        group,
        key=lambda event: str(event.get("start_date_local") or event.get("date") or ""),
    )


def parallel_cycling_event_groups(events: Any) -> list[list[dict[str, Any]]]:
    """Find planned rides whose times overlap or are too vague to distinguish."""
    candidates = _cycling_event_candidates(events)
    edges = _cycling_event_edges(
        [_cycling_event_interval(event) for event in candidates]
    )
    visited: set[int] = set()
    return [
        _cycling_event_group(index, candidates, edges, visited)
        for index in range(len(candidates))
        if index not in visited and edges[index]
    ]
