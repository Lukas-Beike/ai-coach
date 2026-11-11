"""Authenticated GET routes for Coach chat history, receipts, and status."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.route_table import Access, Route, RouteRequest


class CoachGetRoutes:
    """Dispatch Coach GET routes through their existing state owners."""

    def __init__(
        self,
        chat_history_page_service: Callable[[], ChatHistoryPageService],
        coach_command_receipt_service: Callable[[], CoachCommandReceiptService],
        coach_job_submission_service: Callable[[], CoachJobSubmissionService],
    ) -> None:
        self._chat_history_page_service = chat_history_page_service
        self._coach_command_receipt_service = coach_command_receipt_service
        self._coach_job_submission_service = coach_job_submission_service

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/chat/history", Access.SESSION, self._history),
            Route("GET", "/api/chat/receipt", Access.SESSION, self._receipt),
            Route("GET", "/api/chat/status", Access.SESSION, self._status),
        ]

    def _history(self, handler: Any, request: RouteRequest) -> None:
        query = request.query
        handler.send_json(
            200,
            self._chat_history_page_service().page(
                query.get("cursor", [None])[0],
                query.get("limit", [None])[0],
                query.get("q", [None])[0],
                session_csrf_hash=request.session["csrf_hash"],
            ),
        )

    def _receipt(self, handler: Any, request: RouteRequest) -> None:
        handler.send_json(
            200,
            self._coach_command_receipt_service().read(
                request.query.get("client_turn_id", [None])[0],
                request.session["csrf_hash"],
            ),
        )

    def _status(self, handler: Any, request: RouteRequest) -> None:
        handler.send_json(
            200,
            self._coach_job_submission_service().stream_status(
                request.session["csrf_hash"]
            ),
        )
