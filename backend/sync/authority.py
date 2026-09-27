"""Local authority decisions before an explicit synchronization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from backend.db import DatabaseManager
from backend.errors import AppError
from backend.planning.planned_unit_service import UPDATE_SQL
from backend.planning.revision import PlanningRevisionService
from backend.sync.library import WorkoutLibrarySyncStateService


def competition_push_manifest(db: Any) -> list[dict[str, str]]:
    """Hash exactly the dirty competition rows and pending remote deletions."""
    manifest = []
    for table, key, query in (
        (
            "competition",
            "id",
            "SELECT * FROM competitions WHERE sync_dirty=1 OR sync_state='conflict' ORDER BY id",
        ),
        (
            "tombstone",
            "id",
            "SELECT * FROM competition_sync_tombstones ORDER BY id",
        ),
    ):
        for row in db.execute(query).fetchall():
            values = dict(row)
            digest = hashlib.sha256(
                json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            manifest.append({"type": table, key: str(values[key]), "sha256": digest})
    return manifest


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

    def mark_competitions_authoritative(
        self, expected_manifest: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Choose only the competition state shown in the approved preview."""
        with self._database_manager.unit_of_work() as db:
            if competition_push_manifest(db) != expected_manifest:
                raise AppError(409, "Der Wettkampfbestand hat sich seit der Freigabe geändert.")
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
            manifest = competition_push_manifest(db)
        return manifest

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
