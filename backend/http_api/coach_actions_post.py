"""Authenticated Coach action confirmation and execution POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_read import CoachProposalConfirmationService
from backend.http_api.route_table import Access, Route, RouteRequest


class CoachActionsPostRoutes:
    """Dispatch confirmed Coach action requests through their owning services."""

    def __init__(
        self,
        coach_proposal_confirmation_service: Callable[
            [], CoachProposalConfirmationService
        ],
        coach_proposal_execution_service: Callable[[], CoachProposalExecutionService],
    ) -> None:
        self._coach_proposal_confirmation_service = coach_proposal_confirmation_service
        self._coach_proposal_execution_service = coach_proposal_execution_service

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST", "/api/coach/actions/confirm", Access.SESSION_CSRF, self._confirm
            ),
            Route(
                "POST", "/api/coach/actions/cancel", Access.SESSION_CSRF, self._cancel
            ),
            Route(
                "POST", "/api/coach/actions/execute", Access.SESSION_CSRF, self._execute
            ),
        ]

    def _confirm(self, handler: Any, request: RouteRequest) -> None:
        """Confirm a Coach proposal."""
        payload = handler.read_json()
        handler.send_json(
            200,
            self._coach_proposal_confirmation_service().confirm(
                payload.get("proposal_id"), request.session["csrf_hash"]
            ),
        )

    def _cancel(self, handler: Any, request: RouteRequest) -> None:
        """Cancel a Coach proposal."""
        payload = handler.read_json()
        handler.send_json(
            200,
            self._coach_proposal_confirmation_service().cancel(
                payload.get("proposal_id"), request.session["csrf_hash"]
            ),
        )

    def _execute(self, handler: Any, request: RouteRequest) -> None:
        """Execute a confirmed Coach proposal."""
        payload = handler.read_json()
        handler.send_json(
            200,
            self._coach_proposal_execution_service().execute(
                payload.get("action_token"),
                request.session["csrf_hash"],
                payload.get("payload_hash"),
            ),
        )
