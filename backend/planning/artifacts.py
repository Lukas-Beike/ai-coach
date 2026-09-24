"""Validation for structured Coach plan artifacts."""

from datetime import date
from typing import Any

from backend.errors import AppError


def structured_artifact_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a structured plan artifact payload or report a missing payload."""
    payload = arguments.get("payload")
    if isinstance(payload, dict):
        return payload
    raise AppError(400, "Ein Planartefakt benoetigt payload.", reason="invalid_plan")


def validate_structured_plan_limits(payload: dict[str, Any]) -> None:
    """Validate the size, shape, and date span of a structured plan."""
    workouts = payload.get("workouts")
    if not isinstance(workouts, list) or not workouts:
        raise AppError(
            400,
            "Ein Planartefakt benötigt mindestens eine Einheit.",
            reason="plan_limit",
        )
    if len(workouts) > 366:
        raise AppError(
            400,
            "Ein Planartefakt darf höchstens 366 Einheiten enthalten.",
            reason="plan_limit",
        )

    dates = []
    for workout in workouts:
        if not isinstance(workout, dict):
            raise AppError(
                400,
                "Jede Planeinheit muss ein Objekt sein.",
                reason="invalid_plan",
            )
        try:
            dates.append(date.fromisoformat(str(workout.get("date") or "")[:10]))
        except (TypeError, ValueError) as exc:
            raise AppError(
                400,
                "Jede Planeinheit benötigt ein gültiges Datum.",
                reason="invalid_plan",
            ) from exc

    if dates and (max(dates) - min(dates)).days > 730:
        raise AppError(
            400,
            "Ein Planartefakt darf höchstens 730 Tage umfassen.",
            reason="plan_limit",
        )
