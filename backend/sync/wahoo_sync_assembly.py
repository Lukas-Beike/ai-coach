"""Lazy composition of the Wahoo read synchronization and plan export services."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import ProviderId, Sport
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.performance.current_thresholds import ThresholdKey
from backend.providers.observed_opener import Opener
from backend.providers.wahoo_client import WahooClient
from backend.providers.wahoo_fit_download import download_wahoo_fit
from backend.providers.wahoo_plan_mapping import WahooPlanReferences
from backend.sync.daily import DailySyncMarkerService
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_registry import ProviderRegistry
from backend.sync.stream_backfill import StreamBackfillService
from backend.sync.wahoo_activity_details import WahooActivityDetailImport
from backend.sync.wahoo_connection import WahooConnectionService
from backend.sync.wahoo_library_state import WahooLibraryState
from backend.sync.wahoo_plan_push import WahooPlanPushService
from backend.sync.wahoo_stream_backfill import (
    WAHOO_BATCH_LIMIT,
    WAHOO_REPLAY_DAYS,
    WahooStreamMapping,
    WahooStreamSource,
)
from backend.sync.wahoo_sync import (
    WahooSyncClock,
    WahooSyncService,
    WahooSyncStorage,
)
from backend.sync.wahoo_workout_export import WahooWorkoutExport, plan_references


@dataclass(frozen=True)
class WahooSyncInputs:
    config: Callable[[], Config]
    connection: Callable[[], WahooConnectionService]
    json_request: Callable[[], Callable[..., Any]]
    database_manager: Callable[[], DatabaseManager]
    database_lock: AbstractContextManager[Any]
    key_values: KeyValueRepository
    daily_markers: Callable[[], DailySyncMarkerService]
    observer: Callable[[], SyncOperationObserver]
    registry: ProviderRegistry
    zone_provider: Callable[[], tzinfo | None]
    now: Callable[[], datetime]
    logger: logging.Logger
    redactor: Callable[[str], str]
    resync_gate: ProviderResyncGate
    # ``db -> export thresholds`` (local zones, Garmin, Wahoo) for plan references.
    export_thresholds: Callable[[Any], Mapping[ThresholdKey, Observation]]
    # The oldest day the stream backfill reaches.
    history_earliest_date: date
    # Observes the FIT downloads; without it they run unobserved.
    fit_opener: Callable[[], Opener] | None = None


class WahooSyncAssembly:
    """Share one sync service so its run lock serializes every caller."""

    def __init__(self, inputs: WahooSyncInputs) -> None:
        self._inputs = inputs
        self._service: WahooSyncService | None = None
        self._plan_push: WahooPlanPushService | None = None
        self._details: WahooActivityDetailImport | None = None
        self._lock = threading.Lock()

    def client(self) -> WahooClient:
        """Create a transport bound to the stored, refreshable Wahoo token."""
        inputs = self._inputs
        connection = inputs.connection()
        return WahooClient(
            request=inputs.json_request(),
            access_token=connection.access_token,
            refresh_access_token=connection.refresh_access_token,
            invalidate_access_token=connection.invalidate_access_token,
        )

    def sync_service(self) -> WahooSyncService:
        with self._lock:
            if self._service is None:
                inputs = self._inputs
                self._service = WahooSyncService(
                    config=inputs.config,
                    connection=inputs.connection,
                    source=self.client,
                    storage=WahooSyncStorage(
                        database_manager=inputs.database_manager,
                        database_lock=inputs.database_lock,
                        key_values=inputs.key_values,
                    ),
                    daily_markers=inputs.daily_markers,
                    observer=inputs.observer,
                    registry=inputs.registry,
                    clock=WahooSyncClock(inputs.now, inputs.zone_provider),
                    logger=inputs.logger,
                    gate=inputs.resync_gate,
                    details=self.activity_detail_import,
                )
            return self._service

    def activity_detail_import(self) -> WahooActivityDetailImport:
        """Share one detail importer; it runs only after a sync has committed."""
        with self._lock:
            if self._details is None:
                inputs = self._inputs
                self._details = WahooActivityDetailImport(
                    database_manager=inputs.database_manager,
                    database_lock=inputs.database_lock,
                    key_values=inputs.key_values,
                    download=self.fit_download(),
                    monotonic=time.monotonic,
                    logger=inputs.logger,
                )
            return self._details

    def fit_download(self) -> Callable[[str], bytes]:
        """Return the FIT download, observed when the composition supplies an opener."""
        factory = self._inputs.fit_opener
        if factory is None:
            return download_wahoo_fit
        return lambda url: download_wahoo_fit(url, opener=factory())

    def stream_backfill_service(self) -> StreamBackfillService:
        """Compose the backfill of the FIT streams of past Wahoo workouts."""
        inputs = self._inputs
        return StreamBackfillService(
            provider=ProviderId.WAHOO.value,
            source=WahooStreamSource(
                client=self.client,
                download=self.fit_download(),
            ),
            mapping=WahooStreamMapping(),
            database_manager=inputs.database_manager,
            key_values=inputs.key_values,
            guard=lambda: inputs.database_lock,
            utc_now=lambda: inputs.now().isoformat(),
            configured=self.sync_service().configured,
            earliest_date=inputs.history_earliest_date,
            batch_limit=WAHOO_BATCH_LIMIT,
            operation=inputs.resync_gate.operation,
            replay_days=WAHOO_REPLAY_DAYS,
        )

    def workout_export(self) -> WahooWorkoutExport:
        """Create the library export target; the client resolves per remote call.

        One export serves one push run, so the thresholds are read once per run
        and plan sport, not once per workout.
        """
        cache: dict[Sport, WahooPlanReferences] = {}

        def references(sport: Sport) -> WahooPlanReferences:
            if sport not in cache:
                with self._inputs.database_manager().reader() as db:
                    thresholds = self._inputs.export_thresholds(db)
                cache[sport] = plan_references(thresholds, sport)
            return cache[sport]

        return WahooWorkoutExport(
            self.client, now=self._inputs.now, references=references
        )

    def library_state(self) -> WahooLibraryState:
        """Read-only Wahoo state of library workouts, for the library view."""
        return WahooLibraryState(
            configured=self.sync_service().configured,
            database_manager=self._inputs.database_manager,
            export=self.workout_export,
        )

    def plan_push_service(self) -> WahooPlanPushService:
        """Share one plan-push service so its run lock serializes every caller."""
        configured = self.sync_service().configured
        with self._lock:
            if self._plan_push is None:
                inputs = self._inputs
                self._plan_push = WahooPlanPushService(
                    configured=configured,
                    database_manager=inputs.database_manager,
                    export=self.workout_export,
                    now=inputs.now,
                    redactor=inputs.redactor,
                    gate=inputs.resync_gate,
                )
            return self._plan_push
