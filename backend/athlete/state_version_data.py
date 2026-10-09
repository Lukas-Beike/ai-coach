"""Read durable values used by public athlete-state version markers."""

from __future__ import annotations

from typing import Any

from backend.db.repositories import StateVersionRepository


class StateVersionDataService:
    def __init__(
        self,
        key_values: Any,
        snapshots: Any,
        versions: StateVersionRepository | None = None,
    ) -> None:
        self._key_values = key_values
        self._snapshots = snapshots
        self._versions = versions or StateVersionRepository()

    def read(self, db: Any, snapshot_metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "snapshot": snapshot_metadata or self._snapshots.latest_metadata(db),
            "counters": self._versions.counters(db),
            "last_performance_refresh": self._key_values.get_in_transaction(
                db, "last_performance_refresh_at"
            ),
            "last_garmin_sync": self._key_values.get_in_transaction(
                db, "last_garmin_sync_at"
            ),
            "last_calendar_sync": self._key_values.get_in_transaction(
                db, "last_external_calendar_sync_at"
            ),
        }
