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
        """Coach conversation history page, optionally searched.

        Request: query `cursor` (optional, the `next_cursor` of the previous page),
        `limit` (optional, default 100, clamped to 1..100) and `q` (optional search
        text, trimmed to 200 characters, substring match on the message content).
        No body.

        Response: 200 with `generation` (chat generation, changes on a reset),
        `messages` (one page, oldest first, going back from the cursor; each has
        `id`, `role`, `content`, `created_at` and, when present, `client_turn_id`,
        `attachment_names`, `coach_changes`, `coach_failed`, `coach_request_kind`),
        `proposed_actions` (this session's open Coach proposals, at most 30),
        `next_cursor` (null on the last page), `limit` and `search`.

        Errors: 400 `invalid_page_cursor` "Ungültiger Cursor." when `cursor` is not
        a cursor this route returned.
        """
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
        """Receipt of one Coach turn.

        Request: query `client_turn_id` (required, 1 to 120 characters). No body.

        Response: 200 with the stored receipt of that turn of this session, without
        its `session_key`: fields such as `status`, `mode`, `phase`, `operation_id`,
        `plan_scope`, `model`, `command_receipts` and `change_summary`, plus
        `client_turn_id` and `proposed_actions` (the turn's proposals as stored now,
        `status` `expired` once past `expires_at`).

        Errors: 400 `invalid_client_turn` "Ungültige Coach-Auftragskennung." when
        `client_turn_id` is missing or longer than 120 characters; 404
        `command_not_found` "Coach-Auftrag nicht gefunden."; 403
        `command_scope_denied` "Dieser Coach-Auftrag gehört zu einer anderen
        Sitzung." when another session started the turn.
        """
        handler.send_json(
            200,
            self._coach_command_receipt_service().read(
                request.query.get("client_turn_id", [None])[0],
                request.session["csrf_hash"],
            ),
        )

    def _status(self, handler: Any, request: RouteRequest) -> None:
        """Status of this session's Coach work.

        Request: no query, no body.

        Response: 200 `{"status": "idle", "operation_id": null}` without Coach
        work; `{"status": "running", "operation_id": string}` while a stream is
        attached; for a durable background turn also `mode` `background`, `phase`
        and `plan_scope`.

        Errors: none beyond the common ones.
        """
        handler.send_json(
            200,
            self._coach_job_submission_service().stream_status(
                request.session["csrf_hash"]
            ),
        )
