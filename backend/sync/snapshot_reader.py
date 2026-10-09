from __future__ import annotations

from typing import Any

from backend.runtime.ports import ProviderSnapshotReader
from backend.sync.snapshots import latest_snapshot


class SnapshotRepositoryReader(ProviderSnapshotReader):
    def __init__(self, repository: Any):
        self._repository = repository

    def latest_snapshot(self, db: Any) -> dict[str, Any] | None:
        return latest_snapshot(db, self._repository)
