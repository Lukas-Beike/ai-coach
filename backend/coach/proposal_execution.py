"""Consume approved Coach proposals and apply their effects."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from backend.activities.duplicate_service import DuplicateActivityService
from backend.coach.proposal_models import (
    LOCAL_COACH_WRITE_TOOLS,
    REMOTE_COACH_WRITE_TOOLS,
    _utc_now,
)
from backend.coach.proposal_validation import (
    _validate_local_coach_write,
    _validate_remote_coach_write,
)
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService
from backend.runtime.maintenance import MaintenanceGate

LOGGER = logging.getLogger("intervals_coach")


def _remote_source_message_status(
    message: Any, client_turn_id: str, conversation_id: str, session_key: str
) -> tuple[bool, bool]:
    receipt = json.loads(message["receipt"] or "{}")
    belongs = (
        message["conversation_id"] == conversation_id
        and receipt.get("session_key") == session_key
    )
    return belongs, belongs and message["client_turn_id"] == client_turn_id


class CoachProposalExecutionService:
    """Consume a confirmed, session-bound token before dispatching its action."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        duplicate_activity_service: DuplicateActivityService,
        history_undo_service: HistoryUndoService,
        intervals_client_factory: Callable[[], Any],
        maintenance_gate: MaintenanceGate,
        tool_dispatch_service: Callable[[], Any] | None = None,
        *,
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str] = _utc_now,
    ) -> None:
        self._database_manager = database_manager
        self._duplicate_activity_service = duplicate_activity_service
        self._history_undo_service = history_undo_service
        self._intervals_client_factory = intervals_client_factory
        self._maintenance_gate = maintenance_gate
        self._tool_dispatch_service = tool_dispatch_service
        self._now = now
        self._utc_now = utc_now

    def execute(
        self,
        token: Any,
        session_csrf_hash: str,
        payload_hash: Any = None,
    ) -> dict[str, Any]:
        with self._maintenance_gate.operation():
            return self._execute(token, session_csrf_hash, payload_hash)

    def _execute(
        self,
        token: Any,
        session_csrf_hash: str,
        payload_hash: Any,
    ) -> dict[str, Any]:
        row, action_type, payload = self._load_ready_action(
            token, session_csrf_hash, payload_hash
        )
        validated_context = self._validate_action_before_consume(
            action_type, payload, session_csrf_hash
        )
        self._consume_action(row["id"])
        return self._dispatch_action(
            row, action_type, payload, session_csrf_hash, validated_context
        )

    def _load_ready_action(
        self, token: Any, session_csrf_hash: str, payload_hash: Any
    ) -> tuple[Any, str, dict[str, Any]]:
        raw_token = str(token or "").strip()
        if len(raw_token) < 32:
            raise AppError(400, "Ungültiges Coach-Aktionstoken.")
        now = self._now()
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT * FROM coach_action_proposals "
                "WHERE action_token_hash=? AND session_csrf_hash=? AND status='ready'",
                (token_hash, str(session_csrf_hash)),
            ).fetchone()
            if not row:
                raise AppError(
                    409,
                    "Das Coach-Aktionstoken ist ungültig, abgelaufen oder bereits verwendet.",
                    reason="proposal_invalid",
                )
            if float(row["expires_at"]) <= now:
                raise AppError(
                    409,
                    "Das Coach-Aktionstoken ist abgelaufen.",
                    reason="proposal_expired",
                )
            if payload_hash is not None and str(payload_hash) != str(
                row["payload_hash"]
            ):
                raise AppError(
                    409,
                    "Der bestätigte Aktions-Payload wurde verändert.",
                    reason="proposal_payload_changed",
                )
            action_type = str(row["action_type"])
            payload = json.loads(row["payload"])
        return row, action_type, payload

    def _validate_action_before_consume(
        self, action_type: str, payload: dict[str, Any], session_csrf_hash: str
    ) -> tuple[str, dict[str, Any], dict[str, Any], str, str] | None:
        """Reject stale provenance before consuming the one-shot token."""
        if action_type in {"remote_coach_write", "local_coach_write"}:
            return self._validate_remote_write_context(payload, session_csrf_hash)
        if action_type not in {"delete_duplicate_intervals_activity", "undo_change"}:
            raise AppError(
                400, "Unbekannte Coach-Aktion.", reason="unknown_coach_action"
            )
        return None

    def _consume_action(self, proposal_id: str) -> None:
        with self._database_manager.unit_of_work() as db:
            consumed = db.execute(
                "UPDATE coach_action_proposals SET status='used', used_at=? WHERE id=? AND status='ready'",
                (self._utc_now(), proposal_id),
            ).rowcount
            if consumed != 1:
                raise AppError(
                    409,
                    "Das Coach-Aktionstoken wurde bereits verwendet.",
                    reason="proposal_used",
                )

    def _dispatch_action(
        self,
        row: Any,
        action_type: str,
        payload: dict[str, Any],
        session_csrf_hash: str,
        validated_context: tuple[str, dict[str, Any], dict[str, Any], str, str] | None,
    ) -> dict[str, Any]:
        if action_type == "delete_duplicate_intervals_activity":
            result = {
                "ok": True,
                **self._duplicate_activity_service.delete(
                    payload, self._intervals_client_factory()
                ),
            }
        elif action_type == "undo_change":
            result = self._history_undo_service.apply(payload)
        elif action_type in {"remote_coach_write", "local_coach_write"}:
            assert validated_context is not None
            try:
                result = self._execute_coach_write(session_csrf_hash, validated_context)
            except AppError:
                if action_type == "local_coach_write":
                    # Local nutrition validation failures have no durable
                    # effect. Keep their proposal available so a conflict is
                    # not misreported as an expired confirmation.
                    with self._database_manager.unit_of_work() as db:
                        db.execute(
                            "UPDATE coach_action_proposals SET status='ready', used_at=NULL "
                            "WHERE id=? AND status='used'",
                            (row["id"],),
                        )
                raise
        else:
            raise AppError(400, "Unbekannte Coach-Aktion.")
        LOGGER.info(
            "Coach action executed",
            extra={
                "event": "coach_action_executed",
                "context": {
                    "action_type": action_type,
                    "target_system": row["target_system"],
                    "proposal_id": row["id"],
                },
            },
        )
        return result

    def _execute_coach_write(
        self,
        session_csrf_hash: str,
        validated_context: tuple[str, dict[str, Any], dict[str, Any], str, str],
    ) -> dict[str, Any]:
        if not self._tool_dispatch_service:
            raise AppError(503, "Die Coach-Aktionsausführung ist nicht verfügbar.")
        tool, arguments, intent, conversation_id, client_turn_id = validated_context
        if tool in LOCAL_COACH_WRITE_TOOLS:
            result = self._tool_dispatch_service().execute(
                tool,
                arguments,
                intent=intent,
                conversation_id=conversation_id,
                client_turn_id=client_turn_id,
                session_csrf_hash=session_csrf_hash,
                sync_job_ids=[],
            )
            return {**result, "ok": True, "status": "applied"}
        sync_job_ids: list[str] = []
        result = self._tool_dispatch_service().execute(
            tool,
            arguments,
            intent=intent,
            conversation_id=conversation_id,
            client_turn_id=client_turn_id,
            session_csrf_hash=session_csrf_hash,
            sync_job_ids=sync_job_ids,
        )
        if sync_job_ids:
            result["sync_job_ids"] = sync_job_ids
        return result

    def _validate_remote_write_context(
        self, payload: dict[str, Any], session_csrf_hash: str
    ) -> tuple[str, dict[str, Any], dict[str, Any], str, str]:
        tool = payload.get("tool")
        arguments = payload.get("arguments")
        intent = payload.get("intent")
        local_write = tool in LOCAL_COACH_WRITE_TOOLS
        if (
            not isinstance(tool, str)
            or (tool not in REMOTE_COACH_WRITE_TOOLS and not local_write)
            or not isinstance(arguments, dict)
            or not isinstance(intent, dict)
        ):
            raise AppError(409, "Der freigegebene Coach-Auftrag ist ung\u00fcltig.")
        if local_write:
            _validate_local_coach_write(payload)
        else:
            _validate_remote_coach_write(payload)
        client_turn_id = str(payload.get("client_turn_id") or "")
        conversation_id = str(payload.get("conversation_id") or "")
        if not client_turn_id or not conversation_id:
            raise AppError(
                409, "Der freigegebene Coach-Auftrag ist nicht mehr g\u00fcltig."
            )
        self._validate_remote_write_provenance(
            intent, client_turn_id, conversation_id, session_csrf_hash
        )
        return tool, arguments, intent, conversation_id, client_turn_id

    def _validate_remote_write_provenance(
        self,
        intent: dict[str, Any],
        client_turn_id: str,
        conversation_id: str,
        session_csrf_hash: str,
    ) -> None:
        source_ids = intent["request"].get("source_message_ids") or []
        session_key = hashlib.sha256(str(session_csrf_hash).encode("utf-8")).hexdigest()
        with self._database_manager.unit_of_work() as db:
            bound = db.execute(
                "SELECT conversation_id, receipt FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            receipt = json.loads(bound["receipt"] or "{}") if bound else {}
            if (
                not bound
                or bound["conversation_id"] != conversation_id
                or receipt.get("session_key") != session_key
            ):
                raise AppError(
                    409,
                    "Der freigegebene Coach-Auftrag geh\u00f6rt nicht mehr zu dieser Sitzung.",
                )
            placeholders = ",".join("?" for _ in source_ids)
            existing = db.execute(
                "SELECT m.id, m.client_turn_id, c.conversation_id, c.receipt "
                "FROM messages m LEFT JOIN coach_commands c "
                "ON c.client_turn_id=m.client_turn_id "
                f"WHERE m.role='user' AND m.id IN ({placeholders})",
                tuple(source_ids),
            ).fetchall()
            valid_ids = set()
            current_turn_ids = set()
            for message in existing:
                belongs, current_turn = _remote_source_message_status(
                    message, client_turn_id, conversation_id, session_key
                )
                if belongs:
                    message_id = int(message["id"])
                    valid_ids.add(message_id)
                    if current_turn:
                        current_turn_ids.add(message_id)
            if valid_ids != set(source_ids) or not current_turn_ids:
                raise AppError(
                    409,
                    "Der urspr\u00fcngliche Nutzerauftrag ist nicht mehr verf\u00fcgbar.",
                )
