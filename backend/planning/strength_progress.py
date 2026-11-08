"""Executed strength progression for planning: the recent top sets per exercise.

From the completed activity summaries (their ``strength_sets``), each exercise
lists its last sessions, newest first, with the number of sets and the top set
(heaviest weight with its reps). Exercises are keyed by their provider code, else
their category. No estimated 1RM: that would need a released method card. No I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix

MAX_SESSIONS: Final = 6
MAX_EXERCISES: Final = 10
SOURCE: Final = (
    "Executed strength sets of completed sessions (Garmin exercise sets, else the "
    "FIT set messages); top set = heaviest weight with its reps; never added to "
    "endurance load"
)


def strength_progress(completed: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The last sessions per exercise, newest exercises first."""
    rows = sorted(
        (row for row in completed if isinstance(row.get("strength_sets"), Mapping)),
        key=lambda row: str(row.get("started_at_local") or ""),
        reverse=True,
    )
    exercises: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = iso_date_prefix(row.get("started_at_local"))
        for exercise in row["strength_sets"].get("exercises") or ():
            key = exercise.get("name") or exercise.get("category")
            if not key:
                continue
            entry = exercises.setdefault(
                key,
                {
                    "exercise": key,
                    "category": exercise.get("category"),
                    "leg": exercise.get("leg"),
                    "sessions": [],
                },
            )
            sessions = entry["sessions"]
            if len(sessions) < MAX_SESSIONS and (
                not sessions or sessions[-1]["date"] != day
            ):
                sessions.append(
                    {
                        "date": day,
                        "sets": exercise.get("sets"),
                        "top_kg": exercise.get("top_kg"),
                        "top_reps": exercise.get("top_reps"),
                    }
                )
    return {"source": SOURCE, "exercises": list(exercises.values())[:MAX_EXERCISES]}
