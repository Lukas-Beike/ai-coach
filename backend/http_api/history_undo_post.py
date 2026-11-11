"""Authenticated local change-history undo POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.turn_undo import CoachTurnUndoService
from backend.history.undo_service import HistoryUndoService
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.session_load_response import with_session_load


class HistoryUndoPostRoutes:
    """Dispatch undo applications through their owning services."""

    def __init__(
        self,
        history_undo_service: Callable[[], HistoryUndoService],
        coach_turn_undo_service: CoachTurnUndoService,
        session_rpe_load: Callable[[str], Any] | None = None,
    ) -> None:
        self._history_undo_service = history_undo_service
        self._coach_turn_undo_service = coach_turn_undo_service
        self._session_rpe_load = session_rpe_load

    def routes(self) -> list[Route]:
        return [
            Route("POST", "/api/change-history/undo", Access.SESSION_CSRF, self._undo),
            Route(
                "POST",
                "/api/change-history/undo-turn",
                Access.SESSION_CSRF,
                self._undo_turn,
            ),
        ]

    def _undo(self, handler: Any, _request: RouteRequest) -> None:
        """Apply an undo from the change history."""
        payload = handler.read_json()
        result = self._history_undo_service().apply(payload)
        activity_id = payload.get("activity_id") if isinstance(payload, dict) else None
        if result.get("entity_type") == "activity_feedback" and isinstance(
            activity_id, str
        ):
            result = with_session_load(result, self._session_rpe_load, activity_id)
        handler.send_json(200, result)

    def _undo_turn(self, handler: Any, _request: RouteRequest) -> None:
        """Undo every tracked write of one Coach turn."""
        client_turn_id = handler.read_json().get("client_turn_id")
        handler.send_json(200, self._coach_turn_undo_service.undo(client_turn_id))
