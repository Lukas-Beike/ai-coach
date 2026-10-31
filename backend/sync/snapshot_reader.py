from __future__ import annotations

from typing import Any

from backend.providers.snapshot_projection import (
    intervals_snapshot_has_only_compact_rows,
)
from backend.runtime.ports import ProviderSnapshotReader
from backend.sync.snapshots import latest_snapshot


class SnapshotRepositoryReader(ProviderSnapshotReader):
    def __init__(self, repository: Any):
        self._repository = repository

    def latest_snapshot(self, db: Any) -> dict[str, Any] | None:
        return latest_snapshot(db, self._repository)

    def has_only_compact_activity_rows(self, db: Any) -> bool:
        """Return True when the stored snapshot lists activities only in compact form."""
        return intervals_snapshot_has_only_compact_rows(self.latest_snapshot(db))
