"""Shared rules for the remote leftovers of deleted or replaced planned units."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

# One sync job takes at most 28 entries; the rest waits for the next sync.
MAX_CLEANUP: Final = 20


@dataclass(frozen=True)
class GarminOrphan:
    """A pushed Garmin workout whose planned unit is gone or no longer pushable."""

    local_id: str
    name: str
    date: str


def nearest_first[T](
    items: Sequence[T], today: date, day_of: Callable[[T], str]
) -> list[T]:
    """Upcoming days first, soonest first; then past days, newest first; undated last."""
    now = today.isoformat()
    upcoming = sorted((i for i in items if day_of(i) >= now), key=day_of)
    past = sorted(
        (i for i in items if day_of(i) and day_of(i) < now), key=day_of, reverse=True
    )
    undated = [i for i in items if not day_of(i)]
    return [*upcoming, *past, *undated]


def cap[T](items: list[T], limit: int | None) -> list[T]:
    return items if limit is None else items[:limit]
