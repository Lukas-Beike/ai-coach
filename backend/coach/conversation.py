"""Durable Coach conversation state and local message projections."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from backend.coach.constants import AI_PROVIDER
from backend.coach.service import command_receipt
from backend.coach.streams import ChatStreamRegistry
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.errors import AppError
from backend.providers.openai import OpenAIResponsesClient
from backend.runtime.events import StateEventBuffer

MESSAGE_ATTACHMENTS_QUERY = "SELECT attachments FROM messages WHERE id=?"


class CoachConversationResetService:
    """Clear local dialogue and best-effort delete the remote conversation."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_values: KeyValueRepository,
        openai_client: OpenAIResponsesClient,
        streams: ChatStreamRegistry,
        db_lock: Any,
        conversation_lock: Any,
        utc_now: Callable[[], str],
        uuid_factory: Callable[[], uuid.UUID],
        logger: Any,
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._openai_client = openai_client
        self._streams = streams
        self._db_lock = db_lock
        self._conversation_lock = conversation_lock
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._logger = logger

    def _delete_remote(self, conversation_id: str) -> bool:
        if not conversation_id:
            return False
        try:
            return self._openai_client.delete_conversation(conversation_id)
        except Exception:
            self._logger.warning(
                "Remote OpenAI conversation could not be deleted during reset",
                extra={"event": "openai_reset_remote_delete_failed"},
                exc_info=True,
            )
            return False

    def _reset_local(self) -> tuple[list[str], str, str]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            now = self._utc_now()
            conversation_id = self._key_values.get(db, "openai_conversation_id") or ""
            operation_ids: list[str] = []
            rows = db.execute(
                "SELECT client_turn_id, receipt FROM coach_commands WHERE status IN ('queued', 'running')"
            ).fetchall()
            for row in rows:
                receipt = command_receipt(row["receipt"])
                operation_id = str(receipt.get("operation_id") or "")
                if operation_id:
                    operation_ids.append(operation_id)
                receipt.update(
                    status="cancelled",
                    phase="chat_reset",
                    cancel_requested=True,
                    message=None,
                )
                db.execute(
                    "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? WHERE client_turn_id=?",
                    (
                        json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                        now,
                        row["client_turn_id"],
                    ),
                )
            db.execute("DELETE FROM messages")
            db.execute(
                "UPDATE coach_action_proposals SET status='cancelled', action_token_hash=NULL WHERE action_type IN ('remote_coach_write', 'local_coach_write') AND status IN ('preview', 'ready')"
            )
            generation = self._uuid_factory().hex
            self._key_values.set(db, "chat_generation", generation)
            self._key_values.set(db, "openai_conversation_id", "")
            self._key_values.set(db, "last_chat_reset_at", now)
            db.execute(
                "UPDATE coach_plan_artifacts SET status='superseded', updated_at=? WHERE status='draft'",
                (now,),
            )
            self._key_values.set(db, "coach_pending_request", "null")
        return operation_ids, conversation_id, generation

    def reset(self) -> dict[str, Any]:
        with self._conversation_lock:
            operation_ids, conversation_id, generation = self._reset_local()
            for operation_id in operation_ids:
                self._streams.cancel_background_event(operation_id)
        return {
            "status": "ok",
            "generation": generation,
            "remote_conversation_deleted": self._delete_remote(conversation_id),
            "message": "Neuer Coach-Chat wird beim nächsten Senden erstellt.",
        }


class CoachConversationProvisionService:
    """Provision and persist an OpenAI conversation identifier."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        openai_responses_client: OpenAIResponsesClient,
        db_lock: Any,
        uuid_factory: Callable[[], uuid.UUID],
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_value_repository
        self._client = openai_responses_client
        self._db_lock = db_lock

    def ensure(self) -> str:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._key_values.get(db, "openai_conversation_id")
        if existing:
            return existing
        result = self._client.request(
            "/conversations",
            {"metadata": {"app": "intervals-coach", "purpose": "personal-coach"}},
        )
        conversation_id = result.get("id")
        if not isinstance(conversation_id, str):
            raise AppError(502, "OpenAI hat keine Konversations-ID zurückgegeben.")
        with self._db_lock, self._database_manager.unit_of_work() as db:
            self._key_values.set(db, "openai_conversation_id", conversation_id)
        return conversation_id


class CoachAttachmentContextService:
    """Load attachment records and safe local evidence for Coach context."""

    def __init__(self, database_manager: DatabaseManager) -> None:
        self._database_manager = database_manager

    def load_for_receipt(
        self, receipt: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._database_manager.reader() as db:
            attachment_row = db.execute(
                MESSAGE_ATTACHMENTS_QUERY, (receipt.get("user_message_id"),)
            ).fetchone()
            prior_ids = set()
            for row in db.execute(
                "SELECT receipt FROM coach_commands WHERE receipt IS NOT NULL"
            ).fetchall():
                prior = command_receipt(row["receipt"])
                message_id = prior.get("user_message_id")
                if prior.get("ai_provider") == AI_PROVIDER and isinstance(
                    message_id, int
                ):
                    prior_ids.add(message_id)
            has_prior = bool(
                prior_ids
                and db.execute(
                    f"SELECT 1 FROM messages WHERE id<? AND attachments!='[]' AND id IN ({','.join('?' for _ in prior_ids)}) LIMIT 1",
                    (receipt.get("user_message_id") or 0, *prior_ids),
                ).fetchone()
            )
        try:
            attachments = (
                json.loads(attachment_row["attachments"]) if attachment_row else []
            )
        except TypeError, json.JSONDecodeError:
            attachments = []
        return (attachments if isinstance(attachments, list) else []), has_prior

    def add_evidence(self, context: dict[str, Any]) -> None:
        with self._database_manager.reader() as db:
            context["attachment_evidence"] = []
            for message in context["messages"]:
                row = db.execute(MESSAGE_ATTACHMENTS_QUERY, (message["id"],)).fetchone()
                try:
                    attachments = json.loads(row["attachments"] or "[]") if row else []
                except TypeError, json.JSONDecodeError:
                    attachments = []
                for item in attachments if isinstance(attachments, list) else []:
                    context["attachment_evidence"].append(
                        {
                            "source_message_id": message["id"],
                            "type": item.get("type"),
                            "untrusted_attachment_name": item.get("name"),
                            **(
                                {item.get("type"): item.get("summary")}
                                if item.get("type") in {"gpx", "fit"}
                                else {}
                            ),
                        }
                    )


class CoachMessageService:
    """Persist Coach messages and publish their committed state change."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        chat_repository: ChatRepository,
        state_event_buffer: StateEventBuffer,
    ) -> None:
        self._database_manager = database_manager
        self._chat_repository = chat_repository
        self._state_event_buffer = state_event_buffer

    def add(self, role: str, content: str) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            result = self._chat_repository.add(db, role, content)
        self._state_event_buffer.publish(
            "coach", {"message_id": result.get("id"), "role": str(role)[:20]}
        )
        return result

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            return self._chat_repository.list(db, limit)


class CoachConversationHistoryService:
    """Read bounded local conversation pages transactionally."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        chat_repository: ChatRepository,
        key_values: KeyValueRepository,
        database_lock: Any,
    ) -> None:
        self._database_manager = database_manager
        self._chat_repository = chat_repository
        self._key_values = key_values
        self._database_lock = database_lock

    def page(
        self, *, before_message_id: int | None, search: str, limit: int
    ) -> tuple[str, list[dict[str, Any]]]:
        with self._database_lock, self._database_manager.unit_of_work() as db:
            messages = self._chat_repository.list_page(
                db, before_message_id=before_message_id, search=search, limit=limit
            )
            generation = self._key_values.get(db, "chat_generation") or "initial"
        return generation, messages
