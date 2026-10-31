"""Read local change history and reconstruct its prior local state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from backend import change_history
from backend.athlete.profile import DEFAULT_PROFILE, normalize_profile
from backend.errors import AppError


class ChangeHistoryService:
    def __init__(
        self,
        database_manager: Any,
        profile_repository: Any,
        zone_service: Any | None = None,
        feedback_service: Any | None = None,
    ):
        self._database_manager = database_manager
        self._profile_repository = profile_repository
        self._zone_service = zone_service
        self._feedback_service = feedback_service

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        # Retention is enforced on read in SQL; recording a change prunes rows.
        cutoff = (
            datetime.now(UTC) - timedelta(days=change_history.RETENTION_DAYS)
        ).isoformat()
        with self._database_manager.read_snapshot() as db:
            rows = db.execute(
                "SELECT id, entity_type, entity_id, action, source, created_at, "
                "before_hash, after_hash, diff FROM change_history "
                "WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                (cutoff, max(1, min(int(limit), change_history.MAX_ROWS))),
            ).fetchall()
        return [change_history.public_view(dict(row)) for row in rows]

    def current(
        self, db: Any, entity_type: str, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if entity_type == "profile":
            payload = self._profile_repository.get(db)
            try:
                value = normalize_profile(json.loads(payload or "{}"))
            except TypeError, json.JSONDecodeError:
                value = dict(DEFAULT_PROFILE)
        elif entity_type == "zone_configuration" and self._zone_service is not None:
            return self._zone_service.current(db, entity_id)
        elif entity_type == "activity_feedback" and self._feedback_service is not None:
            return self._feedback_service.current(db, entity_id)
        else:
            value = self._current_record(db, entity_type, entity_id)
        return value, change_history.audit_projection(entity_type, value)

    @staticmethod
    def _current_record(
        db: Any, entity_type: str, entity_id: str
    ) -> dict[str, Any] | None:
        queries = {
            "workout_library": "SELECT * FROM workout_library WHERE local_id=?",
            "planned_unit": "SELECT * FROM planned_units WHERE local_id=?",
            "competition": "SELECT * FROM competitions WHERE id=?",
            "training_plan": "SELECT * FROM training_plans WHERE id=?",
        }
        query = queries.get(entity_type)
        if query is None:
            raise AppError(400, "Unbekannte lokale Änderung.")
        row = db.execute(query, (entity_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def target(
        row: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            diff = json.loads(row.get("diff") or "{}")
        except (TypeError, ValueError) as exc:
            raise AppError(409, "Die Änderungshistorie ist beschädigt.") from exc
        fields = diff.get("fields") if isinstance(diff, dict) else None
        if not isinstance(fields, dict):
            raise AppError(
                409, "Die Änderungshistorie enthält keinen wiederherstellbaren Diff."
            )
        if row.get("action") == "create":
            return None, None
        if row.get("action") not in {"update", "delete"}:
            raise AppError(
                409, "Diese Änderung kann nicht erneut zurückgenommen werden."
            )
        # Rows recorded before schema version 16 name planning fields with their
        # former keys; the restore target uses the current ones.
        target = change_history.current_audit_fields(
            str(row.get("entity_type") or ""),
            {
                field: change.get("before")
                for field, change in fields.items()
                if isinstance(change, dict) and "before" in change
            },
        )
        return target, target
