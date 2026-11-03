"""Deterministic placement of one day's units into its free blocks.

Units with a start time keep their own interval and must not overlap a timed
event; the others go greedily, longest first, into the smallest free block that
holds them. A unit that cannot be placed is returned. No I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.planning import free_time

OVERLAP: Final = "overlap"
NO_BLOCK: Final = "no_block"
SHARED: Final = "shared_with_other_units"


@dataclass(frozen=True)
class Request:
    key: int
    minutes: int
    start: int | None
    windows: Sequence[str]


@dataclass(frozen=True)
class Unplaced:
    key: int
    reason: str
    free_minutes: int
    longest_block_minutes: int


def _longest(blocks: Sequence[tuple[int, int]]) -> int:
    return max((right - left for left, right in blocks), default=0)


def _timed(
    requests: Sequence[Request], spans: Sequence[tuple[int, int]]
) -> tuple[list[Request], list[tuple[int, int]]]:
    """Timed requests overlapping a timed event, and the intervals the others take."""
    overlapping: list[Request] = []
    taken: list[tuple[int, int]] = []
    for request in requests:
        begin = request.start or 0
        interval = (begin, begin + request.minutes)
        if any(left < interval[1] and right > interval[0] for left, right in spans):
            overlapping.append(request)
        else:
            taken.append(interval)
    return overlapping, taken


def _place(request: Request, pool: dict[str, list[tuple[int, int]]]) -> bool:
    """Put the request into its smallest fitting block; false when none fits."""
    fits = [
        (right - left, left, text)
        for text in request.windows
        for left, right in pool.get(text, ())
        if right - left >= request.minutes
    ]
    if not fits:
        return False
    length, left, text = min(fits)
    blocks = pool[text]
    blocks.remove((left, left + length))
    if request.minutes < length:
        blocks.append((left + request.minutes, left + length))
    return True


def allocate(
    day: date, requests: Sequence[Request], events: Sequence[Mapping[str, Any]]
) -> list[Unplaced]:
    """Requests that do not fit, ordered by key."""
    spans = free_time.busy_spans(events, day)
    overlapping, taken = _timed([r for r in requests if r.start is not None], spans)
    pool = {
        text: free_time.free_blocks([text], [*spans, *taken])
        for text in {name for item in requests for name in item.windows}
    }
    failed = [(item, OVERLAP) for item in overlapping]
    loose = [item for item in requests if item.start is None]
    for item in sorted(loose, key=lambda value: (-value.minutes, value.key)):
        if not _place(item, pool):
            alone = _longest(free_time.free_blocks(item.windows, spans))
            failed.append((item, SHARED if alone >= item.minutes else NO_BLOCK))
    return [
        Unplaced(
            item.key,
            reason,
            free_time.free_minutes(day, item.windows, events),
            free_time.longest_block(day, item.windows, events),
        )
        for item, reason in sorted(failed, key=lambda value: value[0].key)
    ]
