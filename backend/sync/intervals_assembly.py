"""Composition for the read-only Intervals synchronization pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from backend.athlete.clock import AthleteLocalClock
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.intervals import IntervalsApiClient
from backend.sync.daily import DailySyncMarkerService
from backend.sync.gates import ProviderResyncGate
from backend.sync.intervals import (
    IntervalsSnapshotReader,
    IntervalsSnapshotService,
    IntervalsSyncJournal,
    IntervalsSyncRuntime,
    IntervalsSyncService,
    IntervalsSyncStatus,
    IntervalsSyncWorkflow,
)
from backend.sync.performance import (
    PerformanceRefreshFollowupService,
    PerformanceRefreshService,
)
from backend.sync.state import SyncStateRepository
from backend.sync.status import SyncOperationStateWriter


@dataclass(frozen=True)
class IntervalsProviderDependencies:
    config: Callable[[], Config]
    request: Callable[[], Callable[..., Any]]
    athlete_clock: Callable[[], AthleteLocalClock]
    utc_now: Callable[[], str]


@dataclass(frozen=True)
class IntervalsPersistenceDependencies:
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    state_repository: Callable[[], SyncStateRepository]
    daily_markers: Callable[[], DailySyncMarkerService]
    event_buffer: Any
    redact_text: Callable[[str], str]
    logger: logging.Logger


@dataclass(frozen=True)
class IntervalsOperationDependencies:
    operation_observer: Callable[[], Any]
    resync_gate: ProviderResyncGate
    sync_lock: Any
    sync_job_queue: Callable[[], Any]


@dataclass(frozen=True)
class IntervalsLibraryDependencies:
    remote_planned_unit_reconciler: Callable[[], Any]
    workout_library_refresh_service: Callable[[], Any]
    workout_library_service: Callable[[], Any]


@dataclass(frozen=True)
class IntervalsWindowSettings:
    sync_period_defaults: Mapping[str, int]
    all_sync_days: int
    sync_chunk_days: int
    sync_earliest_date: date
    calendar_history_days: int
    calendar_future_days: int


@dataclass(frozen=True)
class IntervalsWaitSettings:
    performance_wait_seconds: int
    poll_seconds: float


class IntervalsSyncAssembly:
    """Create Intervals refresh and synchronization services on demand."""

    @dataclass(frozen=True)
    class Inputs:
        provider: IntervalsProviderDependencies
        persistence: IntervalsPersistenceDependencies
        operations: IntervalsOperationDependencies
        library: IntervalsLibraryDependencies
        window: IntervalsWindowSettings
        waits: IntervalsWaitSettings

    def __init__(self, *, dependencies: "IntervalsSyncAssembly.Inputs") -> None:
        provider = dependencies.provider
        persistence = dependencies.persistence
        operations = dependencies.operations
        library = dependencies.library
        window = dependencies.window
        waits = dependencies.waits
        self._config = provider.config
        self._request = provider.request
        self._athlete_clock = provider.athlete_clock
        self._utc_now = provider.utc_now
        self._database_manager = persistence.database_manager
        self._key_values = persistence.key_values
        self._state_repository = persistence.state_repository
        self._daily_markers = persistence.daily_markers
        self._event_buffer = persistence.event_buffer
        self._redact_text = persistence.redact_text
        self._logger = persistence.logger
        self._operation_observer = operations.operation_observer
        self._intervals_resync_gate = operations.resync_gate
        self._intervals_sync_lock = operations.sync_lock
        self._sync_job_queue = operations.sync_job_queue
        self._remote_planned_unit_reconciler = library.remote_planned_unit_reconciler
        self._workout_library_refresh_service = library.workout_library_refresh_service
        self._workout_library_service = library.workout_library_service
        self._sync_period_defaults = window.sync_period_defaults
        self._all_sync_days = window.all_sync_days
        self._sync_chunk_days = window.sync_chunk_days
        self._sync_earliest_date = window.sync_earliest_date
        self._calendar_history_days = window.calendar_history_days
        self._calendar_future_days = window.calendar_future_days
        self._performance_wait_seconds = waits.performance_wait_seconds
        self._poll_seconds = waits.poll_seconds

    def performance_service(self) -> PerformanceRefreshService:
        """Create targeted Intervals performance refresh persistence."""
        return PerformanceRefreshService(
            self._config(),
            self._database_manager(),
            self._state_repository(),
            self._key_values,
            self.snapshot_reader(),
            self._event_buffer,
            self._redact_text,
            self._logger,
            self._operation_observer(),
            self._intervals_resync_gate,
        )

    def snapshot_reader(self) -> IntervalsSnapshotReader:
        """Create a reader using the current provider configuration."""
        config = self._config()
        api_client = IntervalsApiClient(
            api_key=config.intervals_api_key,
            request=self._request(),
        )
        return IntervalsSnapshotReader(
            config,
            api_client,
            self._state_repository(),
            self._athlete_clock().now,
            self._utc_now,
            self._sync_earliest_date,
            self._sync_chunk_days,
            self._all_sync_days,
            self._calendar_history_days,
            self._calendar_future_days,
        )

    def performance_followup(self) -> PerformanceRefreshFollowupService:
        """Create the queueing and polling service for performance refreshes."""
        return PerformanceRefreshFollowupService(
            self._config(),
            self._sync_job_queue(),
            self.performance_service(),
            self._database_manager(),
            self._key_values,
            self._logger,
            wait_seconds=self._performance_wait_seconds,
            poll_seconds=self._poll_seconds,
        )

    def snapshot_service(self) -> IntervalsSnapshotService:
        """Create snapshot persistence and sync-window handling."""
        return IntervalsSnapshotService(
            self._database_manager(),
            self._key_values,
            self._state_repository(),
            self._remote_planned_unit_reconciler(),
            self._workout_library_refresh_service(),
            self._workout_library_service(),
            self._redact_text,
            self._athlete_clock().now,
            self._sync_earliest_date,
            self._sync_chunk_days,
            self._all_sync_days,
        )

    def sync_service(self) -> IntervalsSyncService:
        """Create the full read-only Intervals synchronization use case."""
        status = IntervalsSyncStatus(self._database_manager(), self._key_values)
        return IntervalsSyncService(
            self._config(),
            IntervalsSyncWorkflow(
                self.snapshot_reader(),
                self.snapshot_service(),
                self._state_repository(),
                self._daily_markers(),
                self._sync_period_defaults,
                self._all_sync_days,
            ),
            self.performance_followup(),
            status,
            IntervalsSyncJournal(
                status,
                SyncOperationStateWriter(
                    self._database_manager(),
                    self._key_values,
                    self._event_buffer,
                    self._redact_text,
                ),
                self._redact_text,
                self._logger,
                self._utc_now,
            ),
            IntervalsSyncRuntime(
                self._intervals_sync_lock,
                self._operation_observer(),
                self._intervals_resync_gate,
                wait_seconds=self._performance_wait_seconds,
            ),
        )
