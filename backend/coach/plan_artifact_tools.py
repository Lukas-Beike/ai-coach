"""Authorize Coach plan-artifact tools before entering planning services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.authorization import authorized_operations, require_coach_scope
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService


class CoachPlanArtifactToolService:
    """Own operation and artifact-scope checks for stage and commit tools."""

    def __init__(
        self, training_plan_artifact_service: Callable[[], TrainingPlanArtifactService]
    ) -> None:
        self._training_plan_artifact_service = training_plan_artifact_service

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        intent: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
    ) -> dict[str, Any] | None:
        if name not in {"stage_training_plan", "commit_training_plan"}:
            return None

        if name not in authorized_operations(intent):
            raise AppError(403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied")

        if name == "stage_training_plan":
            require_coach_scope(intent, "local_plan")
            return self._training_plan_artifact_service().stage(
                arguments, conversation_id, client_turn_id
            )

        artifact_id = str(intent.get("artifact_id") or "").strip()
        if not artifact_id:
            raise AppError(
                400,
                "Zum Speichern wird ein lokales Planartefakt benötigt.",
                reason="artifact_required",
            )
        if str(arguments.get("artifact_id") or artifact_id).strip() != artifact_id:
            raise AppError(
                403,
                "Das Planartefakt stimmt nicht mit der klassifizierten Aktion überein.",
                reason="intent_scope_denied",
            )
        require_coach_scope(intent, f"artifact:{artifact_id}")
        return self._training_plan_artifact_service().commit(
            artifact_id,
            conversation_id,
            explicit_artifact=bool(intent.get("_artifact_explicit")),
        )
