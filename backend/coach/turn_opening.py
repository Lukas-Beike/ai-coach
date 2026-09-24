"""Open a durable Coach turn and bind it to its creating session."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from backend.coach.authorization import coach_session_key
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository


class CoachTurnOpeningService:
    """Create or return the session-owned receipt that opens a Coach turn."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: threading.RLock,
        chat_repository: ChatRepository,
        receipt_service: CoachCommandReceiptService,
        utc_now: Callable[[], str],
        uuid_factory: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._chat_repository = chat_repository
        self._receipt_service = receipt_service
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory

    def open(
        self,
        message: str,
        *,
        intent: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
        session_csrf_hash: str,
        ai_provider: str,
        model: str | None,
    ) -> dict[str, Any]:
        with self._database_lock, self._database_manager.unit_of_work() as db:
            existing = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            receipt = command_receipt(existing["receipt"]) if existing else {}
            if existing:
                self._receipt_service.require_owner(receipt, session_csrf_hash)
            else:
                user = self._chat_repository.add(
                    db, "user", message, client_turn_id=client_turn_id
                )
                receipt = {
                    "client_turn_id": client_turn_id,
                    "session_key": coach_session_key(session_csrf_hash),
                    "user_message_id": user["id"],
                    "status": "running",
                    "command_receipts": [],
                    "ai_provider": ai_provider,
                    "model": model,
                }
                db.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) VALUES (?, ?, ?, ?, 'none', 'running', ?, ?, ?)",
                    (
                        self._uuid_factory().hex,
                        client_turn_id,
                        conversation_id,
                        json.dumps(intent),
                        json.dumps(receipt),
                        self._utc_now(),
                        self._utc_now(),
                    ),
                )
        return receipt
