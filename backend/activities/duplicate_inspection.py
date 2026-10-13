"""Read the newest Wahoo/Garmin duplicate pair through the canonical activity rows."""

from __future__ import annotations

from typing import Any

from backend.activities.duplicates import latest_wahoo_garmin_duplicate_from_rows
from backend.runtime.ports import ActivityRowReader, ProviderSnapshotReader


class DuplicateInspector:
    """Find the current duplicate pair from injected canonical row and snapshot ports.

    The snapshot only supplies the sync time that the duplicate manifest records;
    the activities themselves come from the canonical selector, so a removed
    duplicate disappears once it is tombstoned.
    """

    def __init__(
        self,
        database_manager: Any,
        snapshot_reader: ProviderSnapshotReader,
        row_reader: ActivityRowReader,
    ) -> None:
        self._database_manager = database_manager
        self._snapshot_reader = snapshot_reader
        self._row_reader = row_reader

    def latest(self) -> dict[str, Any] | None:
        """Return the newest exact-source ride pair, always keeping Wahoo canonical."""
        with self._database_manager.unit_of_work() as db:
            snapshot = self._snapshot_reader.latest_snapshot(db)
            rows = self._row_reader.activity_rows(db)
        synced_at = snapshot.get("synced_at") if isinstance(snapshot, dict) else None
        return latest_wahoo_garmin_duplicate_from_rows(
            rows, snapshot_synced_at=synced_at
        )
