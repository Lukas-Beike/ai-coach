"""Authorize structured Coach preview, apply, plan, and undo tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.authorization import (
    authorized_operations,
    require_coach_scope,
    structured_action_payload,
)
from backend.coach.proposals import CoachProposalCreationService
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError
from backend.history.undo_service import HistoryUndoService
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.training_plans import TrainingPlanService


class CoachPlanningActionToolService:
    """Own dispatch and Coach authorization for remaining structured tools."""

    def __init__(
        self,
        adaptive_preview_service: Callable[[], AdaptiveReplanPreviewService],
        adaptive_apply_service: Callable[[], CoachAdaptiveApplyService],
        training_plan_service: Callable[[], TrainingPlanService],
        history_undo_service: Callable[[], HistoryUndoService],
        proposal_creation_service: Callable[[], CoachProposalCreationService],
        training_plan_scope_prefix: str,
    ) -> None:
        self._adaptive_preview_service = adaptive_preview_service
        self._adaptive_apply_service = adaptive_apply_service
        self._training_plan_service = training_plan_service
        self._history_undo_service = history_undo_service
        self._proposal_creation_service = proposal_creation_service
        self._training_plan_scope_prefix = training_plan_scope_prefix

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        intent: dict[str, Any],
        client_turn_id: str,
        session_csrf_hash: str,
    ) -> dict[str, Any] | None:
        if name == "preview_adaptive_replan":
            if name not in authorized_operations(intent):
                raise AppError(
                    403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied"
                )
            require_coach_scope(intent, "adaptive_replan")
            return {"ok": True, **self._adaptive_preview_service().preview()}

        if name == "apply_adaptive_replan":
            return self._adaptive_apply_service().apply(
                arguments, intent, client_turn_id
            )

        if name == "update_training_plan":
            if name not in authorized_operations(intent):
                raise AppError(
                    403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied"
                )
            payload = structured_action_payload(arguments)
            plan_id = str(payload.get("plan_id") or "").strip()
            require_coach_scope(
                intent,
                f"{self._training_plan_scope_prefix}{plan_id}",
                "local_plan",
            )
            return {"ok": True, **self._training_plan_service().update(plan_id, payload)}

        if name == "undo_training_change":
            if name not in authorized_operations(intent):
                raise AppError(
                    403, STRUCTURED_AUTHORIZATION_ERROR, reason="intent_scope_denied"
                )
            change_id = str(arguments.get("change_id") or "").strip()
            require_coach_scope(intent, f"change:{change_id}")
            preview = self._history_undo_service().preview(change_id)
            proposal = self._proposal_creation_service().create(
                preview.pop("proposal"), session_csrf_hash
            )
            return {
                "ok": True,
                **preview,
                "proposed_action": proposal["proposed_action"],
            }

        return None
