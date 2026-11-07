"""Race results of past competitions, read from the sessions linked to them.

The canonical reader links a completed race session to its stored competition
(``backend.activities.session_purpose.with_competitions``). Each competition up
to today gets that session's result: duration, distance, average pace (runs and
other sports with speed) or average power (rides), and the source label of the
link. Nothing is stored; a competition without a linked session gets no result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Final

from backend.canonical.activity_summary import summary_duration_s

# At most this many past competition days are read; older ones get no result.
MAX_RESULT_DAYS: Final = 100
_RESULT_KEYS: Final = ("distance_m", "avg_speed_mps", "avg_power", "avg_hr")


def with_race_results(
    competitions: Iterable[dict[str, Any]],
    today: date,
    summaries_on: Callable[[date], Sequence[Mapping[str, Any]] | None],
) -> list[dict[str, Any]]:
    """Return the competitions, each past one with its linked session's result.

    The newest ``MAX_RESULT_DAYS`` past competition days are read, one read each.
    """
    rows = list(competitions)
    past = {
        day for row in rows if (day := _event_day(row)) is not None and day <= today
    }
    days = {
        day: summaries_on(day) or ()
        for day in sorted(past, reverse=True)[:MAX_RESULT_DAYS]
    }
    return [
        _with_result(row, days.get(_event_day(row) or date.min, ())) for row in rows
    ]


def _with_result(
    competition: dict[str, Any], summaries: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    race = next(
        (
            row
            for row in summaries
            if row.get("competition_id") == competition.get("id")
        ),
        None,
    )
    return competition if race is None else {**competition, "result": _result(race)}


def _result(summary: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {
        "activity_id": summary.get("id"),
        "duration_s": summary_duration_s(summary),
        "source": (summary.get("sources") or {}).get("purpose")
        or summary.get("source"),
    }
    for key in _RESULT_KEYS:
        value = summary.get(key)
        if value is not None:
            values[key] = value
    return values


def _event_day(competition: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(competition.get("event_date") or "")[:10])
    except ValueError:
        return None
