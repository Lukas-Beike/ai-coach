"""Authorize structured Coach planning mutation tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.authorization import (
    authorized_operations,
    require_coach_scope,
    scope_values,
)
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.planning.changes import StructuredTrainingChangeService
from backend.planning.replacement_service import (
    StructuredTrainingPlanReplacementService,
)


class CoachPlanningChangeToolService:
    """Own Coach operation and object-scope checks for plan mutations."""

    def __init__(
        self,
        plan_replacement_service: Callable[[], StructuredTrainingPlanReplacementService],
        training_change_service: Callable[[], StructuredTrainingChangeService],
        training_plan_scope_prefix: str,
    ) -> None:
        self._plan_replacement_service = plan_replacement_service
        self._training_change_service = training_change_service
        self._training_plan_scope_prefix = training_plan_scope_prefix

    def execute(
        self, name: str, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any] | None:
        if name not in {"replace_training_plan", "apply_training_changes"}:
            return None

        if name == "replace_training_plan":
            return self._replace_training_plan(arguments, intent)
        return self._apply_training_changes(arguments, intent)

    def _replace_training_plan(
        self, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any]:
        if "replace_training_plan" not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")

        selected_plan_ids = self._selected_plan_ids(intent)
        if len(selected_plan_ids) > 1:
            raise AppError(
                400,
                "Ein Planersatz darf nur einen konkret benannten Trainingsplan auswählen.",
                reason="intent_scope_denied",
            )
        if not selected_plan_ids and "local_plan" not in scope_values(intent):
            raise AppError(
                403,
                "Die strukturierte Coach-Autorisierung umfasst diesen Plan nicht.",
                reason="intent_scope_denied",
            )

        return self._plan_replacement_service().replace(
            {
                **arguments,
                "period": intent.get("period"),
                "constraints": (intent.get("request") or {}).get("constraints", []),
            },
            selected_plan_id=selected_plan_ids[0] if selected_plan_ids else None,
        )

    def _apply_training_changes(
        self, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any]:
        if "apply_training_changes" not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")

        changes = arguments.get("changes")
        if not isinstance(changes, list):
            raise AppError(
                400,
                "Coach-Änderungen müssen als Liste gesendet werden.",
                reason="invalid_change",
            )

        selected_plan_ids = self._selected_plan_ids(intent)
        if len(selected_plan_ids) > 1:
            raise AppError(
                400,
                "Die Änderungen dürfen nur einen konkret benannten Trainingsplan auswählen.",
                reason="intent_scope_denied",
            )
        self._validate_training_change_scopes(changes, intent, selected_plan_ids)
        return self._training_change_service().apply(
            arguments,
            require_revision=bool(intent.get("bulk_change")),
            authorized_plan_id=selected_plan_ids[0] if selected_plan_ids else None,
        )

    def _selected_plan_ids(self, intent: dict[str, Any]) -> list[str]:
        scope_prefix = self._training_plan_scope_prefix
        return sorted(
            token.split(":", 1)[1]
            for token in scope_values(intent)
            if token.startswith(scope_prefix) and token.split(":", 1)[1]
        )

    def _validate_training_change_scopes(
        self,
        changes: list[Any],
        intent: dict[str, Any],
        selected_plan_ids: list[str],
    ) -> None:
        for change in changes:
            if not isinstance(change, dict):
                continue
            action = str(change.get("action") or "update").strip().casefold()
            if action == "create":
                require_coach_scope(intent, "local_plan", "local_plan_create")
                requested_plan_id = str(change.get("plan_id") or "").strip()
                if requested_plan_id and requested_plan_id not in selected_plan_ids:
                    raise AppError(
                        403,
                        "Die neue Einheit darf nur dem benannten Trainingsplan zugeordnet werden.",
                        reason="intent_scope_denied",
                    )
            elif change.get("local_id"):
                local_id = str(change["local_id"]).strip()
                allowed_scopes = (f"planned_unit:{local_id}",)
                if "local_plan_create" not in scope_values(intent):
                    allowed_scopes += ("local_plan",)
                require_coach_scope(intent, *allowed_scopes)
