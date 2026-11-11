"""Coach conversation reset POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.conversation import CoachConversationResetService
from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class ChatPostRoutes:
    """Dispatch the confirmed conversation reset through its service."""

    def __init__(
        self,
        coach_conversation_reset_service: Callable[[], CoachConversationResetService],
        max_request_bytes: int,
    ) -> None:
        self._coach_conversation_reset_service = coach_conversation_reset_service
        self._max_request_bytes = max_request_bytes

    def routes(self) -> list[Route]:
        return [Route("POST", "/api/chat/reset", Access.SESSION_CSRF, self._reset)]

    def _reset(self, handler: Any, _request: RouteRequest) -> None:
        payload = handler.read_json(self._max_request_bytes)
        if payload.get("confirmed") is not True:
            raise AppError(
                400,
                "Das Zurücksetzen muss bestätigt werden.",
                reason="confirmation_required",
            )
        handler.send_json(200, self._coach_conversation_reset_service().reset())
