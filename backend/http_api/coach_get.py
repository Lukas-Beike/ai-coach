"""Authenticated GET routes for Coach chat history, receipts, and status."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.http_api.auth import SessionAuthService
from backend.http_api.chat_page import ChatHistoryPageService


class CoachGetRoutes:
    """Dispatch Coach GET routes through their existing state owners."""

    def __init__(
        self,
        auth_service: Callable[[], SessionAuthService],
        chat_history_page_service: Callable[[], ChatHistoryPageService],
        coach_command_receipt_service: Callable[[], CoachCommandReceiptService],
        coach_job_submission_service: Callable[[], CoachJobSubmissionService],
    ) -> None:
        self._auth_service = auth_service
        self._chat_history_page_service = chat_history_page_service
        self._coach_command_receipt_service = coach_command_receipt_service
        self._coach_job_submission_service = coach_job_submission_service

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {"/api/chat/history", "/api/chat/receipt", "/api/chat/status"}:
            return False

        session = self._auth_service().require_auth(handler)
        if path == "/api/chat/history":
            query = parse_qs(urlparse(handler.path).query)
            payload = self._chat_history_page_service().page(
                query.get("cursor", [None])[0],
                query.get("limit", [None])[0],
                query.get("q", [None])[0],
                session_csrf_hash=session["csrf_hash"],
            )
        elif path == "/api/chat/receipt":
            query = parse_qs(urlparse(handler.path).query)
            payload = self._coach_command_receipt_service().read(
                query.get("client_turn_id", [None])[0], session["csrf_hash"]
            )
        else:
            payload = self._coach_job_submission_service().stream_status(
                session["csrf_hash"]
            )

        handler.send_json(200, payload)
        return True
