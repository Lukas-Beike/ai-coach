"""Composition for competition synchronization and provider resync."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.sync.competitions import CompetitionSyncReconciler, CompetitionSyncService
from backend.sync.full_resync import (
    FULL_RESYNC_LABEL,
    PROVIDER_RESYNC_KEYS,
    FullProviderResyncService,
    FullResyncHandler,
    FullResyncOperationJournal,
    FullResyncRuns,
    FullResyncStateStore,
)
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_table import (
    GARMIN_NOT_CONFIGURED_MESSAGE,
    WAHOO_NOT_CONFIGURED_MESSAGE,
)
from backend.sync.wahoo_sync import WahooSyncService


@dataclass(frozen=True)
class CompetitionSyncOwners:
    config: Callable[[], Config]
    intervals_client: Callable[[], Any]
    competition_service: Callable[[], Any]


@dataclass(frozen=True)
class ResyncProviderOwners:
    garmin_sync_service: Callable[[], Any]
    garmin_resync_gate: ProviderResyncGate
    wahoo_sync_service: Callable[[], Any]
    wahoo_resync_gate: ProviderResyncGate
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
    after_resync: Callable[[Mapping[str, Any]], None] = lambda _job: None


class GarminFullResync:
    """Full Garmin resync over the complete sync window.

    A contended run is a failed resync; a partial read is returned as such, so
    the state does not record it as complete.
    """

    def __init__(
        self, *, garmin_service: GarminSyncService, all_sync_days: int
    ) -> None:
        self._garmin_service = garmin_service
        self._all_sync_days = all_sync_days

    def configured(self) -> bool:
        return self._garmin_service.configured()

    def not_configured_error(self) -> AppError:
        return AppError(503, GARMIN_NOT_CONFIGURED_MESSAGE, reason="not_configured")

    def run(
        self, operation_id: str, _observer: SyncOperationObserver
    ) -> dict[str, Any]:
        result = self._garmin_service.sync(
            days=self._all_sync_days,
            operation_id=operation_id,
            reason=FULL_RESYNC_LABEL,
        )
        status = result.get("status")
        if status == "not_configured":
            raise self.not_configured_error()
        if status == "already_running":
            raise AppError(
                409,
                "Die Garmin-Synchronisierung läuft bereits. Bitte warten.",
                reason="already_running",
            )
        return result


class WahooFullResync:
    """Full Wahoo read resync over the complete sync window.

    A skipped or contended run is a failed resync, so the state records it
    instead of reporting success.
    """

    def __init__(self, *, sync_service: WahooSyncService, all_sync_days: int) -> None:
        self._sync_service = sync_service
        self._all_sync_days = all_sync_days

    def configured(self) -> bool:
        return self._sync_service.configured()

    def not_configured_error(self) -> AppError:
        return AppError(503, WAHOO_NOT_CONFIGURED_MESSAGE, reason="not_configured")

    def run(
        self, operation_id: str, _observer: SyncOperationObserver
    ) -> dict[str, Any]:
        result = self._sync_service.sync(
            days=self._all_sync_days,
            reason=FULL_RESYNC_LABEL,
            operation_id=operation_id,
        )
        status = result.get("status")
        if status == "not_configured":
            raise self.not_configured_error()
        if status == "already_running":
            raise AppError(
                409,
                "Die Wahoo-Synchronisierung läuft bereits. Bitte warten.",
                reason="already_running",
            )
        if status == "partial":
            # The newest workouts are stored, so nothing is lost, but the window
            # was not read completely and must not be reported as a full resync.
            raise AppError(
                502,
                "Wahoo hat mehr Einheiten geliefert, als ein Durchlauf abrufen kann. "
                "Die neuesten wurden gespeichert, ältere fehlen noch.",
                reason="partial_resync",
            )
        return result


def full_resync_handlers(
    *,
    garmin_service: GarminSyncService,
    wahoo_service: WahooSyncService,
    all_sync_days: int,
) -> dict[str, FullResyncHandler]:
    """Map each provider with a full resync to its handler."""
    return {
        GARMIN_ID: GarminFullResync(
            garmin_service=garmin_service, all_sync_days=all_sync_days
        ),
        WAHOO_ID: WahooFullResync(
            sync_service=wahoo_service, all_sync_days=all_sync_days
        ),
    }


class ProviderResyncAssembly:
    """Create the competition sync and full provider resync use cases."""

    @dataclass(frozen=True)
    class Inputs:
        competition: CompetitionSyncOwners
        resync: ResyncProviderOwners
        persistence: ProviderResyncPersistence
        runtime: ProviderResyncRuntime

    def __init__(
        self,
        *,
        dependencies: ProviderResyncAssembly.Inputs,
    ) -> None:
        competition = dependencies.competition
        resync = dependencies.resync
        persistence = dependencies.persistence
        runtime = dependencies.runtime
        self._competition_config = competition.config
        self._intervals_client = competition.intervals_client
        self._competition_service = competition.competition_service
        self._garmin_sync_service = resync.garmin_sync_service
        self._garmin_resync_gate = resync.garmin_resync_gate
        self._wahoo_sync_service = resync.wahoo_sync_service
        self._wahoo_resync_gate = resync.wahoo_resync_gate
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
        self._after_resync = runtime.after_resync
        self._resync_runs = FullResyncRuns()

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
        gates: dict[str, ProviderResyncGate] = {
            GARMIN_ID: self._garmin_resync_gate,
            WAHOO_ID: self._wahoo_resync_gate,
        }
        handlers = full_resync_handlers(
            garmin_service=self._garmin_sync_service(),
            wahoo_service=self._wahoo_sync_service(),
            all_sync_days=self._all_sync_days,
        )
        return FullProviderResyncService(
            handlers,
            FullResyncStateStore(
                self._database_manager(),
                self._key_values,
                PROVIDER_RESYNC_KEYS,
            ),
            FullResyncOperationJournal(
                observer,
                self._logger,
                self._redactor.redact_text,
                self._utc_now,
                self._monotonic,
                self._uuid_factory,
            ),
            gates=gates,
            after_resync=self._after_resync,
            runs=self._resync_runs,
        )
