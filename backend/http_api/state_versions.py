"""Read-only public version markers for browser state projections."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.athlete.profile import ProfileService
from backend.athlete.state_version_data import StateVersionDataService
from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager


class StateVersionService:
    """Build the current public version markers from local durable state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_service: Any,
        profile_service: ProfileService,
    ) -> None:
        self._database_manager = database_manager
        self._state_version_data = StateVersionDataService(key_value_service)
        self._profile_service = profile_service

    def versions(self) -> dict[str, str]:
        with self._database_manager.reader() as db:
            state = self._state_version_data.read(db)
            profile = self._profile_service.get_from_db(db)

        counters = state["counters"]
        # Each finished Garmin or Wahoo sync moves these markers.
        provider_syncs = (
            f"{state['last_garmin_sync'] or ''}:{state['last_wahoo_sync'] or ''}"
        )
        profile_hash = hashlib.sha256(
            json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "activities": f"{provider_syncs}:{counters['activities']['count']}",
            "performance": f"{provider_syncs}:{counters['observations']['count']}",
            ProviderId.GARMIN.value: f"{state['last_garmin_sync'] or ''}",
            "chat": f"{counters['message']['latest']}:{counters['message']['count']}",
            "library": f"{counters['library']['latest']}:{counters['library']['count']}",
            "checkins": f"{counters['checkins']['latest']}:{counters['checkins']['count']}",
            "activity_feedback": f"{counters['feedback']['latest']}:{counters['feedback']['count']}",
            "profile": profile_hash,
            "plan": f"{state['last_calendar_sync'] or ''}:{counters['library']['latest']}:{counters['planned']['latest']}:{counters['checkins']['latest']}",
        }
