"""Authorized deletion of duplicate Intervals.icu activities."""

from __future__ import annotations

from typing import Any

from backend.activities.duplicates import (
    latest_wahoo_garmin_duplicate,
    remove_activity_from_snapshot,
    validate_duplicate_delete,
)
from backend.runtime.ports import ProviderSnapshotReader


class DuplicateActivityService:
    """Own the remote-delete use case and its local snapshot projection."""

    def __init__(
        self,
        database_manager: Any,
        snapshot_repository: Any,
        snapshot_reader: ProviderSnapshotReader,
        clock: Any,
        event_buffer: Any,
    ) -> None:
        self._database_manager = database_manager
        self._snapshot_repository = snapshot_repository
        self._snapshot_reader = snapshot_reader
        self._clock = clock
        self._event_buffer = event_buffer

    def _latest_snapshot(self) -> dict[str, Any] | None:
        with self._database_manager.unit_of_work() as db:
            return self._snapshot_reader.latest_snapshot(db)

    def delete(self, payload: Any, intervals_client: Any) -> dict[str, Any]:
        """Delete the confirmed Garmin copy and retain the Wahoo activity."""
        current = latest_wahoo_garmin_duplicate(self._latest_snapshot() or {})
        canonical_id, duplicate_id = validate_duplicate_delete(payload, current)

        intervals_client.delete_activity(duplicate_id)

        synced_at = self._clock()
        with self._database_manager.unit_of_work() as db:
            snapshot = self._snapshot_reader.latest_snapshot(db)
            updated = remove_activity_from_snapshot(
                snapshot,
                duplicate_id,
                synced_at=synced_at,
            )
            if updated is not None:
                self._snapshot_repository.save(db, updated, synced_at)

        self._event_buffer.publish(
            "provider",
            {"provider": "intervals", "status": "duplicate_deleted"},
        )
        return {
            "status": "deleted",
            "deleted_activity_id": duplicate_id,
            "kept_activity_id": canonical_id,
            "kept_source": "Wahoo",
        }
