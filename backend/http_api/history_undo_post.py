"""Authenticated local change-history undo POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.proposals import CoachProposalCreationService
from backend.history.undo_service import HistoryUndoService


class HistoryUndoPostRoutes:
    """Dispatch undo previews and applications through their owning services."""

    def __init__(
        self,
        history_undo_service: Callable[[], HistoryUndoService],
        coach_proposal_creation_service: Callable[[], CoachProposalCreationService],
    ) -> None:
        self._history_undo_service = history_undo_service
        self._coach_proposal_creation_service = coach_proposal_creation_service

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
            handler.send_json(200, self._history_undo_service().apply(payload))
        else:
            return False
        return True
