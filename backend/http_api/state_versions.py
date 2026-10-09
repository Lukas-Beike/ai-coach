"""Read-only public version markers for browser state projections."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.athlete.profile import ProfileService
from backend.db import DatabaseManager
from backend.db.repositories import (
    KeyValueRepository,
    SnapshotRepository,
    StateVersionRepository,
)


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
        self._version_repository = StateVersionRepository()

    def versions(
        self, snapshot_metadata: dict[str, Any] | None = None
    ) -> dict[str, str]:
        with self._database_manager.reader() as db:
            snapshot = snapshot_metadata or self._snapshot_repository.latest_metadata(
                db
            )
            counters = self._version_repository.counters(db)
            last_performance_refresh = self._key_value_repository.get(
                db, "last_performance_refresh_at"
            )
            last_garmin_sync = self._key_value_repository.get(db, "last_garmin_sync_at")
            last_calendar_sync = self._key_value_repository.get(
                db, "last_external_calendar_sync_at"
            )
            profile = self._profile_service.get_from_db(db)

        synced_at = snapshot.get("synced_at") or ""
        profile_hash = hashlib.sha256(
            json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "activities": f"{synced_at}:{snapshot.get('recent_activity_count', 0)}",
            "performance": f"{last_performance_refresh or synced_at}",
            "garmin": f"{last_garmin_sync or ''}",
            "chat": f"{counters['message']['latest']}:{counters['message']['count']}",
            "library": f"{counters['library']['latest']}:{counters['library']['count']}",
            "checkins": f"{counters['checkins']['latest']}:{counters['checkins']['count']}",
            "activity_feedback": f"{counters['feedback']['latest']}:{counters['feedback']['count']}",
            "profile": profile_hash,
            "plan": f"{synced_at}:{last_calendar_sync or ''}:{counters['library']['latest']}:{counters['planned']['latest']}:{counters['checkins']['latest']}",
        }
