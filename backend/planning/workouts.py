"""Normalize local workout drafts and validate Intervals.icu workout data.

This module is the planning facade for workouts. Validation lives in
``workout_validation``, the provider-neutral export model in ``workout_export``,
and the Intervals.icu catalog and payload mapping in
``backend.providers.intervals_workouts``. Names re-exported here keep existing
callers stable.
"""

from datetime import date, datetime
from typing import Any

from backend.activities.hr_cap_export import capped_description
from backend.activities.workout_text import (
    WorkoutTextError,
    canonical_workout_zones,
    verify_workout_readback,
)
from backend.canonical.planning_fields import SESSION_FOCUS_KEYS, TEMPLATE_ID
from backend.errors import AppError
from backend.planning.session_focus import normalize_session_focus
from backend.planning.sport import planned_stored_sport
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
    DERIVED_WORKOUT_KEYS,
    INTERVALS_DEFAULT_WORKOUT_TYPE,
    INTERVALS_ENDURANCE_WORKOUT_TYPES,
    INTERVALS_EVENT_CATEGORY,
    INTERVALS_NOTE_CATEGORY,
    INTERVALS_STRENGTH_TYPE,
    INTERVALS_WORKOUT_SPORTS,
    INTERVALS_WORKOUT_TYPES,
    intervals_event_payload,
    intervals_record_type,
    intervals_workout_sport,
)


def workout_event_payload(
    workout_id: str, workout: dict[str, Any], *, today: date
) -> dict[str, Any]:
    """Return the Intervals.icu event payload for one planned unit."""
    return intervals_event_payload(
        workout_id, build_planned_workout_export(workout, today=today)
    )


def library_sent_workout(workout: dict[str, Any]) -> dict[str, Any]:
    """The library entry as Intervals.icu receives it: the cap as percent of the LTHR.

    A library entry has no date to resolve a threshold HR on, so, like the Wahoo
    export, it carries the percent form. The stored description stays unchanged.
    """
    return {
        **workout,
        "description": capped_description(
            str(workout.get("description") or ""), workout, percent_basis=True
        ),
    }


def library_workout_payload(workout: dict[str, Any]) -> dict[str, Any]:
    validate_workout_description(workout)
    payload = {
        "name": str(workout.get("name") or "Coach-Einheit")[:200],
        "description": library_sent_workout(workout)["description"][:12000],
        "type": intervals_record_type(workout),
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
        **planned_stored_sport(workout).fields(),
        "name": workout.get("name") or "Bibliotheks-Einheit",
        "description": library_sent_workout(workout)["description"],
        "duration_minutes": workout.get("duration_minutes")
        or max(5, round(float(workout.get("planned_duration_s") or 3600) / 60)),
        "target": workout.get("target") or "AUTO",
    }
    return workout_event_payload(
        f"library-{workout_id}-{plan_date}", planned, today=today
    )


def validate_intervals_workout_result(
    workout: dict[str, Any], remote: dict[str, Any]
) -> None:
    """A saved provider resource is only synced after its parsed structure agrees."""
    expected_sport = intervals_record_type(workout)
    if not isinstance(remote, dict):
        raise AppError(
            502,
            "Intervals.icu hat die Sportart nicht korrekt bestätigt.",
            reason="intervals_workout_sport_mismatch",
        )
    if "category" in remote:
        # A calendar event: strength must come back as a note, so Intervals.icu
        # never forwards it to Garmin as one unnamed step.
        expected_category = (
            INTERVALS_NOTE_CATEGORY
            if expected_sport == INTERVALS_STRENGTH_TYPE
            else INTERVALS_EVENT_CATEGORY
        )
        if remote.get("category") != expected_category:
            raise AppError(
                502,
                "Intervals.icu hat die Kalenderkategorie nicht korrekt bestätigt.",
                reason="intervals_workout_category_mismatch",
            )
    # Intervals.icu may keep no type on a note; its category is checked above.
    note_without_type = remote.get("category") == INTERVALS_NOTE_CATEGORY and not (
        remote.get("type")
    )
    if remote.get("type") != expected_sport and not note_without_type:
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
    starts_at_local = value.strip()
    try:
        parsed_start = datetime.fromisoformat(starts_at_local)
    except ValueError as exc:
        raise AppError(400, message, reason="invalid_workout_start_date") from exc
    if (
        "T" not in starts_at_local.upper()
        or parsed_start.date().isoformat() != workout_date
    ):
        raise AppError(400, message, reason="invalid_workout_start_date")
    return starts_at_local[:40]


def normalize_workout(workout: Any, *, today: date) -> dict[str, Any]:
    if not isinstance(workout, dict):
        raise AppError(400, "Jede geplante Einheit muss ein Objekt sein.")
    sport = intervals_record_type(
        {
            "sport": workout.get("sport"),
            "environment": workout.get("environment"),
            "sport_detail": workout.get("sport_detail"),
        }
    )
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
    for key in SESSION_FOCUS_KEYS:
        if workout.get(key) is not None:
            draft[key] = workout[key]
    if workout.get(TEMPLATE_ID):
        draft[TEMPLATE_ID] = str(workout[TEMPLATE_ID]).strip()[:120]
    normalize_session_focus(draft)
    starts_at_local = workout.get("starts_at_local")
    if starts_at_local is not None:
        draft["starts_at_local"] = validate_workout_start_date(
            starts_at_local, str(draft["date"])
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
