"""Normalize local workout drafts and validate Intervals.icu workout data."""

import math
import re
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from backend.errors import AppError
from backend.providers.workout_text import (
    WorkoutTextError,
    canonical_workout_zones,
    structured_duration,
    verify_workout_readback,
)

COACH_EVENT_EXTERNAL_PREFIX = "intervals-coach-"

INTERVALS_WORKOUT_SPORTS = {
    "cycling": "Ride",
    "rad": "Ride",
    "rad outdoor": "Ride",
    "radfahren": "Ride",
    "ride": "Ride",
    "virtualride": "VirtualRide",
    "virtual ride": "VirtualRide",
    "rad indoor": "VirtualRide",
    "indoor cycling": "VirtualRide",
    "virtual cycling": "VirtualRide",
    "running": "Run",
    "lauf": "Run",
    "laufen": "Run",
    "run": "Run",
    "strength": "WeightTraining",
    "kraft": "WeightTraining",
    "krafttraining": "WeightTraining",
    "weighttraining": "WeightTraining",
    "bike": "Ride",
    "biking": "Ride",
    "bicycle": "Ride",
    "bike workout": "Ride",
    "cycling workout": "Ride",
    "swim": "Swim",
    "swimming": "Swim",
    "schwimmen": "Swim",
    "run workout": "Run",
    "jogging": "Run",
    "jog": "Run",
    "gym": "WeightTraining",
    "weights": "WeightTraining",
    "weight training": "WeightTraining",
    "hiking": "Hike",
    "walking": "Walk",
    "row": "Rowing",
    "rowing": "Rowing",
    "yoga": "Yoga",
}

INTERVALS_WORKOUT_TYPES = {
    "Ride",
    "Run",
    "Swim",
    "WeightTraining",
    "Hike",
    "Walk",
    "AlpineSki",
    "BackcountrySki",
    "Badminton",
    "Canoeing",
    "Crossfit",
    "EBikeRide",
    "EMountainBikeRide",
    "Elliptical",
    "Golf",
    "GravelRide",
    "Handcycle",
    "HighIntensityIntervalTraining",
    "IceSkate",
    "InlineSkate",
    "Kayaking",
    "Kitesurf",
    "MountainBikeRide",
    "NordicSki",
    "OpenWaterSwim",
    "Padel",
    "Pilates",
    "Pickleball",
    "Racquetball",
    "Rugby",
    "RockClimbing",
    "RollerSki",
    "Rowing",
    "Sail",
    "Skateboard",
    "Snowboard",
    "Snowshoe",
    "Soccer",
    "Squash",
    "StairStepper",
    "StandUpPaddling",
    "Surfing",
    "TableTennis",
    "Tennis",
    "TrailRun",
    "Transition",
    "Velomobile",
    "VirtualRide",
    "VirtualRow",
    "VirtualRun",
    "WaterSport",
    "Wheelchair",
    "Windsurf",
    "Workout",
    "Yoga",
    "Other",
}

# These sport families have duration/distance and intensity prescriptions.
# Other supported activities retain free-text instructions (e.g. Yoga/Golf).
INTERVALS_ENDURANCE_WORKOUT_TYPES = {
    "Ride",
    "VirtualRide",
    "EBikeRide",
    "EMountainBikeRide",
    "GravelRide",
    "MountainBikeRide",
    "Velomobile",
    "Handcycle",
    "Run",
    "TrailRun",
    "VirtualRun",
    "Walk",
    "Hike",
    "Wheelchair",
    "Swim",
    "OpenWaterSwim",
    "Rowing",
    "VirtualRow",
    "Canoeing",
    "Kayaking",
    "StandUpPaddling",
    "NordicSki",
    "RollerSki",
    "Snowshoe",
    "IceSkate",
    "InlineSkate",
    "Elliptical",
    "StairStepper",
}

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
_TARGET_TYPES = {"AUTO", "POWER", "HR", "PACE"}


def intervals_workout_sport(value: Any) -> str:
    """Return the provider's canonical activity type for workout payloads."""
    raw = str(value or "Ride").strip()
    normalized = re.sub(r"[\s_-]+", " ", raw.casefold())
    canonical = INTERVALS_WORKOUT_SPORTS.get(
        raw.casefold()
    ) or INTERVALS_WORKOUT_SPORTS.get(normalized)
    if canonical:
        return canonical
    for activity_type in INTERVALS_WORKOUT_TYPES:
        if activity_type.casefold() == raw.casefold():
            return activity_type
    return "Other"


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
                "Trainingsschritte mit '- ' muessen direkt mit Dauer oder Distanz beginnen "
                "(z.B. '- 6km Z1 HR'). Hinweise, Bedingungen und optionale Gesamtstrecken "
                "als eigenen Absatz ohne '- ' schreiben; sonst zaehlt Intervals.icu sie als weitere Schritte.",
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
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def validate_workout_description(workout: dict[str, Any]) -> float | None:
    """Require quantity-first endurance steps; never guess intent from prose."""
    sport = intervals_workout_sport(workout.get("sport") or workout.get("type"))
    if sport not in INTERVALS_ENDURANCE_WORKOUT_TYPES:
        return
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


def workout_event_payload(
    workout_id: str, workout: dict[str, Any], *, today: date
) -> dict[str, Any]:
    structured_seconds = validate_workout_description(workout)
    try:
        workout_date = date.fromisoformat(str(workout["date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AppError(
            400, "Das Trainingsdatum muss das Format JJJJ-MM-TT haben."
        ) from exc
    if workout_date < today - timedelta(days=1):
        raise AppError(400, "Eine Einheit in der Vergangenheit wird nicht übertragen.")
    duration = int(workout.get("duration_minutes", 0))
    if duration < 5 or duration > 600:
        raise AppError(
            400, "Die Trainingsdauer muss zwischen 5 und 600 Minuten liegen."
        )
    return {
        "category": "WORKOUT",
        "start_date_local": str(
            workout.get("start_date_local") or workout_date.isoformat() + "T00:00:00"
        )[:40],
        "type": intervals_workout_sport(workout.get("sport") or workout.get("type")),
        "name": str(workout.get("name") or "Coach workout")[:200],
        "description": str(workout.get("description") or "")[:12000],
        "moving_time": round(structured_seconds)
        if structured_seconds is not None
        else duration * 60,
        "target": workout.get("target")
        if workout.get("target") in _TARGET_TYPES
        else "AUTO",
        "external_id": f"{COACH_EVENT_EXTERNAL_PREFIX}{workout_id}",
    }


def validate_intervals_workout_result(
    workout: dict[str, Any], remote: dict[str, Any]
) -> None:
    """A saved provider resource is only synced after its parsed structure agrees."""
    expected_sport = intervals_workout_sport(
        workout.get("sport") or workout.get("type")
    )
    if not isinstance(remote, dict) or remote.get("type") != expected_sport:
        raise AppError(
            502,
            "Intervals.icu hat die Sportart nicht korrekt bestaetigt.",
            reason="intervals_workout_sport_mismatch",
        )
    if expected_sport not in INTERVALS_ENDURANCE_WORKOUT_TYPES:
        return
    try:
        verify_workout_readback(str(workout.get("description") or ""), remote)
    except WorkoutTextError as exc:
        raise AppError(502, str(exc), reason=exc.reason) from exc


def normalize_workout(workout: Any, *, today: date) -> dict[str, Any]:
    if not isinstance(workout, dict):
        raise AppError(400, "Jede geplante Einheit muss ein Objekt sein.")
    sport = intervals_workout_sport(workout.get("sport"))
    draft = {
        "date": str(workout.get("date") or "").strip(),
        "sport": sport,
        "name": str(workout.get("name") or "Coach-Einheit").strip()[:200],
        "description": canonical_workout_zones(
            str(workout.get("description") or "").strip()[:12000],
            endurance=sport in INTERVALS_ENDURANCE_WORKOUT_TYPES,
        ),
        "duration_minutes": workout.get("duration_minutes"),
        "target": workout.get("target")
        if workout.get("target") in _TARGET_TYPES
        else "AUTO",
        "rationale": str(
            workout.get("rationale") or "Manuell geplante Einheit"
        ).strip()[:2000],
    }
    try:
        draft["duration_minutes"] = int(draft["duration_minutes"])
    except (TypeError, ValueError) as exc:
        raise AppError(400, "Die Trainingsdauer muss eine ganze Zahl sein.") from exc
    if not draft["description"]:
        raise AppError(400, "Jede geplante Einheit benötigt Workout-Text.")
    if not draft["rationale"]:
        raise AppError(400, "Jede geplante Einheit benötigt eine Begründung.")
    workout_event_payload("validation", draft, today=today)
    return draft
