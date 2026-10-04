"""Composition for Garmin synchronization and read projections."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.config import Config
from backend.observability import Redactor
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.providers import garmin as garmin_provider
from backend.sync import garmin, garmin_service
from backend.sync.garmin_projection_service import GarminProjectionService
from backend.sync.garmin_service import (
    GarminRemoteReader,
    GarminSyncCoordination,
    GarminSyncLifecycleState,
    GarminSyncService,
    GarminSyncSource,
    shared_garmin_sync_lock,
)
from backend.sync.state import SyncStateRepository
from backend.sync.status import SyncOperationStateWriter


@dataclass(frozen=True)
class GarminProviderSettings:
    config: Callable[[], Config]
    root: Path
    athlete_clock: Any
    earliest_date: date
    sync_chunk_days: int
    all_sync_days: int


@dataclass(frozen=True)
class GarminPersistenceOwners:
    database_manager: Callable[[], Any]
    key_values: Any
    sync_state_repository: Callable[[], SyncStateRepository]
    daily_sync_marker_service: Callable[[], Any]
    sync_equipment: Callable[[dict[str, Any]], Any] | None = None


@dataclass(frozen=True)
class GarminSyncTelemetry:
    redactor: Redactor
    logger: Any
    diagnostic_capture: Any
    event_buffer: Any


@dataclass(frozen=True)
class GarminSyncControl:
    utc_now: Callable[[], str]
    datetime_now: Callable[[], datetime]
    resync_gate: Any
    operation_observer: Callable[[], Any]
    lock_wait_seconds: int
    morning_body_battery_service: Callable[[], MorningBodyBatteryService]


class GarminAssembly:
    """Resolve Garmin services from the active application resources."""

    @dataclass(frozen=True)
    class Inputs:
        provider: GarminProviderSettings
        persistence: GarminPersistenceOwners
        telemetry: GarminSyncTelemetry
        control: GarminSyncControl

    def __init__(self, *, dependencies: GarminAssembly.Inputs) -> None:
        provider = dependencies.provider
        persistence = dependencies.persistence
        telemetry = dependencies.telemetry
        control = dependencies.control
        self._config = provider.config
        self._root = provider.root
        self._athlete_clock = provider.athlete_clock
        self._earliest_date = provider.earliest_date
        self._sync_chunk_days = provider.sync_chunk_days
        self._all_sync_days = provider.all_sync_days
        self._database_manager = persistence.database_manager
        self._key_values = persistence.key_values
        self._sync_state_repository = persistence.sync_state_repository
        self._daily_sync_marker_service = persistence.daily_sync_marker_service
        self._sync_equipment = persistence.sync_equipment
        self._redactor = telemetry.redactor
        self._logger = telemetry.logger
        self._diagnostic_capture = telemetry.diagnostic_capture
        self._event_buffer = telemetry.event_buffer
        self._utc_now = control.utc_now
        self._datetime_now = control.datetime_now
        self._resync_gate = control.resync_gate
        self._operation_observer = control.operation_observer
        self._lock_wait_seconds = control.lock_wait_seconds
        self._morning_body_battery_service = control.morning_body_battery_service

    def fixture_loader(self) -> garmin.GarminFixtureLoader:
        """Create a fixture reader using the current configuration and clock."""
        return garmin.GarminFixtureLoader(
            self._config(),
            self._root,
            self._athlete_clock.now,
            self._utc_now,
            self._earliest_date,
            self._all_sync_days,
        )

    def client_factory(self) -> garmin_provider.GarminClientFactory:
        """Create the lazy optional Garmin SDK boundary."""
        return garmin_provider.GarminClientFactory()

    def payload_service(self) -> garmin.GarminPayloadService:
        """Compose local Garmin snapshot reads and payload preparation."""
        return garmin.GarminPayloadService(
            self._database_manager(),
            self._key_values,
            self._sync_state_repository(),
            lambda: self._athlete_clock.now().date(),
        )

    def sync_state_service(self) -> garmin.GarminSyncStateService:
        """Compose Garmin sync state and payload persistence."""
        return garmin.GarminSyncStateService(
            self._database_manager(),
            self._key_values,
            self._sync_state_repository(),
            self._daily_sync_marker_service(),
            self._redactor,
            self._utc_now,
            self._datetime_now,
            self._sync_equipment,
        )

    def remote_reader(self) -> GarminRemoteReader:
        """Compose authenticated Garmin SDK reads without contacting Garmin."""
        return GarminRemoteReader(
            self._config(),
            self.client_factory(),
            self.sync_state_service(),
            self._diagnostic_capture,
            self._redactor.redact_text,
            self._logger,
            self._utc_now,
            lambda: self._athlete_clock.now().date(),
            self._earliest_date,
            self._sync_chunk_days,
            self._all_sync_days,
        )

    def sync_service(self) -> GarminSyncService:
        """Compose the Garmin synchronization use case."""
        return garmin_service.GarminSyncService(
            GarminSyncSource(
                self.fixture_loader(),
                self.remote_reader(),
                self._earliest_date,
                lambda: self._athlete_clock.now().date(),
            ),
            self.payload_service(),
            self.sync_state_service(),
            SyncOperationStateWriter(
                self._database_manager(),
                self._key_values,
                self._event_buffer,
                self._redactor.redact_text,
            ),
            self._operation_observer(),
            GarminSyncCoordination(
                shared_garmin_sync_lock(),
                self._resync_gate,
                wait_seconds=self._lock_wait_seconds,
            ),
            GarminSyncLifecycleState(
                self._database_manager(),
                self._key_values,
                self._utc_now,
                self._logger,
            ),
        )

    def projection_service(self) -> GarminProjectionService:
        """Compose public and Coach projections over current Garmin state."""
        return GarminProjectionService(
            self._config(),
            self.payload_service(),
            self.sync_service(),
            self.sync_state_service(),
            self._sync_state_repository(),
            self._morning_body_battery_service(),
            self.client_factory(),
            self._database_manager(),
            self._key_values,
            self._redactor,
            self._athlete_clock.now,
        )
