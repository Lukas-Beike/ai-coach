"""Authenticated Coach planning command POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.conversation import CoachConversationProvisionService
from backend.coach.planning_commands import CoachPlanningCommandService


class PlanningCommandsPostRoutes:
    """Dispatch planning command execution through its Coach service."""

    def __init__(
        self,
        coach_planning_command_service: Callable[[], CoachPlanningCommandService],
        coach_conversation_provision_service: Callable[[], CoachConversationProvisionService],
    ) -> None:
        self._coach_planning_command_service = coach_planning_command_service
        self._coach_conversation_provision_service = coach_conversation_provision_service

    def handle(self, handler: Any, path: str, session: dict[str, Any]) -> bool:
        if path != "/api/planning/commands":
            return False

        payload = handler.read_json()
        conversation_id = self._coach_conversation_provision_service().ensure()
        result = self._coach_planning_command_service().execute(
            payload,
            conversation_id=conversation_id,
            session_csrf_hash=session["csrf_hash"],
        )
        handler.send_json(200, result)
        return True
