"""Composition of completed-activity reads and performance analysis."""

from collections.abc import Callable
from typing import Any

from backend.activities.detail_store import ActivityDetailStore
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.runtime.ports import ProviderSnapshotReader


class ActivityReadAssembly:
    def __init__(
        self,
        database_manager: Callable[[], Any],
        snapshot_reader: ProviderSnapshotReader,
        feedback_service: Callable[[], Any],
        read_equipment: Callable[[], dict[str, Any]],
    ) -> None:
        self._database_manager = database_manager
        self._snapshot_reader = snapshot_reader
        self._feedback_service = feedback_service
        self._read_equipment = read_equipment

    def activity_read(self) -> ActivityAnalysisReadService:
        manager = self._database_manager()
        return ActivityAnalysisReadService(
            manager,
            self._snapshot_reader,
            self._feedback_service(),
            ActivityDetailStore(manager),
            read_equipment=self._read_equipment,
        )
