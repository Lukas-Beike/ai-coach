"""Claim, execute, and receipt one explicit local Coach planning command."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from backend.coach.authorization import coach_session_key
from backend.coach.proposals import coach_action_hash
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.service import command_receipt
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.turn_failures import CoachTurnFailureService
from backend.db.manager import DatabaseManager
from backend.errors import STALE_PLANNING_REVISION_ERROR, AppError

SELECT_PLANNING_REVISION_SQL = "SELECT revision FROM planning_state WHERE id=1"
PLANNING_OPERATIONS = frozenset({
    "commit_training_plan", "replace_training_plan", "apply_training_changes",
    "manage_training_templates",
})


class CoachPlanningCommandService:
    """Own the durable claim/execute/receipt lifecycle and scope preparation."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: Any,
        receipts: CoachCommandReceiptService,
        tools: CoachToolDispatchService,
        failures: CoachTurnFailureService,
        now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._receipts = receipts
        self._tools = tools
        self._failures = failures
        self._now = now

    def execute(
        self, payload: Any, *, conversation_id: str, session_csrf_hash: str = ""
    ) -> dict[str, Any]:
        client_turn_id, operation, arguments, intent = self._prepare(payload)
        command_identity = {
            "client_turn_id": client_turn_id,
            "session_key": coach_session_key(session_csrf_hash),
            "effect_key": coach_action_hash({"operation": operation, "arguments": arguments}),
        }
        existing_receipt = self._claim(
            client_turn_id, conversation_id, session_csrf_hash, payload, intent, command_identity
        )
        if existing_receipt:
            return existing_receipt
        self._execute_claimed(
            client_turn_id, operation, arguments, intent, conversation_id,
            session_csrf_hash, command_identity,
        )
        return self._receipts.read(client_turn_id, session_csrf_hash)

    @staticmethod
    def _append_template_scope(intent: dict[str, Any], templates: Any) -> None:
        if not isinstance(templates, list):
            raise AppError(400, "Vorlagenaenderungen benoetigen eine Liste.", reason="template_limit")
        for template in templates:
            if not isinstance(template, dict):
                raise AppError(400, "Jede Vorlagenaenderung muss ein Objekt sein.", reason="template_limit")
            if str(template.get("action") or "create") in {"update", "archive", "restore", "delete"}:
                intent["authorization_scope"].append(f"library_workout:{template.get('local_id') or ''}")
            else:
                intent["authorization_scope"].append("local_template")

    @classmethod
    def _append_scope(
        cls, intent: dict[str, Any], operation: str, arguments: dict[str, Any]
    ) -> None:
        if operation == "apply_training_changes":
            changes = arguments.get("changes") if isinstance(arguments.get("changes"), list) else []
            for change in changes:
                if isinstance(change, dict) and change.get("local_id"):
                    intent["authorization_scope"].append(f"planned_unit:{change['local_id']}")
                elif isinstance(change, dict) and str(change.get("action") or "update").strip().casefold() == "create":
                    intent["authorization_scope"].append("local_plan")
        elif operation == "replace_training_plan":
            intent["authorization_scope"].append("local_plan")
        elif operation == "manage_training_templates":
            cls._append_template_scope(intent, arguments.get("templates"))

    @staticmethod
    def _intent(payload: dict[str, Any], operation: str) -> dict[str, Any]:
        return {
            "intent": "local_action", "operation": operation, "target_system": "local",
            "artifact_id": str(payload.get("artifact_id") or "").strip() or None,
            "ambiguities": [], "authorization_scope": [], "follow_up_operations": [],
        }

    def _prepare_commit(
        self, payload: dict[str, Any], arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any]:
        artifact_id = str(payload.get("artifact_id") or "").strip()
        if not artifact_id:
            raise AppError(400, "Zum Speichern wird ein Planartefakt benötigt.", reason="artifact_required")
        intent["authorization_scope"].append(f"artifact:{artifact_id}")
        expected_revision = payload.get("expected_revision")
        with self._db_lock, self._database_manager.unit_of_work() as db:
            row = db.execute(SELECT_PLANNING_REVISION_SQL).fetchone()
        if expected_revision is not None and int(expected_revision) != int((row or {}).get("revision") or 0):
            raise AppError(409, STALE_PLANNING_REVISION_ERROR, reason="planning_revision_conflict")
        return {**arguments, "artifact_id": artifact_id}

    def _prepare(self, payload: Any) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        if not isinstance(payload, dict):
            raise AppError(400, "Das Planungskommando muss ein Objekt sein.", reason="invalid_planning_command")
        client_turn_id = str(payload.get("client_turn_id") or "").strip()
        operation = str(payload.get("operation") or "").strip()
        if not client_turn_id or len(client_turn_id) > 120:
            raise AppError(400, "client_turn_id ist für Planungskommandos erforderlich.", reason="invalid_client_turn")
        if operation not in PLANNING_OPERATIONS:
            raise AppError(400, "Das Planungskommando ist nicht zulässig.", reason="invalid_planning_command")
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            raise AppError(400, "Das Planungskommando benoetigt arguments.", reason="invalid_planning_command")
        intent = self._intent(payload, operation)
        if operation == "commit_training_plan":
            arguments = self._prepare_commit(payload, arguments, intent)
        else:
            self._append_scope(intent, operation, arguments)
        return client_turn_id, operation, arguments, intent

    def _claim(
        self, client_turn_id: str, conversation_id: str, session_csrf_hash: str,
        payload: dict[str, Any], intent: dict[str, Any], command_identity: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = db.execute(
                "SELECT conversation_id, status, receipt FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if existing:
                previous = command_receipt(existing["receipt"])
                self._receipts.require_owner(previous, session_csrf_hash)
                if previous.get("effect_key") != command_identity["effect_key"]:
                    raise AppError(409, "Die Auftragskennung wurde fuer andere Argumente verwendet.", reason="command_conflict")
            if existing and existing.get("status") == "completed" and existing.get("receipt"):
                if str(existing.get("conversation_id") or "") != str(conversation_id):
                    raise AppError(403, "Dieses Planungskommando gehört zu einer anderen Conversation.", reason="command_scope_denied")
                return self._receipts.read(client_turn_id, session_csrf_hash)
            if existing:
                raise AppError(409, "Dieses Planungskommando wird bereits verarbeitet.", reason="client_turn_in_progress")
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, artifact_id, status, receipt, created_at, updated_at) VALUES (?, ?, ?, ?, 'local', ?, 'running', ?, ?, ?)",
                (uuid.uuid4().hex, client_turn_id, conversation_id,
                 json.dumps(intent, separators=(",", ":")), payload.get("artifact_id"),
                 json.dumps(command_identity), self._now(), self._now()),
            )
        return None

    def _execute_claimed(
        self, client_turn_id: str, operation: str, arguments: dict[str, Any],
        intent: dict[str, Any], conversation_id: str, session_csrf_hash: str,
        command_identity: dict[str, Any],
    ) -> None:
        try:
            with self._db_lock, self._database_manager.unit_of_work() as db:
                sync_job_ids: list[str] = []
                result = self._tools.execute(
                    operation, arguments, intent=intent, conversation_id=conversation_id,
                    client_turn_id=client_turn_id, session_csrf_hash=session_csrf_hash,
                    sync_job_ids=sync_job_ids,
                )
                receipt = {
                    **command_identity, "message": None,
                    "command_receipts": [{"tool": operation, "result": result}],
                    "sync_job_ids": sync_job_ids, "intent": intent,
                    "tool_rounds": 1, "status": "completed",
                }
                db.execute(
                    "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? "
                    "WHERE client_turn_id=? AND status='running'",
                    (json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                     self._now(), client_turn_id),
                )
        except Exception as exc:  # noqa: BLE001 - persist any tool failure as a durable receipt
            self._failures.persist(client_turn_id, intent, exc)
