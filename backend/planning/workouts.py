"""Normalize local workout drafts and validate Intervals.icu workout data.

This module is the planning facade for workouts. Validation lives in
``workout_validation``, the provider-neutral export model in ``workout_export``,
and the Intervals.icu catalog and payload mapping in
``backend.providers.intervals_workouts``. Names re-exported here keep existing
callers stable.
"""

from datetime import date, datetime
from typing import Any

from backend.activities.workout_text import (
    WorkoutTextError,
    canonical_workout_zones,
    verify_workout_readback,
)
from backend.errors import AppError
from backend.planning.workout_export import (
    build_planned_workout_export,
    planned_target,
)
from backend.planning.workout_validation import (  # noqa: F401
    WORKOUT_STEP_QUANTITY,
    WORKOUT_STEP_QUANTITY_UNITS,
    WORKOUT_STEP_TIME_UNITS,
    _is_composite_duration,
    _raise_ambiguous_workout_step,
    _structured_workout_duration,
    _validate_endurance_workout_steps,
    _validate_workout_duration_match,
    _workout_step_amounts,
    validate_workout_description,
)
from backend.providers.intervals_workouts import (  # noqa: F401
    COACH_EVENT_EXTERNAL_PREFIX,
    INTERVALS_DEFAULT_WORKOUT_TYPE,
    INTERVALS_ENDURANCE_WORKOUT_TYPES,
    INTERVALS_WORKOUT_SPORTS,
    INTERVALS_WORKOUT_TYPES,
    intervals_event_payload,
    intervals_workout_sport,
)


def workout_event_payload(
    workout_id: str, workout: dict[str, Any], *, today: date
) -> dict[str, Any]:
    """Return the Intervals.icu event payload for one planned unit."""
    return intervals_event_payload(
        workout_id, build_planned_workout_export(workout, today=today)
    )


def library_workout_payload(workout: dict[str, Any]) -> dict[str, Any]:
    validate_workout_description(workout)
    payload = {
        "name": str(workout.get("name") or "Coach-Einheit")[:200],
        "description": str(workout.get("description") or "")[:12000],
        "type": intervals_workout_sport(workout.get("type") or workout.get("sport")),
        "target": workout.get("target") or "AUTO",
    }
    if workout.get("folder_id") is not None:
        payload["folder_id"] = workout["folder_id"]
    return payload


def library_workout_event_payload(
    workout_id: str,
    workout: dict[str, Any],
    plan_date: str,
    *,
    today: date,
) -> dict[str, Any]:
    planned = {
        "date": plan_date,
        "sport": workout.get("type")
        or workout.get("sport")
        or INTERVALS_DEFAULT_WORKOUT_TYPE,
        "name": workout.get("name") or "Bibliotheks-Einheit",
        "description": workout.get("description") or "",
        "duration_minutes": workout.get("duration_minutes")
        or max(5, round(float(workout.get("moving_time") or 3600) / 60)),
        "target": workout.get("target") or "AUTO",
    }
    return workout_event_payload(
        f"library-{workout_id}-{plan_date}", planned, today=today
    )


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
            "Intervals.icu hat die Sportart nicht korrekt bestätigt.",
            reason="intervals_workout_sport_mismatch",
        )
    if expected_sport not in INTERVALS_ENDURANCE_WORKOUT_TYPES:
        return
    try:
        verify_workout_readback(str(workout.get("description") or ""), remote)
    except WorkoutTextError as exc:
        raise AppError(502, str(exc), reason=exc.reason) from exc


def validate_workout_start_date(value: Any, workout_date: str) -> str:
    message = (
        "Die lokale Startzeit muss ein ISO-8601-Zeitstempel am Trainingsdatum sein."
    )
    if not isinstance(value, str):
        raise AppError(400, message, reason="invalid_workout_start_date")
    start_date_local = value.strip()
    try:
        parsed_start = datetime.fromisoformat(start_date_local)
    except ValueError as exc:
        raise AppError(400, message, reason="invalid_workout_start_date") from exc
    if (
        "T" not in start_date_local.upper()
        or parsed_start.date().isoformat() != workout_date
    ):
        raise AppError(400, message, reason="invalid_workout_start_date")
    return start_date_local[:40]


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
        "target": planned_target(workout.get("target")),
        "rationale": str(
            workout.get("rationale") or "Manuell geplante Einheit"
        ).strip()[:2000],
    }
    start_date_local = workout.get("start_date_local")
    if start_date_local is not None:
        draft["start_date_local"] = validate_workout_start_date(
            start_date_local, str(draft["date"])
        )
    try:
        draft["duration_minutes"] = int(str(draft["duration_minutes"]))
    except (TypeError, ValueError) as exc:
        raise AppError(400, "Die Trainingsdauer muss eine ganze Zahl sein.") from exc
    if not draft["description"]:
        raise AppError(400, "Jede geplante Einheit benötigt Workout-Text.")
    if not draft["rationale"]:
        raise AppError(400, "Jede geplante Einheit benötigt eine Begründung.")
    workout_event_payload("validation", draft, today=today)
    return draft
