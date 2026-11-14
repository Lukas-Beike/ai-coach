"""Build the competition sync and the full provider resync (#2101).

Every service reads the live configuration, database and domain owners from the
application context when it is built.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.context import AppContext
from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.errors import AppError
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync.competitions import CompetitionSyncReconciler, CompetitionSyncService
from backend.sync.full_resync import (
    FULL_RESYNC_LABEL,
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


@dataclass(frozen=True)
class ProviderResyncServices:
    competition_reconciler: Callable[[], CompetitionSyncReconciler]
    competition_sync_service: Callable[[], CompetitionSyncService]
    full_resync_service: Callable[[], FullProviderResyncService]


def build_provider_resync(
    ctx: AppContext,
    *,
    garmin_resync_gate: ProviderResyncGate,
    wahoo_resync_gate: ProviderResyncGate,
    all_sync_days: int,
    after_resync: Callable[[Mapping[str, Any]], None],
) -> ProviderResyncServices:
    """Competition sync and full provider resync over the live owners.

    The composition root passes the Garmin and Wahoo resync gates, the length of
    the full sync window and the derived-data hook that runs after a resync. The
    run registry is shared, so every full resync service sees the runs in flight.
    """
    resync_runs = FullResyncRuns()

    def competition_reconciler() -> CompetitionSyncReconciler:
        """Local persistence for remote competition reconciliation."""
        return CompetitionSyncReconciler(ctx.database(), uuid.uuid4)

    def competition_sync_service() -> CompetitionSyncService:
        """The authorized competition synchronization use case."""
        return CompetitionSyncService(
            ctx.config(),
            lambda: ctx.provider_transport.intervals_client(),
            competition_reconciler(),
            ctx.planning.competition(),
            ctx.database(),
            ctx.key_values,
            runtime_events.STATE_EVENT_BUFFER,
            ctx.redactor,
            ctx.logger,
            runtime_clock.utc_now,
        )

    def full_resync_service() -> FullProviderResyncService:
        """Full provider resynchronization over the current service owners."""
        observer = ctx.provider_sync.operation_observer()
        gates: dict[str, ProviderResyncGate] = {
            GARMIN_ID: garmin_resync_gate,
            WAHOO_ID: wahoo_resync_gate,
        }
        handlers = full_resync_handlers(
            garmin_service=ctx.garmin.sync_service(),
            wahoo_service=ctx.wahoo.sync_service(),
            all_sync_days=all_sync_days,
        )
        return FullProviderResyncService(
            handlers,
            FullResyncStateStore(ctx.database(), ctx.key_values),
            FullResyncOperationJournal(
                observer,
                ctx.logger,
                ctx.redactor.redact_text,
                runtime_clock.utc_now,
                time.perf_counter,
                lambda: uuid.uuid4().hex,
            ),
            gates=gates,
            after_resync=after_resync,
            runs=resync_runs,
        )

    return ProviderResyncServices(
        competition_reconciler, competition_sync_service, full_resync_service
    )
