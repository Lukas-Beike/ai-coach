"""Composition of completed-activity reads and performance analysis."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from backend.activities.activity_reference import ActivityReferences
from backend.activities.detail_store import ActivityDetailStore
from backend.canonical.vocabulary import ProviderId
from backend.http_api.compact_activity_rows import CompactActivityRows
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.runtime.ports import (
    ActivityRowAndSummaryReader,
    CanonicalReadStatus,
    ObservationReader,
    ProviderCoverageReader,
    ProviderSnapshotReader,
)
from backend.sync.canonical_table_reader import CanonicalTableReader

_PROVIDER_IDS = frozenset(provider.value for provider in ProviderId)


@dataclass(frozen=True)
class ActivityReadSources:
    """Where the activity reads get their sync time, rows and observations.

    ``serving`` reports the canonical read state, so the detail's performance
    block is marked pending or carries the compact-only activity gap.
    """

    snapshot_reader: ProviderSnapshotReader
    row_reader: Callable[[], ActivityRowAndSummaryReader]
    observation_reader: Callable[[], ObservationReader]
    coverage: Callable[[], ProviderCoverageReader]
    serving: Callable[[], CanonicalReadStatus] | None = None


class ActivityReadAssembly:
    def __init__(
        self,
        database_manager: Callable[[], Any],
        sources: ActivityReadSources,
        feedback_service: Callable[[], Any],
        read_equipment: Callable[[str], dict[str, Any]],
        *,
        refreshable_providers: Callable[[], Iterable[str]] = tuple,
    ) -> None:
        """``refreshable_providers`` names the providers that can load details now."""
        self._database_manager = database_manager
        self._snapshot_reader = sources.snapshot_reader
        self._row_reader = sources.row_reader
        self._observation_reader = sources.observation_reader
        self._coverage = sources.coverage
        self._serving = sources.serving
        self._feedback_service = feedback_service
        self._read_equipment = read_equipment
        self._refreshable_providers = refreshable_providers

    def activity_read(self) -> ActivityAnalysisReadService:
        manager = self._database_manager()
        return ActivityAnalysisReadService(
            manager,
            self._snapshot_reader,
            CompactActivityRows(self._row_reader()),
            self._feedback_service(),
            ActivityDetailStore(manager),
            read_equipment=self._read_equipment,
            references=ActivityReferences(manager),
            canonical=self._canonical_source(),
            summary_rows=self._row_reader(),
            session_records=CanonicalTableReader().session_activities,
            refreshable=self._refreshable,
        )

    def _refreshable(self) -> frozenset[ProviderId]:
        return frozenset(
            ProviderId(provider)
            for provider in self._refreshable_providers()
            if provider in _PROVIDER_IDS
        )

    def _canonical_source(self) -> CanonicalPerformanceSource:
        return CanonicalPerformanceSource(
            self._database_manager,
            self._observation_reader,
            serving=self._serving,
            activity_summaries=self._row_reader,
            coverage=self._coverage,
        )
