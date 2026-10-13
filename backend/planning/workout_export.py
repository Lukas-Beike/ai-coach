"""Build the provider-neutral export model for one planned workout.

Validation and date/duration rules run here, in the same order as before the
export port existed, so every caller sees the same errors.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.canonical.planned_workout import PlannedWorkoutExport
from backend.canonical.stored_sports import WORKOUT_SPORT_TOKENS, StoredSport
from backend.errors import AppError
from backend.planning.sport import planned_stored_sport
from backend.planning.workout_validation import validate_workout_description

WORKOUT_TARGET_TYPES = frozenset({"AUTO", "POWER", "HR", "PACE"})


def build_planned_workout_export(
    workout: dict[str, Any], *, today: date
) -> PlannedWorkoutExport:
    """Validate one planned unit and derive its provider-neutral export values."""
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
    stored = planned_stored_sport(workout)
    return PlannedWorkoutExport(
        start_date_local=str(
            workout.get("start_date_local") or workout_date.isoformat() + "T00:00:00"
        )[:40],
        sport=stored.sport,
        environment=stored.environment,
        sport_token=_export_sport_token(workout, stored),
        name=str(workout.get("name") or "Coach workout")[:200],
        description=str(workout.get("description") or "")[:12000],
        duration_seconds=round(structured_seconds)
        if structured_seconds is not None
        else duration * 60,
        target=planned_target(workout.get("target")),
    )


def _export_sport_token(workout: dict[str, Any], stored: StoredSport) -> str:
    """Return the legacy sport text that refines the canonical pair, or ``""``."""
    if stored.detail:
        return stored.detail
    raw = str(workout.get("sport") or workout.get("type") or "").strip()
    return raw if raw in WORKOUT_SPORT_TOKENS else ""


def planned_target(value: Any) -> str:
    return value if value in WORKOUT_TARGET_TYPES else "AUTO"
