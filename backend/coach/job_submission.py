"""Validate, persist, and publish Coach background job submissions."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

from backend.coach.attachments import (
    MAX_ATTACHMENT_STORAGE_BYTES,
    MAX_GEMINI_INLINE_IMAGE_BYTES,
    gemini_inline_image_bytes,
    validate_attachments,
)
from backend.coach.authorization import coach_execution_scope, coach_session_key
from backend.coach.service import command_receipt
from backend.coach.streams import ChatStreamRegistry
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.settings import SettingsService


class CoachJobSubmissionService:
    """Own validation and durable submission of a Coach background turn."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        chat_repository: ChatRepository,
        database_lock: Any,
        settings_service: SettingsService,
        state_event_buffer: StateEventBuffer,
        stream_registry: ChatStreamRegistry,
        wake_event: Any,
        utc_now: Callable[[], str],
        *,
        background_horizon_days: int,
        max_attachment_storage_bytes: int = MAX_ATTACHMENT_STORAGE_BYTES,
        max_gemini_inline_image_bytes: int = MAX_GEMINI_INLINE_IMAGE_BYTES,
    ) -> None:
        self._database_manager = database_manager
        self._chat_repository = chat_repository
        self._database_lock = database_lock
        self._settings_service = settings_service
        self._state_event_buffer = state_event_buffer
        self._stream_registry = stream_registry
        self._wake_event = wake_event
        self._utc_now = utc_now
        self._background_horizon_days = background_horizon_days
        self._max_attachment_storage_bytes = max_attachment_storage_bytes
        self._max_gemini_inline_image_bytes = max_gemini_inline_image_bytes

    def active(
        self, session_csrf_hash: str, operation_id: str | None = None
    ) -> dict[str, Any] | None:
        session_key = coach_session_key(session_csrf_hash)
        with self._database_lock:
            database_manager = self._database_manager()
            with database_manager.unit_of_work() as db:
                rows = self._active_rows(db)
        return self._find_active(rows, session_key, operation_id)

    def stream_status(self, session_csrf_hash: str) -> dict[str, Any]:
        """Project attached or durable background activity for this session."""
        attached = self._stream_registry.attached_status(session_csrf_hash)
        if attached:
            return attached
        job = self.active(session_csrf_hash)
        if not job:
            return {"status": "idle", "operation_id": None}
        receipt = job["receipt"]
        return {
            "status": "running",
            "operation_id": receipt.get("operation_id"),
            "mode": "background",
            "phase": receipt.get("phase") or job.get("status"),
            "plan_scope": receipt.get("plan_scope") or {},
        }

    @staticmethod
    def _active_rows(db: Any) -> list[dict[str, Any]]:
        return db.execute(
            "SELECT client_turn_id, status, receipt, updated_at FROM coach_commands "
            "WHERE status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

    @staticmethod
    def _find_active(
        rows: list[dict[str, Any]], session_key: str, operation_id: str | None = None
    ) -> dict[str, Any] | None:
        for row in rows:
            receipt = command_receipt(row.get("receipt"))
            if receipt.get("mode") != "background" or receipt.get("session_key") != session_key:
                continue
            if operation_id and str(receipt.get("operation_id") or "") != str(operation_id):
                continue
            return {**dict(row), "receipt": receipt}
        return None

    def enqueue(
        self,
        message: str,
        client_turn_id: str,
        session_csrf_hash: str,
        *,
        operation_id: str | None = None,
        cancel_event: threading.Event | None = None,
        request_kind: str | None = None,
        attachments: Any = None,
    ) -> dict[str, Any]:
        """Persist a long Coach turn before returning control to the browser."""
        message, client_turn_id, request_kind, attachments, scope = self._validate_submission(
            message, client_turn_id, request_kind, attachments
        )
        active = self.active(session_csrf_hash)
        if active and active["client_turn_id"] != client_turn_id:
            raise AppError(409, "Für diese Sitzung läuft bereits eine Coach-Anfrage.", reason="chat_already_running")
        operation_id = operation_id or uuid.uuid4().hex
        session_key = coach_session_key(session_csrf_hash)
        ai_provider, model, thinking_level = self._provider_settings(attachments)

        existing_response, user_message_id = self._persist(
            message,
            client_turn_id,
            session_csrf_hash,
            operation_id,
            request_kind,
            attachments,
            scope,
            session_key,
            ai_provider,
            model,
            thinking_level,
        )
        if existing_response:
            return existing_response
        self._state_event_buffer.publish(
            "coach", {"message_id": user_message_id, "role": "user", "client_turn_id": client_turn_id}
        )
        self._stream_registry.set_background_event(operation_id, cancel_event or threading.Event())
        self._wake_event.set()
        return {"status": "queued", "mode": "background", "operation_id": operation_id, "plan_scope": scope}

    def _validate_submission(
        self,
        message: str,
        client_turn_id: str,
        request_kind: str | None,
        attachments: Any,
    ) -> tuple[str, str, str | None, list[dict[str, Any]], dict[str, Any]]:
        message = str(message or "").strip()
        client_turn_id = str(client_turn_id or "").strip()
        request_kind = str(request_kind or "").strip() or None
        if request_kind not in {None, "morning_checkin"}:
            raise AppError(400, "Unbekannte Coach-Schnellaktion.", reason="invalid_request_kind")
        try:
            attachments = validate_attachments(attachments)
        except ValueError:
            raise AppError(
                400,
                "Ungültiger Anhang. Erlaubt: bis zu 4 GPX-, FIT-, PNG-, JPEG- oder WebP-Dateien mit je höchstens 5 MB.",
                reason="invalid_attachment",
            ) from None
        if attachments and not message:
            message = "Bitte analysiere die angehängten Dateien."
        scope = coach_execution_scope(None, background_horizon_days=self._background_horizon_days)
        if not message or len(message) > 12_000:
            raise AppError(400, "Die Coach-Nachricht ist leer oder zu lang.", reason="invalid_chat_message")
        if not client_turn_id or len(client_turn_id) > 120:
            raise AppError(400, "client_turn_id muss eine begrenzte, nicht leere Kennung sein.", reason="invalid_client_turn")
        if not scope["background"]:
            raise AppError(400, "Diese Coach-Anfrage benötigt keinen Hintergrundauftrag.", reason="background_not_required")
        return message, client_turn_id, request_kind, attachments, scope

    def _provider_settings(self, attachments: list[dict[str, Any]]) -> tuple[str, str, str]:
        ai_provider = self._settings_service.selected_ai_provider()
        model = self._settings_service.selected_model(ai_provider)
        thinking_level = self._settings_service.selected_thinking_level()
        if ai_provider == "gemini" and gemini_inline_image_bytes(attachments) > self._max_gemini_inline_image_bytes:
            raise AppError(
                413,
                "Die ausgewählten Dateien sind für eine Gemini-Anfrage zusammen zu groß. Sende weniger Dateien oder wähle OpenAI.",
                reason="gemini_attachment_request_too_large",
            )
        return ai_provider, model, thinking_level

    def _persist(
        self,
        message: str,
        client_turn_id: str,
        session_csrf_hash: str,
        operation_id: str,
        request_kind: str | None,
        attachments: list[dict[str, Any]],
        scope: dict[str, Any],
        session_key: str,
        ai_provider: str,
        model: str,
        thinking_level: str,
    ) -> tuple[dict[str, Any] | None, int | None]:
        now = self._utc_now()
        with self._database_lock:
            database_manager = self._database_manager()
            with database_manager.unit_of_work() as db:
                existing = db.execute(
                    "SELECT status, receipt FROM coach_commands WHERE client_turn_id=?", (client_turn_id,)
                ).fetchone()
                if existing:
                    receipt = command_receipt(existing.get("receipt"))
                    if receipt.get("session_key") != coach_session_key(session_csrf_hash):
                        raise AppError(
                            403,
                            "Dieser Coach-Auftrag gehoert zu einer anderen Sitzung.",
                            reason="command_scope_denied",
                        )
                    if receipt.get("mode") != "background":
                        raise AppError(409, "Diese Coach-Nachricht wird bereits verarbeitet.", reason="client_turn_in_progress")
                    return {
                        "status": "completed" if existing.get("status") == "completed" else "queued",
                        "mode": "background",
                        "operation_id": receipt.get("operation_id"),
                        "plan_scope": receipt.get("plan_scope") or scope,
                    }, None

                if self._find_active(self._active_rows(db), session_key):
                    raise AppError(
                        409,
                        "Für diese Sitzung läuft bereits eine Coach-Anfrage.",
                        reason="chat_already_running",
                    )

                user_message = self._chat_repository.add(db, "user", message, client_turn_id=client_turn_id)
                attachment_json = json.dumps(attachments, ensure_ascii=False, separators=(",", ":"))
                stored_attachment_bytes = db.execute(
                    "SELECT COALESCE(SUM(length(attachments)), 0) AS total FROM messages"
                ).fetchone()["total"]
                stored_gemini_history_row = db.execute(
                    "SELECT COALESCE(length(value), 0) AS total FROM kv WHERE key='gemini_conversation_history'"
                ).fetchone()
                stored_gemini_history_bytes = stored_gemini_history_row["total"] if stored_gemini_history_row else 0
                if (
                    int(stored_attachment_bytes or 0)
                    + int(stored_gemini_history_bytes or 0)
                    + len(attachment_json.encode("utf-8"))
                    > self._max_attachment_storage_bytes
                ):
                    raise AppError(
                        413,
                        "Der lokale Speicher für Chat-Anhänge ist ausgeschöpft. Entferne alte Chat-Daten, bevor du weitere Bilder sendest.",
                        reason="attachment_storage_quota",
                    )
                db.execute("UPDATE messages SET attachments=? WHERE id=?", (attachment_json, user_message["id"]))
                receipt = {
                    "status": "queued",
                    "mode": "background",
                    "phase": "queued",
                    "operation_id": operation_id,
                    "session_key": session_key,
                    "user_message_id": user_message["id"],
                    "client_turn_id": client_turn_id,
                    "plan_scope": scope,
                    "ai_provider": ai_provider,
                    "model": model,
                    "thinking_level": thinking_level,
                    "request_kind": request_kind,
                }
                db.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) "
                    "VALUES (?, ?, NULL, '{}', 'local', 'queued', ?, ?, ?)",
                    (
                        uuid.uuid4().hex,
                        client_turn_id,
                        json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                        now,
                        now,
                    ),
                )
        return None, user_message["id"]
