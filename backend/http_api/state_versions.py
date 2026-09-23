"""Read-only public version markers for browser state projections."""

from __future__ import annotations

import hashlib
import json

from backend.athlete.profile import ProfileService
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.sync.snapshots import latest_snapshot


class StateVersionService:
    """Build the current public version markers from local durable state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        snapshot_repository: SnapshotRepository,
        profile_service: ProfileService,
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._snapshot_repository = snapshot_repository
        self._profile_service = profile_service

    def versions(self) -> dict[str, str]:
        with self._database_manager.reader() as db:
            snapshot = latest_snapshot(db, self._snapshot_repository) or {}
            message = db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(id), 0) AS latest FROM messages"
            ).fetchone()
            library = db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM workout_library WHERE json_extract(payload, '$.date') IS NULL"
            ).fetchone()
            planned = db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM planned_units"
            ).fetchone()
            checkins = db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM athlete_checkins"
            ).fetchone()
            feedback = db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM activity_feedback"
            ).fetchone()
            last_performance_refresh = self._key_value_repository.get(
                db, "last_performance_refresh_at"
            )
            last_garmin_sync = self._key_value_repository.get(db, "last_garmin_sync_at")
            last_calendar_sync = self._key_value_repository.get(
                db, "last_external_calendar_sync_at"
            )
            profile = self._profile_service.get_from_db(db)

        synced_at = snapshot.get("synced_at") or ""
        recent_activities = snapshot.get("recent_activities")
        profile_hash = hashlib.sha256(
            json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "activities": f"{synced_at}:{len(recent_activities) if isinstance(recent_activities, list) else 0}",
            "performance": f"{last_performance_refresh or synced_at}",
            "garmin": f"{last_garmin_sync or ''}",
            "chat": f"{message['latest']}:{message['count']}",
            "library": f"{library['latest']}:{library['count']}",
            "checkins": f"{checkins['latest']}:{checkins['count']}",
            "activity_feedback": f"{feedback['latest']}:{feedback['count']}",
            "profile": profile_hash,
            "plan": f"{synced_at}:{last_calendar_sync or ''}:{library['latest']}:{planned['latest']}:{checkins['latest']}",
        }
