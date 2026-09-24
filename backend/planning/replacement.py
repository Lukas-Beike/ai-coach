"""Preparation and validation for complete structured plan replacements."""

from datetime import date
from typing import Any

from backend.errors import AppError
from backend.planning.artifacts import (
    structured_artifact_payload,
    validate_structured_plan_limits,
)
from backend.planning.workouts import normalize_workout


def prepare_structured_plan_replacement(
    arguments: dict[str, Any], *, today: date
) -> tuple[dict[str, Any], int, list[dict[str, Any]], str, str, dict[str, str]]:
    """Validate and normalize a full structured plan replacement request."""
    payload = structured_artifact_payload(arguments)
    validate_structured_plan_limits(payload)
    try:
        expected_revision = int(arguments.get("expected_revision"))
    except (TypeError, ValueError) as exc:
        raise AppError(
            400,
            "Ein vollständiger Planersatz benötigt die gelesene Planrevision.",
            reason="planning_revision_required",
        ) from exc
    workouts = [
        normalize_workout(workout, today=today) for workout in payload["workouts"]
    ]
    plan_name = str(payload.get("plan_name") or "").strip()[:200]
    if not plan_name:
        raise AppError(
            400,
            "Ein vollständiger Planersatz benötigt einen Namen.",
            reason="invalid_plan",
        )
    today_text = today.isoformat()
    period = arguments.get("period") or {"start": today_text, "end": "9999-12-31"}
    validate_replacement_workouts(workouts, today_text, period)
    return payload, expected_revision, workouts, plan_name, today_text, period


def validate_replacement_workouts(
    workouts: list[dict[str, Any]], today: str, period: dict[str, str]
) -> None:
    """Reject past, out-of-period, or duplicate-day workouts in a replacement."""
    dates: set[str] = set()
    for workout in workouts:
        workout_date = str(workout.get("date") or "")[:10]
        if workout_date < today or not period["start"] <= workout_date <= period["end"]:
            raise AppError(
                400,
                "Ein vollständiger Planersatz darf keine vergangenen Einheiten enthalten.",
                reason="invalid_plan",
            )
        if workout_date in dates:
            raise AppError(
                409,
                f"Der Plan enthält mehrere Einheiten für den {workout_date}; pro Tag ist eine Einheit möglich.",
                reason="plan_date_conflict",
            )
        dates.add(workout_date)
