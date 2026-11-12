"""Authenticated streaming chat cancellation POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.cancellation import CoachCancellationService
from backend.http_api.route_table import Access, Route, RouteRequest


class ChatCancelPostRoutes:
    """Dispatch streaming chat cancellation outside the maintenance gate."""

    def __init__(
        self,
        coach_cancellation_service: Callable[[], CoachCancellationService],
    ) -> None:
        self._coach_cancellation_service = coach_cancellation_service

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/chat/cancel",
                Access.SESSION_CSRF,
                self._cancel,
                gated=False,
            )
        ]

    def _cancel(self, handler: Any, request: RouteRequest) -> None:
        """Cancel running Coach work of this session.

        Request: JSON body `{"operation_id": string}`; `operation_id` is optional
        and names the attached stream or background turn to cancel.

        Response: 200 `{"status": "cancelling", "operation_id": string}` when
        running work of this session was signalled, `{"status": "not_running"}`
        when there is none.

        Errors: 409 "Die angegebene Coach-Anfrage ist nicht mehr aktiv." when
        `operation_id` differs from the attached stream's.

        The route is not held back by maintenance mode.
        """
        payload = handler.read_json()
        result = self._coach_cancellation_service().cancel(
            request.session["csrf_hash"], payload.get("operation_id")
        )
        handler.send_json(200, result)
