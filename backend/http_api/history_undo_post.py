"""Authenticated local change-history undo POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.turn_undo import CoachTurnUndoService
from backend.history.undo_service import HistoryUndoService


class HistoryUndoPostRoutes:
    """Dispatch undo previews and applications through their owning services."""

    def __init__(
        self,
        history_undo_service: Callable[[], HistoryUndoService],
        coach_proposal_creation_service: Callable[[], CoachProposalCreationService],
        coach_turn_undo_service: CoachTurnUndoService,
        session_rpe_load: Callable[[str], Any] | None = None,
    ) -> None:
        self._history_undo_service = history_undo_service
        self._coach_proposal_creation_service = coach_proposal_creation_service
        self._coach_turn_undo_service = coach_turn_undo_service
        self._session_rpe_load = session_rpe_load

    def handle(self, handler: Any, path: str, session: dict[str, Any]) -> bool:
        if path == "/api/change-history/undo/preview":
            preview = self._history_undo_service().preview(
                handler.read_json().get("change_id")
            )
            proposal = self._coach_proposal_creation_service().create(
                preview.pop("proposal"), session["csrf_hash"]
            )
            handler.send_json(
                200,
                {**preview, "proposed_action": proposal["proposed_action"]},
            )
        elif path == "/api/change-history/undo":
            payload = handler.read_json()
            result = self._history_undo_service().apply(payload)
            activity_id = (
                payload.get("activity_id") if isinstance(payload, dict) else None
            )
            if (
                self._session_rpe_load is not None
                and result.get("entity_type") == "activity_feedback"
                and isinstance(activity_id, str)
            ):
                result = {
                    **result,
                    "session_rpe_load": self._session_rpe_load(activity_id),
                }
            handler.send_json(200, result)
        elif path == "/api/change-history/undo-turn":
            client_turn_id = handler.read_json().get("client_turn_id")
            handler.send_json(200, self._coach_turn_undo_service.undo(client_turn_id))
        else:
            return False
        return True
