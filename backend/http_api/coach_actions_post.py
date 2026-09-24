"""Authenticated Coach action confirmation and execution POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.proposals import (
    CoachProposalConfirmationService,
    CoachProposalExecutionService,
)


class CoachActionsPostRoutes:
    """Dispatch confirmed Coach action requests through their owning services."""

    def __init__(
        self,
        coach_proposal_confirmation_service: Callable[[], CoachProposalConfirmationService],
        coach_proposal_execution_service: Callable[[], CoachProposalExecutionService],
    ) -> None:
        self._coach_proposal_confirmation_service = coach_proposal_confirmation_service
        self._coach_proposal_execution_service = coach_proposal_execution_service

    def handle(self, handler: Any, path: str, session: dict[str, Any]) -> bool:
        if path == "/api/coach/actions/confirm":
            payload = handler.read_json()
            result = self._coach_proposal_confirmation_service().confirm(
                payload.get("proposal_id"), session["csrf_hash"]
            )
        elif path == "/api/coach/actions/execute":
            payload = handler.read_json()
            result = self._coach_proposal_execution_service().execute(
                payload.get("action_token"),
                session["csrf_hash"],
                payload.get("payload_hash"),
            )
        else:
            return False

        handler.send_json(200, result)
        return True
