"""Read-only public version markers for browser state projections."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.athlete.profile import ProfileService
from backend.athlete.state_version_data import StateVersionDataService
from backend.db import DatabaseManager


class StateVersionService:
    """Build the current public version markers from local durable state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_service: Any,
        snapshot_repository: Any,
        profile_service: ProfileService,
    ) -> None:
        self._database_manager = database_manager
        self._state_version_data = StateVersionDataService(
            key_value_service, snapshot_repository
        )
        self._profile_service = profile_service

    def versions(
        self, snapshot_metadata: dict[str, Any] | None = None
    ) -> dict[str, str]:
        with self._database_manager.reader() as db:
            state = self._state_version_data.read(db, snapshot_metadata)
            profile = self._profile_service.get_from_db(db)

        snapshot = state["snapshot"]
        counters = state["counters"]

        synced_at = snapshot.get("synced_at") or ""
        profile_hash = hashlib.sha256(
            json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "activities": f"{synced_at}:{snapshot.get('recent_activity_count', 0)}",
            "performance": f"{state['last_performance_refresh'] or synced_at}",
            "garmin": f"{state['last_garmin_sync'] or ''}",
            "chat": f"{counters['message']['latest']}:{counters['message']['count']}",
            "library": f"{counters['library']['latest']}:{counters['library']['count']}",
            "checkins": f"{counters['checkins']['latest']}:{counters['checkins']['count']}",
            "activity_feedback": f"{counters['feedback']['latest']}:{counters['feedback']['count']}",
            "profile": profile_hash,
            "plan": f"{synced_at}:{state['last_calendar_sync'] or ''}:{counters['library']['latest']}:{counters['planned']['latest']}:{counters['checkins']['latest']}",
        }
