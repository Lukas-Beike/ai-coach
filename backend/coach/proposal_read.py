"""Read, confirm, and cancel session-owned Coach proposals."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

from backend.coach.proposal_models import (
    coach_action_view,
    prune_expired_coach_proposals,
)
from backend.db.manager import DatabaseManager
from backend.errors import AppError


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
            if (
                row["status"] not in {"preview", "ready"}
                or float(row["expires_at"]) <= now
            ):
                raise AppError(
                    409,
                    "Die Aktionsvorschau ist abgelaufen oder wurde bereits bestätigt.",
                )
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            confirmed = db.execute(
                "UPDATE coach_action_proposals SET action_token_hash=?, status='ready' "
                "WHERE id=? AND status IN ('preview', 'ready')",
                (token_hash, normalized_id),
            ).rowcount
            if confirmed != 1:
                raise AppError(409, "Die Aktionsvorschau wurde bereits bestätigt.")
            updated = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=?", (normalized_id,)
            ).fetchone()
            result = {
                "status": "ready",
                "action_token": token,
                "proposed_action": coach_action_view(dict(updated)),
            }
        return result

    def cancel(self, proposal_id: Any, session_csrf_hash: str) -> dict[str, Any]:
        """Revoke an unexecuted approval proposal owned by this session."""
        normalized_id = str(proposal_id or "").strip()
        if not re.fullmatch(r"[0-9a-f-]{36}", normalized_id):
            raise AppError(400, "Ungültige Aktionsvorschau.")
        with self._database_manager.unit_of_work() as db:
            changed = db.execute(
                "UPDATE coach_action_proposals SET status='cancelled', action_token_hash=NULL "
                "WHERE id=? AND session_csrf_hash=? AND status IN ('preview', 'ready')",
                (normalized_id, str(session_csrf_hash)),
            ).rowcount
            if changed != 1:
                raise AppError(409, "Die Aktionsvorschau ist nicht mehr offen.")
        return {"status": "cancelled", "proposal_id": normalized_id}
