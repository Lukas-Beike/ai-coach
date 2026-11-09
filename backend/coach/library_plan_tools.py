"""Coach authorization for scheduling workout-library templates locally."""

from __future__ import annotations

from typing import Any

from backend.coach.authorization import authorized_operations, require_coach_scope
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.planning import plan_checks, run_hr_cap
from backend.planning.library_plan_service import WorkoutLibraryPlanService


def require_complete_template(template_id: str, template: dict[str, Any]) -> None:
    """Reject a template whose units would miss data the plan guard requires.

    The tool takes only an id and a date, so the Coach cannot supply the
    missing focus, strength structure or heart-rate cap here: it must complete
    the template first.
    """
    missing = [
        field
        for item in plan_checks.strength_incomplete([template])
        for field in item["evidence"]["missing"]
    ]
    if plan_checks.focus_missing([template]):
        missing.append("session_focus")
    if run_hr_cap.capped_focus(template) and template.get("hr_cap") is None:
        missing.append("hr_cap")
    if missing:
        name = str(template.get("name") or "Vorlage")
        raise AppError(
            409,
            f"Vorlage „{name}“ ({template_id}) fehlt: {', '.join(missing)}. "
            "Zuerst die Vorlage mit manage_training_templates ergänzen, dann "
            "erneut einplanen.",
            reason="library_template_incomplete",
        )


class CoachLibraryPlanToolService:
    """Authorize Coach requests before delegating to the atomic planning use case."""

    def __init__(self, library_plan_service: WorkoutLibraryPlanService) -> None:
        self._library_plan_service = library_plan_service

    def execute(
        self, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any]:
        if "apply_workout_library_plan" not in authorized_operations(intent):
            raise AppError(
                403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied"
            )
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
            **self._library_plan_service.apply(
                entries, check_template=require_complete_template
            ),
        }
