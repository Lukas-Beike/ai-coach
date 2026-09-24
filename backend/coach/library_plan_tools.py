"""Coach authorization for scheduling workout-library templates locally."""

from __future__ import annotations

from typing import Any

from backend.coach.authorization import authorized_operations, require_coach_scope
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.planning.library_plan_service import WorkoutLibraryPlanService


class CoachLibraryPlanToolService:
    """Authorize Coach requests before delegating to the atomic planning use case."""

    def __init__(self, library_plan_service: WorkoutLibraryPlanService) -> None:
        self._library_plan_service = library_plan_service

    def execute(self, arguments: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        if "apply_workout_library_plan" not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")
        entries = arguments.get("entries")
        if not isinstance(entries, list):
            raise AppError(
                400,
                "Bibliothekseinheiten müssen als Liste gesendet werden.",
                reason="invalid_library_plan",
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise AppError(
                    400,
                    "Jede Bibliothekseinheit muss ein Objekt sein.",
                    reason="invalid_library_plan",
                )
            local_id = str(entry.get("library_workout_id") or "").strip()
            require_coach_scope(intent, f"library_workout:{local_id}", "local_plan")
        return {
            "ok": True,
            "stored_locally": True,
            **self._library_plan_service.apply(entries),
        }
