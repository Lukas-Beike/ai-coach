"""Composition for Garmin synchronization and read projections."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import GARMIN_ID
from backend.config import Config
from backend.errors import AppError
from backend.observability import Redactor
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.providers import garmin as garmin_provider
from backend.providers.garmin_personal import GarminPersonalClient
from backend.sync import garmin, garmin_service
from backend.sync.garmin_activity_details import GarminActivityDetailService
from backend.sync.garmin_change_check import GarminChangeCheck
from backend.sync.garmin_personal_status import sdk_write_ready
from backend.sync.garmin_projection_service import (
    GarminCanonicalSources,
    GarminProjectionService,
)
from backend.sync.garmin_service import (
    GarminAnalysisRefreshService,
    GarminNutritionRefreshService,
    GarminRemoteReader,
    GarminSyncCoordination,
    GarminSyncLifecycleState,
    GarminSyncService,
    GarminSyncSource,
    shared_garmin_sync_lock,
)
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.garmin_stream_backfill import (
    STREAM_BATCH_LIMIT,
    GarminStreamMapping,
    GarminStreamSource,
)
from backend.sync.garmin_wellness_history import (
    GarminWellnessHistoryService,
    coordinated_guard,
)
from backend.sync.gates import RESYNC_RUNNING_REASON
from backend.sync.state import SyncStateRepository
from backend.sync.status import SyncOperationStateWriter
from backend.sync.stream_backfill import StreamBackfillService


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
    metric_export: Callable[[], dict[str, Any] | None] | None = None


@contextmanager
def _non_blocking_garmin_guard(coordination: GarminSyncCoordination) -> Iterator[None]:
    """Hold the resync gate and Garmin's shared lock without waiting for either."""
    with coordination.operation():
        if not coordination.acquire():
            raise AppError(
                503,
                "Die aktuelle Garmin-Synchronisierung ist noch nicht abgeschlossen.",
                reason="provider_busy",
            )
        try:
            yield
        finally:
            coordination.release()


class GarminAssembly:
    """Resolve Garmin services from the active application resources."""

    @dataclass(frozen=True)
    class Inputs:
        provider: GarminProviderSettings
        persistence: GarminPersistenceOwners
        telemetry: GarminSyncTelemetry
        control: GarminSyncControl
        canonical: GarminCanonicalSources | None = None
        # Database-backed Garmin token store; None keeps the legacy file rules.
        tokens: Any | None = None
        # Snapshot of the run zones per unit, for the Garmin run push.
        run_zones: (
            Callable[[], Callable[[Mapping[str, Any]], ZoneSettings | None]] | None
        ) = None

    def __init__(self, *, dependencies: GarminAssembly.Inputs) -> None:
        self._canonical = dependencies.canonical
        self._garmin_tokens = dependencies.tokens
        self._run_zones = dependencies.run_zones
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
        self._metric_export = control.metric_export
        # One change check and one reader per configuration, so the cadence
        # state and the 24-hour Personal API token outlive each loop pass.
        self._change_lock = threading.Lock()
        self._change_check: GarminChangeCheck | None = None
        self._change_reader: tuple[tuple[Any, Any], GarminRemoteReader] | None = None

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
            snapshot_writer=GarminSnapshotWriter(
                self._key_values,
                lambda: self._athlete_clock.now().tzinfo,
            ),
        )

    def strength_push_service(self) -> Any:
        """Compose the explicit strength and run workout push; it opens no connection yet."""
        from backend.sync.garmin_strength_push import (
            GarminSdkWriteSession,
            GarminStrengthPushService,
        )

        return GarminStrengthPushService(
            configured=lambda: bool(self.sync_service().configured()),
            database_manager=self._database_manager,
            sdk_session=GarminSdkWriteSession(
                self.remote_reader(), self.fixture_loader(), self._garmin_tokens
            ),
            today=lambda: self._athlete_clock.now().date(),
            now=self._datetime_now,
            redactor=self._redactor.redact_text,
            gate=self._resync_gate,
            write_ready=self.sdk_write_ready,
            run_zones=self._run_zones,
        )

    def sdk_write_ready(self) -> bool:
        """Whether Garmin workouts can be written: an SDK login, not skipped."""
        with self._database_manager().reader() as db:
            return sdk_write_ready(
                self._config(), lambda key: self._key_values.get(db, key)
            )

    def body_export(self, profile: Any) -> Any:
        from backend.sync.garmin_profile_body_export import GarminProfileBodyExport

        return GarminProfileBodyExport(
            profile, self.remote_reader(), self.fixture_loader(), self._garmin_tokens
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
            garmin_tokens=self._garmin_tokens,
        )

    def check_stored_login(self) -> None:
        """Verify the stored tokens while holding Garmin's sync guard.

        A running sync makes the check report busy. Holding the guard keeps a
        sync from refreshing the same token blob during the login, because a
        lost write-back could force a reconnect.
        """
        if self.fixture_loader().path() is not None:
            # Fixture mode never reaches the real Garmin SDK, as in the other entry points.
            raise AppError(
                503, "Die Garmin-Testdatei ist aktiv.", reason="check_unsupported"
            )
        try:
            with _non_blocking_garmin_guard(self._sync_coordination()):
                self.remote_reader().check_stored_login()
        except AppError as error:
            if error.reason == RESYNC_RUNNING_REASON:
                # A full resync holds the gate; report it like a running sync.
                raise AppError(
                    503,
                    "Eine Garmin-Synchronisierung läuft.",
                    reason="provider_busy",
                ) from error
            raise

    def change_check(self) -> GarminChangeCheck:
        """The process-wide light Garmin change check (#2303)."""
        with self._change_lock:
            if self._change_check is None:
                self._change_check = GarminChangeCheck(
                    personal=self._change_personal_client,
                    known_activity_ids=lambda days: (
                        self.payload_service().known_activity_ids(days)
                    ),
                    stored_sleep=lambda day: (
                        self.payload_service()
                        .view(["sleep"], start=day.isoformat(), end=day.isoformat())
                        .get("sleep")
                    ),
                    last_refresh=lambda: self._daily_sync_marker_service().last_success(
                        GARMIN_ID
                    ),
                    local_now=self._athlete_clock.now,
                    logger=self._logger,
                    store_daytime=lambda day, values: (
                        self.nutrition_refresh_service().store_daytime(day, values)
                    ),
                )
            return self._change_check

    def _change_personal_client(self) -> GarminPersonalClient | None:
        """The Personal API client of the current configuration and database.

        None in fixture mode, which never reaches the real Garmin.
        """
        key = (self._config(), self._database_manager())
        if self.fixture_loader().path() is not None:
            return None
        with self._change_lock:
            cached = self._change_reader
            if cached is None or any(a is not b for a, b in zip(cached[0], key)):
                cached = (key, self.remote_reader())
                self._change_reader = cached
        return cached[1].personal_client()

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
            self._sync_coordination(),
            GarminSyncLifecycleState(
                self._database_manager(),
                self._key_values,
                self._utc_now,
                self._logger,
            ),
            metric_export=self._metric_export,
            activity_detail_backfill=self.activity_detail_service().backfill,
        )

    def activity_detail_service(self) -> GarminActivityDetailService:
        """Compose the on-demand Garmin activity detail refresh.

        The guard shares Garmin's resync gate and lock with the sync service but
        never waits: a busy provider answers 503 instead of queueing a second read.
        While the Garmin fixture is active the detail fetch counts as not
        configured, so fixture mode never reaches the real Garmin SDK.
        """
        reader = self.remote_reader()
        coordination = self._sync_coordination()
        return GarminActivityDetailService(
            database_manager=self._database_manager(),
            reader=reader,
            configured=self._remote_configured(reader),
            guard=lambda: _non_blocking_garmin_guard(coordination),
            utc_now=self._utc_now,
            key_values=self._key_values,
            capability_allowed=self.sync_state_service().capability_allowed,
        )

    def nutrition_refresh_service(self) -> GarminNutritionRefreshService:
        """Compose bounded Garmin reads used by nutrition, without a full sync."""
        reader = self.remote_reader()
        return GarminNutritionRefreshService(
            reader=reader,
            database_manager=self._database_manager(),
            snapshot_writer=GarminSnapshotWriter(
                self._key_values,
                lambda: self._athlete_clock.now().tzinfo,
            ),
            payload_service=self.payload_service(),
            coordination=self._sync_coordination(),
            utc_now=self._utc_now,
            configured=self._remote_configured(reader),
        )

    def wellness_history_service(self) -> GarminWellnessHistoryService:
        """Compose the one-off, insert-only Garmin wellness history backfill."""
        reader = self.remote_reader()
        return GarminWellnessHistoryService(
            reader=reader,
            database_manager=self._database_manager(),
            snapshot_writer=GarminSnapshotWriter(
                self._key_values,
                lambda: self._athlete_clock.now().tzinfo,
            ),
            sync_state_repository=self._sync_state_repository(),
            coordination=self._sync_coordination(),
            utc_now=self._utc_now,
            configured=self._remote_configured(reader),
        )

    def stream_backfill_service(self) -> StreamBackfillService:
        """Compose the backfill of the FIT streams of past Garmin activities."""
        reader = self.remote_reader()
        coordination = self._sync_coordination()

        def guard() -> AbstractContextManager[None]:
            return coordinated_guard(coordination)

        return StreamBackfillService(
            provider=GARMIN_ID,
            source=GarminStreamSource(reader, guard),
            mapping=GarminStreamMapping(),
            database_manager=self._database_manager,
            key_values=self._key_values,
            guard=guard,
            utc_now=self._utc_now,
            configured=self._remote_configured(reader),
            earliest_date=self._earliest_date,
            batch_limit=STREAM_BATCH_LIMIT,
        )

    def analysis_refresh_service(self) -> GarminAnalysisRefreshService:
        """Compose bounded Garmin reads used by Analyse without a full sync."""
        reader = self.remote_reader()
        return GarminAnalysisRefreshService(
            reader=reader,
            database_manager=self._database_manager(),
            snapshot_writer=GarminSnapshotWriter(
                self._key_values,
                lambda: self._athlete_clock.now().tzinfo,
            ),
            payload_service=self.payload_service(),
            coordination=self._sync_coordination(),
            utc_now=self._utc_now,
            configured=self._remote_configured(reader),
        )

    def _remote_configured(self, reader: Any) -> Callable[[], bool]:
        """Report a remote reader as configured only while no fixture is active."""
        fixture_loader = self.fixture_loader()
        return lambda: fixture_loader.path() is None and reader.configured()

    def _sync_coordination(self) -> GarminSyncCoordination:
        return GarminSyncCoordination(
            shared_garmin_sync_lock(),
            self._resync_gate,
            wait_seconds=self._lock_wait_seconds,
        )

    def projection_service(self) -> GarminProjectionService:
        """Compose public and Coach projections over current Garmin state."""
        if self._canonical is None:
            raise RuntimeError("Garmin projections need the canonical read sources.")
        return GarminProjectionService(
            self._config(),
            self.payload_service(),
            self.sync_service(),
            self.sync_state_service(),
            self._morning_body_battery_service(),
            self.client_factory(),
            self._database_manager(),
            self._key_values,
            self._redactor,
            self._athlete_clock.now,
            canonical=self._canonical,
        )
