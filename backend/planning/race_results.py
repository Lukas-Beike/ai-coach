"""Race results of past competitions, read from the sessions linked to them.

The canonical reader links a completed race session to its stored competition
(``backend.activities.session_purpose.with_competitions``). Each past competition
gets that session's result: elapsed time (else moving time), distance, average
speed and power, its canonical sport and the source label of the link. Today's
competition takes only a provider race, never the competition-date hint, so a
session done before the start never shows as the result. Nothing is stored; a
competition without a linked session gets no result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Final

from backend.activities.session_purpose import COMPETITION_SOURCE_LABEL

_RESULT_KEYS: Final = ("distance_m", "avg_speed_mps", "avg_power")


def with_race_results(
    competitions: Iterable[dict[str, Any]],
    today: date,
    summaries_on: Callable[
        [Sequence[date]], Mapping[date, Sequence[Mapping[str, Any]]]
    ],
) -> list[dict[str, Any]]:
    """Return the competitions, each past one with its linked session's result.

    ``summaries_on`` reads the summaries of several local days in one read.
    """
    rows = list(competitions)
    days = sorted(
        {day for row in rows if (day := _event_day(row)) is not None and day <= today}
    )
    summaries = summaries_on(days) if days else {}
    return [_with_result(row, summaries, today) for row in rows]


def _with_result(
    competition: dict[str, Any],
    summaries: Mapping[date, Sequence[Mapping[str, Any]]],
    today: date,
) -> dict[str, Any]:
    day = _event_day(competition)
    race = next(
        (
            row
            for row in (summaries.get(day, ()) if day is not None else ())
            if row.get("competition_id") == competition.get("id")
            and (day != today or _source(row) != COMPETITION_SOURCE_LABEL)
        ),
        None,
    )
    return competition if race is None else {**competition, "result": _result(race)}


def _result(summary: Mapping[str, Any]) -> dict[str, Any]:
    duration = summary.get("elapsed_duration_s")
    if duration is None:
        duration = summary.get("moving_duration_s")
    values: dict[str, Any] = {
        "sport": summary.get("sport"),
        "duration_s": duration,
        "source": _source(summary),
    }
    for key in _RESULT_KEYS:
        value = summary.get(key)
        if value is not None:
            values[key] = value
    return values


def _source(summary: Mapping[str, Any]) -> Any:
    return (summary.get("sources") or {}).get("purpose") or summary.get("source")


def _event_day(competition: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(competition.get("event_date") or "")[:10])
    except ValueError:
        return None
