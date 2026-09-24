"""Durable Coach chat submission and conversation reset POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.conversation import CoachConversationResetService
from backend.coach.job_submission import CoachJobSubmissionService
from backend.errors import AppError


class ChatPostRoutes:
    """Dispatch chat submission and reset requests through their services."""

    def __init__(
        self,
        coach_job_submission_service: Callable[[], CoachJobSubmissionService],
        coach_conversation_reset_service: Callable[[], CoachConversationResetService],
        max_request_bytes: int,
    ) -> None:
        self._coach_job_submission_service = coach_job_submission_service
        self._coach_conversation_reset_service = coach_conversation_reset_service
        self._max_request_bytes = max_request_bytes

    def handle(self, handler: Any, path: str, session: dict[str, Any]) -> bool:
        if path == "/api/chat":
            payload = handler.read_json(self._max_request_bytes)
            client_turn_id = str(payload.get("client_turn_id") or "").strip()
            if not client_turn_id:
                raise AppError(
                    400,
                    "client_turn_id ist für Coach-Nachrichten erforderlich.",
                    reason="invalid_client_turn",
                )
            result = self._coach_job_submission_service().enqueue(
                str(payload.get("message", "")),
                client_turn_id,
                session["csrf_hash"],
                request_kind=payload.get("request_kind"),
                attachments=payload.get("attachments"),
            )
            handler.send_json(202, result)
        elif path == "/api/chat/reset":
            handler.send_json(200, self._coach_conversation_reset_service().reset())
        else:
            return False
        return True
