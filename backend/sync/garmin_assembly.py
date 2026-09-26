"""Composition for Garmin synchronization and read projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.config import Config
from backend.observability import Redactor
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.providers import garmin as garmin_provider
from backend.sync import garmin
from backend.sync.garmin_projection_service import GarminProjectionService
from backend.sync import garmin_service
from backend.sync.garmin_service import (
    GarminRemoteReader,
    GarminSyncCoordination,
    GarminSyncLifecycleState,
    GarminSyncService,
    GarminSyncSource,
    shared_garmin_sync_lock,
)
from backend.sync.status import SyncOperationStateWriter
from backend.sync.state import SyncStateRepository


class GarminAssembly:
    """Resolve Garmin services from the active application resources."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        root: Path,
        database_manager: Callable[[], Any],
        key_values: Any,
        sync_state_repository: Callable[[], SyncStateRepository],
        daily_sync_marker_service: Callable[[], Any],
        redactor: Redactor,
        logger: Any,
        diagnostic_capture: Any,
        athlete_clock: Any,
        utc_now: Callable[[], datetime],
        datetime_now: Callable[[], datetime],
        earliest_date: date,
        sync_chunk_days: int,
        all_sync_days: int,
        resync_gate: Any,
        operation_observer: Callable[[], Any],
        event_buffer: Any,
        lock_wait_seconds: int,
        morning_body_battery_service: Callable[[], MorningBodyBatteryService],
    ) -> None:
        self._config = config
        self._root = root
        self._database_manager = database_manager
        self._key_values = key_values
        self._sync_state_repository = sync_state_repository
        self._daily_sync_marker_service = daily_sync_marker_service
        self._redactor = redactor
        self._logger = logger
        self._diagnostic_capture = diagnostic_capture
        self._athlete_clock = athlete_clock
        self._utc_now = utc_now
        self._datetime_now = datetime_now
        self._earliest_date = earliest_date
        self._sync_chunk_days = sync_chunk_days
        self._all_sync_days = all_sync_days
        self._resync_gate = resync_gate
        self._operation_observer = operation_observer
        self._event_buffer = event_buffer
        self._lock_wait_seconds = lock_wait_seconds
        self._morning_body_battery_service = morning_body_battery_service

    def fixture_loader(self) -> garmin.GarminFixtureLoader:
        """Create a fixture reader using the current configuration and clock."""
        return garmin.GarminFixtureLoader(
            self._config(), self._root, self._athlete_clock.now, self._utc_now,
            self._earliest_date, self._all_sync_days,
        )

    def client_factory(self) -> garmin_provider.GarminClientFactory:
        """Create the lazy optional Garmin SDK boundary."""
        return garmin_provider.GarminClientFactory()

    def payload_service(self) -> garmin.GarminPayloadService:
        """Compose local Garmin snapshot reads and payload preparation."""
        return garmin.GarminPayloadService(
            self._database_manager(), self._key_values,
            self._sync_state_repository(),
            lambda: self._athlete_clock.now().date(),
        )

    def sync_state_service(self) -> garmin.GarminSyncStateService:
        """Compose Garmin sync state and payload persistence."""
        return garmin.GarminSyncStateService(
            self._database_manager(), self._key_values,
            self._sync_state_repository(), self._daily_sync_marker_service(),
            self._redactor, self._utc_now, self._datetime_now,
        )

    def remote_reader(self) -> GarminRemoteReader:
        """Compose authenticated Garmin SDK reads without contacting Garmin."""
        return GarminRemoteReader(
            self._config(), self.client_factory(), self.sync_state_service(),
            self._diagnostic_capture, self._redactor.redact_text, self._logger,
            self._utc_now, lambda: self._athlete_clock.now().date(),
            self._earliest_date, self._sync_chunk_days, self._all_sync_days,
        )

    def sync_service(self) -> GarminSyncService:
        """Compose the Garmin synchronization use case."""
        return garmin_service.GarminSyncService(
            GarminSyncSource(
                self.fixture_loader(), self.remote_reader(), self._earliest_date,
                lambda: self._athlete_clock.now().date(),
            ),
            self.payload_service(), self.sync_state_service(),
            SyncOperationStateWriter(
                self._database_manager(), self._key_values, self._event_buffer,
                self._redactor.redact_text,
            ),
            self._operation_observer(),
            GarminSyncCoordination(
                shared_garmin_sync_lock(), self._resync_gate,
                wait_seconds=self._lock_wait_seconds,
            ),
            GarminSyncLifecycleState(
                self._database_manager(), self._key_values, self._utc_now,
                self._logger,
            ),
        )

    def projection_service(self) -> GarminProjectionService:
        """Compose public and Coach projections over current Garmin state."""
        return GarminProjectionService(
            self._config(), self.payload_service(), self.sync_service(),
            self.sync_state_service(), self._sync_state_repository(),
            self._morning_body_battery_service(), self.client_factory(),
            self._database_manager(), self._key_values, self._redactor,
            self._athlete_clock.now,
        )
