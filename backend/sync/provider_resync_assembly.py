"""Composition for competition synchronization and provider resync."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.transport_assembly import ProviderTransportAssembly
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


class ProviderResyncAssembly:
    """Create the competition sync and full provider resync use cases."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        intervals_client: Callable[[], Any],
        competition_service: Callable[[], Any],
        intervals_sync_service: Callable[[], Any],
        garmin_sync_service: Callable[[], Any],
        database_manager: Callable[[], DatabaseManager],
        key_values: KeyValueRepository,
        event_buffer: StateEventBuffer,
        redactor: Any,
        logger: logging.Logger,
        utc_now: Callable[[], str],
        uuid_factory: Callable[[], str],
        monotonic: Callable[[], float],
        operation_observer: Callable[[], SyncOperationObserver],
        intervals_resync_gate: ProviderResyncGate,
        garmin_resync_gate: ProviderResyncGate,
        all_sync_days: int,
    ) -> None:
        self._config = config
        self._intervals_client = intervals_client
        self._competition_service = competition_service
        self._intervals_sync_service = intervals_sync_service
        self._garmin_sync_service = garmin_sync_service
        self._database_manager = database_manager
        self._key_values = key_values
        self._event_buffer = event_buffer
        self._redactor = redactor
        self._logger = logger
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._monotonic = monotonic
        self._operation_observer = operation_observer
        self._intervals_resync_gate = intervals_resync_gate
        self._garmin_resync_gate = garmin_resync_gate
        self._all_sync_days = all_sync_days

    def competition_reconciler(self) -> CompetitionSyncReconciler:
        """Create local persistence for remote competition reconciliation."""
        return CompetitionSyncReconciler(self._database_manager(), uuid.uuid4)

    def competition_sync_service(self) -> CompetitionSyncService:
        """Create the authorized competition synchronization use case."""
        return CompetitionSyncService(
            self._config(),
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
                self._config(),
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
