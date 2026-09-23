"""Session-bound read projection for durable Coach command receipts."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from backend.coach.authorization import coach_session_key
from backend.coach.proposals import coach_action_view
from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.errors import AppError


class CoachCommandReceiptService:
    def __init__(
        self,
        manager_factory: Callable[[], DatabaseManager],
        database_lock: threading.RLock,
        *,
        now: Callable[[], float] = time.time,
        proposal_view: Callable[[dict[str, Any]], dict[str, Any]] = coach_action_view,
    ) -> None:
        self._manager_factory = manager_factory
        self._database_lock = database_lock
        self._now = now
        self._proposal_view = proposal_view

    def require_owner(self, receipt: dict[str, Any], session_csrf_hash: str) -> None:
        if receipt.get("session_key") != coach_session_key(session_csrf_hash):
            raise AppError(
                403,
                "Dieser Coach-Auftrag gehoert zu einer anderen Sitzung.",
                reason="command_scope_denied",
            )

    def read(self, client_turn_id: Any, session_csrf_hash: str) -> dict[str, Any]:
        turn_id = str(client_turn_id or "").strip()
        if not turn_id or len(turn_id) > 120:
            raise AppError(
                400,
                "Ungueltige Coach-Auftragskennung.",
                reason="invalid_client_turn",
            )

        with self._database_lock, self._manager_factory().unit_of_work() as db:
            row = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                (turn_id,),
            ).fetchone()
            if not row:
                raise AppError(
                    404, "Coach-Auftrag nicht gefunden.", reason="command_not_found"
                )
            receipt = command_receipt(row["receipt"])
            self.require_owner(receipt, session_csrf_hash)

            proposals = receipt.get("proposed_actions") or [
                item["result"]["proposed_action"]
                for item in receipt.get("command_receipts", [])
                if isinstance(item.get("result"), dict)
                and item["result"].get("proposed_action")
            ]
            receipt["proposed_actions"] = []
            for proposal in proposals:
                current = db.execute(
                    "SELECT * FROM coach_action_proposals WHERE id=? AND session_csrf_hash=?",
                    (proposal.get("id"), session_csrf_hash),
                ).fetchone()
                if current:
                    value = self._proposal_view(dict(current))
                    if (
                        float(value["expires_at"]) <= self._now()
                        and value["status"] in {"preview", "ready"}
                    ):
                        value["status"] = "expired"
                    receipt["proposed_actions"].append(value)

        return {
            key: value
            for key, value in {**receipt, "client_turn_id": turn_id}.items()
            if key != "session_key"
        }
