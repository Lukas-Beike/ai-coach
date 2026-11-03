"""The running week as completed days plus the remaining planned days.

Planned units are future-only, so the days of the current ISO week before today
exist only as completed activities. Checks that judge a whole week combine both
and label it ``RUNNING_WEEK_BASIS``. No I/O.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.planning.sport import planned_sport_environment

RUNNING_WEEK_BASIS = "running week: completed + planned"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _day(row: Mapping[str, Any]) -> str:
    return iso_date_prefix(
        row.get("started_at_local") or row.get("date") or row.get("starts_at_local")
    )


def completed_this_week(
    completed: Iterable[Mapping[str, Any]], today: date
) -> list[Mapping[str, Any]]:
    """Completed activities from this week's Monday to today."""
    first = week_start(today).isoformat()
    return [row for row in completed if first <= _day(row) <= today.isoformat()]


def without_done_today(
    units: Sequence[Mapping[str, Any]],
    completed: Iterable[Mapping[str, Any]],
    today: date,
) -> list[Mapping[str, Any]]:
    """Units without today's planned ones that a completed activity replaces.

    Each completed activity of today replaces one planned unit of its sport, so a
    second planned session of the day stays.
    """
    done = Counter(
        str(row.get("sport")) for row in completed if _day(row) == today.isoformat()
    )
    kept = []
    for unit in units:
        sport = planned_sport_environment(unit)[0].value
        if _day(unit) == today.isoformat() and done[sport] > 0:
            done[sport] -= 1
            continue
        kept.append(unit)
    return kept
