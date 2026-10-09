"""Preparation and validation for complete structured plan replacements."""

from datetime import date
from typing import Any

from backend.athlete.local_date import LocalDate
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
        revision = arguments.get("expected_revision")
        if revision is None:
            raise ValueError("missing planning revision")
        expected_revision = int(revision)
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
    """Reject past, out-of-period, or overlapping-time workouts in a replacement."""
    from backend.planning.conflicts import calendar_items_conflict

    for i, workout in enumerate(workouts):
        try:
            workout_date = LocalDate.parse(workout.get("date")).isoformat()
        except (TypeError, ValueError) as exc:
            raise AppError(
                400,
                "Ein vollständiger Planersatz darf keine ungültigen Einheiten enthalten.",
                reason="invalid_plan",
            ) from exc
        if workout_date < today or not period["start"] <= workout_date <= period["end"]:
            raise AppError(
                400,
                "Ein vollständiger Planersatz darf keine vergangenen Einheiten enthalten.",
                reason="invalid_plan",
            )
        for other in workouts[i + 1 :]:
            matches, match = calendar_items_conflict(workout, other)
            if matches and match == "time_window":
                raise AppError(
                    409,
                    f"Der Plan enthält zeitlich überschneidende Einheiten für den {workout_date}.",
                    reason="plan_date_conflict",
                )
