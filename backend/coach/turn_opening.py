"""Open a durable Coach turn and bind it to its creating session."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.coach.authorization import coach_session_key
from backend.coach.constants import turn_ai_provider
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.service import command_receipt
from backend.db import coach_store
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository
from backend.errors import AppError


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
        model: str | None,
    ) -> dict[str, Any]:
        with self._database_lock, self._database_manager.unit_of_work() as db:
            existing = coach_store.command_row(db, client_turn_id)
            receipt = command_receipt(existing["receipt"]) if existing else {}
            if existing:
                self._receipt_service.require_owner(receipt, session_csrf_hash)
                self._require_same_message(db, client_turn_id, message)
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
                    "ai_provider": turn_ai_provider(model),
                    "model": model,
                }
                coach_store.insert_command(
                    db,
                    self._uuid_factory().hex,
                    client_turn_id,
                    conversation_id,
                    intent,
                    target_system="none",
                    status="running",
                    receipt=receipt,
                    created_at=self._utc_now(),
                    updated_at=self._utc_now(),
                )
        return receipt

    @staticmethod
    def _require_same_message(db: Any, client_turn_id: str, message: str) -> None:
        """Refuse to run new text under a turn id that stored different text."""
        stored = coach_store.user_message_for_turn(db, client_turn_id, "content")
        if stored is not None and stored["content"] != message.strip():
            raise AppError(
                409,
                "Diese Anfrage-ID gehört bereits zu einer anderen Nachricht. "
                "Bitte sende die Nachricht erneut.",
                reason="client_turn_text_mismatch",
            )
