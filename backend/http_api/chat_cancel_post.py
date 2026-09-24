"""Authenticated streaming chat cancellation POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.cancellation import CoachCancellationService


class ChatCancelPostRoutes:
    """Dispatch streaming chat cancellation outside the maintenance gate."""

    def __init__(
        self,
        coach_cancellation_service: Callable[[], CoachCancellationService],
    ) -> None:
        self._coach_cancellation_service = coach_cancellation_service

    def handle(self, handler: Any, path: str, session: dict[str, Any]) -> bool:
        if path != "/api/chat/cancel":
            return False

        payload = handler.read_json()
        result = self._coach_cancellation_service().cancel(
            session["csrf_hash"], payload.get("operation_id")
        )
        handler.send_json(200, result)
        return True
