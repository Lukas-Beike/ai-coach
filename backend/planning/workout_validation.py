"""Validate planned workout text against its structured duration.

Endurance families (provider-owned exact Intervals types) must be quantity-first
and their step durations must agree with the planned duration. Other sport
families keep free-text instructions and are not checked here.
"""

import math
import re
from itertools import pairwise
from typing import Any

from backend.activities.workout_text import WorkoutTextError, structured_duration
from backend.errors import AppError
from backend.providers.intervals_workouts import (
    INTERVALS_ENDURANCE_WORKOUT_TYPES,
    intervals_record_type,
)

WORKOUT_STEP_QUANTITY = re.compile(r"\d+(?:[.,]\d+)?\s*(?P<unit>[A-Za-z'\"]+)")
WORKOUT_STEP_QUANTITY_UNITS = {
    "km",
    "mtr",
    "mi",
    "yd",
    "yard",
    "yards",
    "meter",
    "meters",
    "metre",
    "metres",
    "minute",
    "minutes",
    "min",
    "mins",
    "second",
    "seconds",
    "sec",
    "secs",
    "hour",
    "hours",
    "hr",
    "hrs",
    "h",
    "m",
    "s",
    "'",
    '"',
}
WORKOUT_STEP_TIME_UNITS = {
    "h",
    "m",
    "s",
    "hours",
    "hrs",
    "minutes",
    "mins",
    "seconds",
    "secs",
    "'",
    '"',
}


def _workout_step_amounts(text: str) -> list[re.Match[str]]:
    """Return step quantities, excluding pace denominators such as /100m."""
    return [
        match
        for match in WORKOUT_STEP_QUANTITY.finditer(text)
        if match.group("unit") in WORKOUT_STEP_QUANTITY_UNITS
        and (match.start() == 0 or text[match.start() - 1] != "/")
    ]


def _raise_ambiguous_workout_step(line_number: int, message: str) -> None:
    raise AppError(
        400,
        f"Workout-Text in Zeile {line_number} ist mehrdeutig: {message}",
        reason="ambiguous_workout_step",
    )


def _is_composite_duration(amounts: list[re.Match[str]]) -> bool:
    return all(
        current.start() == previous.end()
        and previous.group("unit").casefold() in WORKOUT_STEP_TIME_UNITS
        and current.group("unit").casefold() in WORKOUT_STEP_TIME_UNITS
        for previous, current in pairwise(amounts)
    )


def _validate_endurance_workout_steps(description: str) -> None:
    for line_number, line in enumerate(description.splitlines(), 1):
        stripped = line.lstrip(" \t")
        if not stripped.startswith("-"):
            continue
        text = stripped[1:].lstrip(" \t")
        if not text:
            continue
        amounts = _workout_step_amounts(text)
        if amounts and amounts[0].start() != 0:
            _raise_ambiguous_workout_step(
                line_number,
                "Trainingsschritte mit '- ' müssen direkt mit Dauer oder Distanz beginnen "
                "(z.B. '- 6km Z1 HR'). Hinweise, Bedingungen und optionale Gesamtstrecken "
                "als eigenen Absatz ohne '- ' schreiben; sonst zählt Intervals.icu sie als weitere Schritte.",
            )
        if len(amounts) > 1 and not _is_composite_duration(amounts):
            _raise_ambiguous_workout_step(
                line_number,
                "Ein Trainingsschritt darf nur eine Distanz oder Dauer enthalten; "
                "zusammengesetzte Zeiten wie '- 1h30m Z2' sind erlaubt. "
                "Optionale Gesamtstrecken als eigenen Absatz ohne '- ' schreiben.",
            )


def _structured_workout_duration(description: str, target: str) -> tuple[float, bool]:
    try:
        return structured_duration(description, target)
    except WorkoutTextError as exc:
        raise AppError(400, str(exc), reason=exc.reason) from exc


def _validate_workout_duration_match(
    seconds: float, has_distance: bool, expected_seconds: float | None
) -> None:
    if expected_seconds is None or (
        seconds <= expected_seconds
        if has_distance
        else abs(seconds - expected_seconds) <= 30
    ):
        return
    raise AppError(
        400,
        f"Trainingsschritte ergeben {seconds / 60:g} Minuten, die angegebene Dauer ist {expected_seconds / 60:g} Minuten. "
        "Dauer und Workout-Text einschliesslich aller Wiederholungen, Pausen, Warmup und Cooldown abgleichen; keine fehlenden Minuten erfinden.",
        reason="workout_duration_mismatch",
    )


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def validate_workout_description(workout: dict[str, Any]) -> float | None:
    """Require quantity-first endurance steps; never guess intent from prose."""
    sport = intervals_record_type(workout)
    if sport not in INTERVALS_ENDURANCE_WORKOUT_TYPES:
        return None
    description = str(workout.get("description") or "")[:12000]
    _validate_endurance_workout_steps(description)
    seconds, has_distance = _structured_workout_duration(
        description, str(workout.get("target") or "AUTO")
    )
    expected_minutes = _as_number(workout.get("duration_minutes"))
    expected_seconds = (
        expected_minutes * 60
        if expected_minutes is not None
        else _as_number(workout.get("moving_time"))
    )
    _validate_workout_duration_match(seconds, has_distance, expected_seconds)
    return None if has_distance else seconds
