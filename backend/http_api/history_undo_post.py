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
        """Apply an undo from the change history.

        Request: JSON body `{"change_id": string, "expected_current_hash": string,
        "activity_id": string}`. `change_id` is the change-history entry (36
        characters, `0-9`, `a-f`, `-`); `expected_current_hash` is the hash from the
        undo preview and is required, a missing or different one answers 409;
        `activity_id` is optional and only used for `activity_feedback` entries.

        Response: 200 `{"status": "undone", "change_id": string, "entity_type":
        string, "entity_id": string, "remote_untouched": true}`; for
        `activity_feedback` with a string `activity_id` also `session_rpe_load`
        (omitted if it cannot be read).

        Errors: 400 "Ungültige Änderungshistorie-ID."; 404 "Änderung nicht
        gefunden."; 409 "Eine Undo-Aktion kann nicht erneut zurückgenommen
        werden."; 400 "Ein Export an einen Anbieter lässt sich nicht zurücknehmen.";
        400 "Diese Änderung lässt sich nicht mehr zurücknehmen."; 409 "Die lokale
        Änderung wurde inzwischen weiter geändert; Undo wurde abgebrochen."; 400
        "Unbekannte lokale Änderung.".
        """
        payload = handler.read_json()
        result = self._history_undo_service().apply(payload)
        activity_id = payload.get("activity_id") if isinstance(payload, dict) else None
        if result.get("entity_type") == "activity_feedback" and isinstance(
            activity_id, str
        ):
            result = with_session_load(result, self._session_rpe_load, activity_id)
        handler.send_json(200, result)

    def _undo_turn(self, handler: Any, _request: RouteRequest) -> None:
        """Undo every tracked write of one Coach turn.

        Request: JSON body `{"client_turn_id": string}`, 1 to 120 characters.

        Response: 200 `{"status": "undone", "client_turn_id": string,
        "coach_changes": object, "remote_untouched": true}`; `coach_changes` is the
        turn's change summary with `undone_at` set. All changes are restored in one
        transaction or none.

        Errors: 400 "Ungültiger Coach-Auftrag."; 404 "Coach-Antwort nicht
        gefunden." for an unknown or unfinished turn; 409 "Diese Coach-Antwort hat
        nichts geändert."; 409 "Diese Coach-Änderungen wurden bereits
        zurückgenommen."; 409 "Diese Coach-Änderungen können nicht gesammelt
        zurückgenommen werden."; 409 "Die lokale Änderung wurde inzwischen weiter
        geändert; Undo wurde abgebrochen." when a record changed since the turn.
        """
        client_turn_id = handler.read_json().get("client_turn_id")
        handler.send_json(200, self._coach_turn_undo_service.undo(client_turn_id))
