"""Undo every local record change of one finished Coach turn at once."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from backend.coach.change_receipts import turn_changes
from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService
from backend.runtime.clock import utc_now


class CoachTurnUndoService:
    """Restore a turn's changes in one transaction, or none of them."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        database_lock: threading.RLock,
        history_undo_service: Callable[[], HistoryUndoService],
        *,
        now: Callable[[], str] = utc_now,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._history_undo_service = history_undo_service
        self._now = now

    def undo(self, client_turn_id: Any) -> dict[str, Any]:
        turn_id = str(client_turn_id or "").strip()
        if not turn_id or len(turn_id) > 120:
            raise AppError(400, "Ungültiger Coach-Auftrag.")
        history_undo = self._history_undo_service()
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id=?",
                (turn_id,),
            ).fetchone()
            if row is None or row["status"] != "completed":
                raise AppError(404, "Coach-Antwort nicht gefunden.")
            receipt = command_receipt(row["receipt"])
            summary = receipt.get("change_summary")
            if not isinstance(summary, dict):
                raise AppError(409, "Diese Coach-Antwort hat nichts geändert.")
            if summary.get("undone_at"):
                raise AppError(
                    409, "Diese Coach-Änderungen wurden bereits zurückgenommen."
                )
            changes = turn_changes(receipt.get("command_receipts") or [])
            if summary.get("undoable") is not True or not changes:
                raise AppError(
                    409,
                    "Diese Coach-Änderungen können nicht gesammelt zurückgenommen werden.",
                )
            history_undo.apply_many(db, changes)
            now = self._now()
            summary = {**summary, "undone_at": now}
            db.execute(
                "UPDATE coach_commands SET receipt=json_set(receipt, '$.change_summary', json(?)), "
                "updated_at=? WHERE client_turn_id=?",
                (json.dumps(summary, ensure_ascii=False), now, turn_id),
            )
        return {
            "status": "undone",
            "client_turn_id": turn_id,
            "coach_changes": summary,
            "remote_untouched": True,
        }
