"""Validate and resume one session-bound Coach chat turn."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from backend.coach.conversation import CoachConversationProvisionService
from backend.coach.conversation_gate import CoachConversationGate
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.response_transport import raise_if_chat_cancelled
from backend.coach.service import command_receipt
from backend.coach.structured_turn import CoachStructuredTurnService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.settings import SettingsService

COMMAND_STALE_SECONDS = 15 * 60


class CoachChatTurnService:
    """Own request validation, durable replay selection, and turn dispatch."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        receipts: CoachCommandReceiptService,
        settings: SettingsService,
        conversations: Callable[[], CoachConversationProvisionService],
        structured_turn: Callable[[], CoachStructuredTurnService],
        utc_now: Callable[[], str],
        conversation_gate: CoachConversationGate,
        maintenance_gate: MaintenanceGate,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._receipts = receipts
        self._settings = settings
        self._conversations = conversations
        self._structured_turn = structured_turn
        self._utc_now = utc_now
        self._conversation_gate = conversation_gate
        self._maintenance_gate = maintenance_gate

    @staticmethod
    def _validate(message: str, client_turn_id: str, cancel_event: threading.Event | None) -> tuple[str, str]:
        raise_if_chat_cancelled(cancel_event)
        message = message.strip()
        if not message:
            raise AppError(400, "Die Nachricht darf nicht leer sein.")
        if len(message) > 12_000:
            raise AppError(400, "Die Nachricht ist zu lang.")
        client_turn_id = str(client_turn_id).strip()
        if not client_turn_id or len(client_turn_id) > 120:
            raise AppError(400, "client_turn_id muss eine begrenzte, nicht leere Kennung sein.", reason="invalid_client_turn")
        return message, client_turn_id

    def _recover_stale_command(
        self, db: Any, existing_command: dict[str, Any], background_owned: bool, client_turn_id: str,
    ) -> dict[str, Any]:
        if not existing_command or existing_command.get("status") != "running" or background_owned:
            return existing_command
        age = db.execute(
            "SELECT (julianday('now') - julianday(?)) * 86400 AS age", (existing_command.get("updated_at"),)
        ).fetchone()
        if float((age or {}).get("age") or 0) <= COMMAND_STALE_SECONDS:
            return existing_command
        try:
            recovered = json.loads(existing_command.get("receipt") or "{}")
        except (TypeError, ValueError):
            recovered = {}
        if not isinstance(recovered, dict):
            recovered = {}
        recovered.update({"status": "failed", "error": "Die vorherige Coach-Verarbeitung wurde nach einem Prozessabbruch wieder freigegeben."})
        db.execute(
            "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? WHERE client_turn_id=? AND status='running'",
            (json.dumps(recovered, ensure_ascii=False, separators=(",", ":")), self._utc_now(), client_turn_id),
        )
        return {"status": "completed", "receipt": json.dumps(recovered)}

    def _command_state(
        self, client_turn_id: str, session_csrf_hash: str, background_job: bool,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
        with self._database_lock, self._database_manager().unit_of_work() as db:
            existing_command = db.execute(
                "SELECT conversation_id, intent, receipt, status, updated_at FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            background_receipt = command_receipt((existing_command or {}).get("receipt"))
            if existing_command:
                self._receipts.require_owner(background_receipt, session_csrf_hash)
            background_owned = bool(background_job and background_receipt.get("mode") == "background")
            existing_command = self._recover_stale_command(db, existing_command, background_owned, client_turn_id)
        return existing_command, background_receipt, background_owned

    def _provider_settings(self, background_receipt: dict[str, Any]) -> tuple[str, str, str]:
        ai_provider = str(background_receipt.get("ai_provider") or self._settings.selected_ai_provider()).casefold()
        if ai_provider not in {"openai", "gemini"}:
            ai_provider = self._settings.selected_ai_provider()
        model = str(background_receipt.get("model") or self._settings.selected_model(ai_provider))
        thinking_level = str(background_receipt.get("thinking_level") or self._settings.selected_thinking_level()).casefold()
        if thinking_level not in {"low", "medium", "high"}:
            thinking_level = self._settings.selected_thinking_level()
        return ai_provider, model, thinking_level

    def _resume_background_command(
        self, background_owned: bool, conversation_id: str,
        structured_intent: dict[str, Any], client_turn_id: str,
    ) -> None:
        if not background_owned:
            return
        with self._database_lock, self._database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE coach_commands SET conversation_id=?, intent=?, status='running', updated_at=? WHERE client_turn_id=?",
                (conversation_id, json.dumps(structured_intent), self._utc_now(), client_turn_id),
            )

    def run(
        self,
        message: str,
        *,
        allow_mutations: bool = True,
        on_text_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        session_csrf_hash: str = "",
        client_turn_id: str,
        background_job: bool = False,
    ) -> dict[str, Any]:
        """Resume or execute a Coach turn under its existing session claim."""
        with self._maintenance_gate.operation(), self._conversation_gate.operation():
            return self._run(
                message, allow_mutations=allow_mutations, on_text_delta=on_text_delta,
                cancel_event=cancel_event, session_csrf_hash=session_csrf_hash,
                client_turn_id=client_turn_id, background_job=background_job,
            )

    def _run(
        self,
        message: str,
        *,
        allow_mutations: bool,
        on_text_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
        session_csrf_hash: str,
        client_turn_id: str,
        background_job: bool,
    ) -> dict[str, Any]:
        message, client_turn_id = self._validate(message, client_turn_id, cancel_event)
        existing_command, background_receipt, background_owned = self._command_state(
            client_turn_id, session_csrf_hash, background_job,
        )
        if existing_command and existing_command.get("status") == "completed" and existing_command.get("receipt"):
            try:
                return self._receipts.read(client_turn_id, session_csrf_hash)
            except (TypeError, ValueError):
                pass
        if existing_command and not background_owned:
            raise AppError(409, "Diese Coach-Nachricht wird bereits verarbeitet.", reason="client_turn_in_progress")
        ai_provider, model, thinking_level = self._provider_settings(background_receipt)
        existing_conversation_id = str((existing_command or {}).get("conversation_id") or "")
        conversation_id = existing_conversation_id or self._conversations().ensure(ai_provider)
        structured_intent = {"allow_mutations": allow_mutations}
        self._resume_background_command(background_owned, conversation_id, structured_intent, client_turn_id)
        return self._structured_turn().run(
            message, intent=structured_intent, conversation_id=conversation_id, client_turn_id=client_turn_id,
            session_csrf_hash=session_csrf_hash, on_text_delta=on_text_delta, cancel_event=cancel_event,
            background_job=background_job, ai_provider=ai_provider, model=model, thinking_level=thinking_level,
        )
