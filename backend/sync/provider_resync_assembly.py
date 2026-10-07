"""Composition for competition synchronization and provider resync."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.runtime.events import StateEventBuffer
from backend.sync.competitions import CompetitionSyncReconciler, CompetitionSyncService
from backend.sync.full_resync import (
    FullProviderResyncService,
    FullResyncOperationJournal,
    FullResyncProviderExecution,
    FullResyncStateStore,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver


@dataclass(frozen=True)
class CompetitionSyncOwners:
    config: Callable[[], Config]
    intervals_client: Callable[[], Any]
    competition_service: Callable[[], Any]


@dataclass(frozen=True)
class ResyncProviderOwners:
    config: Callable[[], Config]
    intervals_sync_service: Callable[[], Any]
    garmin_sync_service: Callable[[], Any]
    intervals_resync_gate: ProviderResyncGate
    garmin_resync_gate: ProviderResyncGate
    all_sync_days: int


@dataclass(frozen=True)
class ProviderResyncPersistence:
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    event_buffer: StateEventBuffer
    redactor: Any


@dataclass(frozen=True)
class ProviderResyncRuntime:
    logger: logging.Logger
    utc_now: Callable[[], str]
    uuid_factory: Callable[[], str]
    monotonic: Callable[[], float]
    operation_observer: Callable[[], SyncOperationObserver]


class ProviderResyncAssembly:
    """Create the competition sync and full provider resync use cases."""

    @dataclass(frozen=True)
    class Inputs:
        competition: CompetitionSyncOwners
        resync: ResyncProviderOwners
        persistence: ProviderResyncPersistence
        runtime: ProviderResyncRuntime

    def __init__(self, *, dependencies: ProviderResyncAssembly.Inputs) -> None:
        competition = dependencies.competition
        resync = dependencies.resync
        persistence = dependencies.persistence
        runtime = dependencies.runtime
        self._competition_config = competition.config
        self._intervals_client = competition.intervals_client
        self._competition_service = competition.competition_service
        self._resync_config = resync.config
        self._intervals_sync_service = resync.intervals_sync_service
        self._garmin_sync_service = resync.garmin_sync_service
        self._intervals_resync_gate = resync.intervals_resync_gate
        self._garmin_resync_gate = resync.garmin_resync_gate
        self._all_sync_days = resync.all_sync_days
        self._database_manager = persistence.database_manager
        self._key_values = persistence.key_values
        self._event_buffer = persistence.event_buffer
        self._redactor = persistence.redactor
        self._logger = runtime.logger
        self._utc_now = runtime.utc_now
        self._uuid_factory = runtime.uuid_factory
        self._monotonic = runtime.monotonic
        self._operation_observer = runtime.operation_observer

    def competition_reconciler(self) -> CompetitionSyncReconciler:
        """Create local persistence for remote competition reconciliation."""
        return CompetitionSyncReconciler(self._database_manager(), uuid.uuid4)

    def competition_sync_service(self) -> CompetitionSyncService:
        """Create the authorized competition synchronization use case."""
        return CompetitionSyncService(
            self._competition_config(),
            self._intervals_client,
            self.competition_reconciler(),
            self._competition_service(),
            self._database_manager(),
            self._key_values,
            self._event_buffer,
            self._redactor,
            self._logger,
            self._utc_now,
        )

    def full_resync_service(self) -> FullProviderResyncService:
        """Create full provider resynchronization over current service owners."""
        observer = self._operation_observer()
        return FullProviderResyncService(
            FullResyncProviderExecution(
                self._resync_config(),
                self._intervals_sync_service(),
                self._garmin_sync_service(),
                self.competition_sync_service(),
                self._intervals_resync_gate,
                self._garmin_resync_gate,
                self._all_sync_days,
            ),
            FullResyncStateStore(self._database_manager(), self._key_values),
            FullResyncOperationJournal(
                observer,
                self._logger,
                self._redactor.redact_text,
                self._utc_now,
                self._monotonic,
                self._uuid_factory,
            ),
        )
