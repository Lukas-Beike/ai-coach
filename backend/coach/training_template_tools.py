"""Local Coach operations for reusable training templates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.authorization import authorized_operations, require_coach_scope
from backend.db.manager import DatabaseManager
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError


class TrainingTemplateToolService:
    """Execute authorized template changes as one local database transaction."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        workout_library_service: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._workout_library_service = workout_library_service

    def execute(self, arguments: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        if "manage_training_templates" not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")

        templates = arguments.get("templates")
        if (
            not isinstance(templates, list)
            or not 1 <= len(templates) <= 28
            or not all(isinstance(item, dict) for item in templates)
        ):
            raise AppError(
                400,
                "Ein Coach-Kommando darf 1 bis 28 Vorlagenänderungen enthalten.",
                reason="template_limit",
            )

        actions: list[tuple[str, str]] = []
        for template in templates:
            action = str(template.get("action") or "create").strip().casefold()
            if action in {"update", "archive", "restore", "delete"}:
                local_id = str(template.get("local_id") or "").strip()
                require_coach_scope(intent, f"library_workout:{local_id}", "local_template")
            elif action == "create":
                local_id = ""
                require_coach_scope(intent, "local_template")
            else:
                raise AppError(
                    400,
                    "Unbekannte Aktion für die Bibliothekseinheit.",
                    reason="invalid_template_action",
                )
            actions.append((action, local_id))

        # Restore may replace the active manager. Resolve both dependencies only
        # after acquiring the shared lock, then keep every nested library write
        # inside the same manager-owned unit of work.
        with self._database_lock:
            manager = self._database_manager()
            library = self._workout_library_service()
            with manager.unit_of_work():
                results = []
                for template, (action, local_id) in zip(templates, actions, strict=True):
                    if action == "create":
                        results.append(library.create_template(template))
                    else:
                        results.append(library.update(local_id, template))

        return {
            "ok": True,
            "stored_locally": True,
            "templates": results,
            "template": results[0] if len(results) == 1 else None,
        }


def training_template_tool_service(
    database_manager: Callable[[], DatabaseManager],
    database_lock: Any,
    workout_library_service: Callable[[], Any],
) -> TrainingTemplateToolService:
    """Build an uncached operation service from current composition-root factories."""
    return TrainingTemplateToolService(
        database_manager, database_lock, workout_library_service
    )
