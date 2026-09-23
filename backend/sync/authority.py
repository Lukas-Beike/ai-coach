"""Local authority decisions before an explicit synchronization."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.db import DatabaseManager
from backend.planning.planned_unit_service import UPDATE_SQL
from backend.planning.revision import PlanningRevisionService
from backend.sync.library import WorkoutLibrarySyncStateService


class PlanningAuthorityService:
    """Make explicitly selected local planning and competition data authoritative."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        workout_library_sync_state_service: WorkoutLibrarySyncStateService,
        planning_revision_service: PlanningRevisionService,
        now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._workout_library_sync_state_service = workout_library_sync_state_service
        self._planning_revision_service = planning_revision_service
        self._now = now

    def pending_plan_push_entries(self) -> list[dict[str, str]]:
        """Return the minimal expected-hash manifest for pending local workouts."""
        _summary, entries, _fingerprint = (
            self._workout_library_sync_state_service.preview()
        )
        return [
            {
                "library_workout_id": str(entry["local_id"]),
                "expected_payload_hash": str(entry["payload_hash"]),
            }
            for entry in entries
            if entry.get("local_id") and entry.get("payload_hash")
        ]

    def mark_planning_authoritative(self, local_ids: list[str] | None = None) -> int:
        """Make selected local planning rows authoritative in one transaction."""
        normalized_ids = {
            str(value).strip() for value in (local_ids or []) if str(value).strip()
        }
        with self._database_manager.unit_of_work() as db:
            now = self._now()
            if normalized_ids:
                placeholders = ",".join("?" for _ in normalized_ids)
                rows = db.execute(
                    "SELECT local_id, payload FROM planned_units "
                    f"WHERE local_id IN ({placeholders})",
                    tuple(sorted(normalized_ids)),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT local_id, payload FROM planned_units "
                    "WHERE sync_state IN ('conflict', 'remote_missing', 'sync_error')"
                ).fetchall()

            changed = sum(self._mark_planning_row(row, now, db) for row in rows)
            if changed:
                self._planning_revision_service.bump(db)
        return changed

    def mark_competitions_authoritative(self) -> int:
        """Choose local competition values for dirty or conflicted rows."""
        with self._database_manager.unit_of_work() as db:
            rows = db.execute(
                "SELECT id, sync_state, sync_conflict FROM competitions "
                "WHERE sync_dirty=1 OR sync_state='conflict'"
            ).fetchall()
            now = self._now()
            for row in rows:
                if self._competition_remote_id_is_missing(row):
                    db.execute(
                        "UPDATE competitions SET intervals_event_id=NULL, sync_dirty=1, "
                        "sync_state='local_override', sync_conflict='', updated_at=? WHERE id=?",
                        (now, row["id"]),
                    )
                else:
                    db.execute(
                        "UPDATE competitions SET sync_dirty=1, sync_state='local_override', "
                        "sync_conflict='', updated_at=? WHERE id=?",
                        (now, row["id"]),
                    )
        return len(rows)

    @staticmethod
    def _mark_planning_row(row: dict[str, Any], now: str, db: Any) -> bool:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict) or payload.get("local_deleted"):
            return False
        payload["sync_status"] = "local"
        db.execute(
            UPDATE_SQL,
            (json.dumps(payload, ensure_ascii=False), now, row["local_id"]),
        )
        return True

    @staticmethod
    def _competition_remote_id_is_missing(row: dict[str, Any]) -> bool:
        if row.get("sync_state") == "remote_missing":
            return True
        try:
            conflict = json.loads(row.get("sync_conflict") or "{}")
        except (TypeError, ValueError):
            return False
        return isinstance(conflict, dict) and conflict.get("type") == "remote_missing"
