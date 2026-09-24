"""Session-owned Coach action proposal projection and expiration cleanup."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from backend.activities.duplicates import (
    latest_wahoo_garmin_duplicate,
    validate_duplicate_delete,
)
from backend.activities.duplicate_service import DuplicateActivityService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.state import SyncStateRepository


COACH_ACTION_TYPES = {"undo_change", "delete_duplicate_intervals_activity"}
COACH_ACTION_TTL_SECONDS = 600
LOGGER = logging.getLogger("intervals_coach")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validated_coach_action_preview_input(
    values: Any,
) -> tuple[str, str, dict[str, Any] | list[Any], dict[str, Any] | list[Any], dict[str, Any]]:
    """Validate proposal input shape, supported action, target, and visible diff."""
    if not isinstance(values, dict):
        raise AppError(400, "Die Aktionsvorschau muss ein Objekt sein.")
    action_type = str(values.get("action_type") or "").strip()
    if action_type not in COACH_ACTION_TYPES:
        raise AppError(400, "Unbekannter Coach-Aktionstyp.")
    target_system = str(values.get("target_system") or "").strip()
    if target_system not in {"local", "intervals", "local+intervals"}:
        raise AppError(400, "Die Aktionsvorschau benötigt ein gültiges Zielsystem.")
    object_ids = values.get("object_ids")
    diff = values.get("diff")
    payload = values.get("payload")
    if (
        not isinstance(object_ids, (dict, list))
        or not isinstance(diff, (dict, list))
        or not isinstance(payload, dict)
    ):
        raise AppError(400, "Die Aktionsvorschau benötigt Objekt-IDs, Diff und Payload.")
    expected_target = "intervals" if action_type == "delete_duplicate_intervals_activity" else "local"
    if target_system != expected_target or not diff:
        raise AppError(400, "Die geschuetzte Aktion benoetigt das passende Ziel und einen sichtbaren Diff.")
    return action_type, target_system, object_ids, diff, payload


def coach_action_hash(payload: Any) -> str:
    """Return the canonical SHA-256 identity used for Coach action payloads."""
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def coach_action_view(row: dict[str, Any]) -> dict[str, Any]:
    """Expose proposal metadata without returning its private action payload."""
    return {
        "id": row["id"],
        "action_type": row["action_type"],
        "target_system": row["target_system"],
        "object_ids": json.loads(row["object_ids"]),
        "diff": json.loads(row["diff"]),
        "payload_hash": row["payload_hash"],
        "expires_at": row["expires_at"],
        "status": row["status"],
    }


def prune_expired_coach_proposals(db: Any, now: float) -> int:
    """Delete expired authorization artifacts, leaving durable plan drafts alone."""
    return db.execute(
        "DELETE FROM coach_action_proposals WHERE expires_at<=?", (now,)
    ).rowcount


class CoachProposalCreationService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        sync_state_repository: SyncStateRepository,
        *,
        ttl_seconds: int = COACH_ACTION_TTL_SECONDS,
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str] = _utc_now,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._database_manager = database_manager
        self._sync_state_repository = sync_state_repository
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory

    def create(self, values: Any, session_csrf_hash: str) -> dict[str, Any]:
        action_type, target_system, object_ids, diff, payload = (
            validated_coach_action_preview_input(values)
        )
        if action_type == "delete_duplicate_intervals_activity":
            validate_duplicate_delete(
                payload,
                latest_wahoo_garmin_duplicate(
                    self._sync_state_repository.latest_snapshot() or {}
                ),
            )

        proposal_id = str(self._uuid_factory())
        expires_at = self._now() + self._ttl_seconds
        created_at = self._utc_now()
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_action_proposals "
                "(id, session_csrf_hash, action_type, target_system, object_ids, "
                "diff, payload, payload_hash, status, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preview', ?, ?)",
                (
                    proposal_id,
                    str(session_csrf_hash),
                    action_type,
                    target_system,
                    json.dumps(object_ids, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(diff, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    coach_action_hash(payload),
                    expires_at,
                    created_at,
                ),
            )
            row = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            result = {
                "status": "preview",
                "proposed_action": coach_action_view(dict(row)),
            }
        return result


class CoachProposalReadService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._database_manager = database_manager
        self._now = now

    def current(self, session_csrf_hash: str) -> list[dict[str, Any]]:
        if not session_csrf_hash:
            return []
        with self._database_manager.unit_of_work() as db:
            prune_expired_coach_proposals(db, self._now())
            rows = db.execute(
                "SELECT * FROM coach_action_proposals "
                "WHERE session_csrf_hash=? AND status IN ('preview', 'ready') "
                "AND expires_at>? ORDER BY created_at DESC LIMIT 30",
                (session_csrf_hash, self._now()),
            ).fetchall()
            return [coach_action_view(row) for row in rows]


class CoachProposalConfirmationService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        *,
        now: Callable[[], float] = time.time,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self._database_manager = database_manager
        self._now = now
        self._token_factory = token_factory

    def confirm(self, proposal_id: Any, session_csrf_hash: str) -> dict[str, Any]:
        normalized_id = str(proposal_id or "").strip()
        if not re.fullmatch(r"[0-9a-f-]{36}", normalized_id):
            raise AppError(400, "Ungültige Aktionsvorschau.")
        token = self._token_factory(32)
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=? AND session_csrf_hash=?",
                (normalized_id, str(session_csrf_hash)),
            ).fetchone()
            if not row:
                raise AppError(404, "Aktionsvorschau nicht gefunden.")
            if row["status"] not in {"preview", "ready"} or float(row["expires_at"]) <= now:
                raise AppError(409, "Die Aktionsvorschau ist abgelaufen oder wurde bereits bestätigt.")
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            confirmed = db.execute(
                "UPDATE coach_action_proposals SET action_token_hash=?, status='ready' "
                "WHERE id=? AND status IN ('preview', 'ready')",
                (token_hash, normalized_id),
            ).rowcount
            if confirmed != 1:
                raise AppError(409, "Die Aktionsvorschau wurde bereits bestÃ¤tigt.")
            updated = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=?", (normalized_id,)
            ).fetchone()
            result = {
                "status": "ready",
                "action_token": token,
                "proposed_action": coach_action_view(dict(updated)),
            }
        return result


class CoachProposalExecutionService:
    """Consume a confirmed, session-bound token before dispatching its action."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        duplicate_activity_service: DuplicateActivityService,
        history_undo_service: HistoryUndoService,
        intervals_client_factory: Callable[[], Any],
        maintenance_gate: MaintenanceGate,
        *,
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str] = _utc_now,
    ) -> None:
        self._database_manager = database_manager
        self._duplicate_activity_service = duplicate_activity_service
        self._history_undo_service = history_undo_service
        self._intervals_client_factory = intervals_client_factory
        self._maintenance_gate = maintenance_gate
        self._now = now
        self._utc_now = utc_now

    def execute(
        self, token: Any, session_csrf_hash: str, payload_hash: Any = None,
    ) -> dict[str, Any]:
        with self._maintenance_gate.operation():
            return self._execute(token, session_csrf_hash, payload_hash)

    def _execute(
        self, token: Any, session_csrf_hash: str, payload_hash: Any,
    ) -> dict[str, Any]:
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
                raise AppError(409, "Das Coach-Aktionstoken ist ungültig, abgelaufen oder bereits verwendet.")
            if float(row["expires_at"]) <= now:
                raise AppError(409, "Das Coach-Aktionstoken ist abgelaufen.")
            if payload_hash is not None and str(payload_hash) != str(row["payload_hash"]):
                raise AppError(409, "Der bestätigte Aktions-Payload wurde verändert.")
            consumed = db.execute(
                "UPDATE coach_action_proposals SET status='used', used_at=? WHERE id=? AND status='ready'",
                (self._utc_now(), row["id"]),
            ).rowcount
            if consumed != 1:
                raise AppError(409, "Das Coach-Aktionstoken wurde bereits verwendet.")
            action_type = str(row["action_type"])
            payload = json.loads(row["payload"])

        if action_type == "delete_duplicate_intervals_activity":
            result = {
                "ok": True,
                **self._duplicate_activity_service.delete(
                    payload, self._intervals_client_factory()
                ),
            }
        elif action_type == "undo_change":
            result = self._history_undo_service.apply(payload)
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
