"""Build the Wahoo connection, read synchronization and plan export services (#2101).

Each service reads the live configuration, database and domain owners from the
application context when it is used, so Wahoo credentials saved in the app apply
to the next call without a restart. The connection service, the sync service,
the activity detail importer and the plan-push service are shared, so their run
and refresh locks serialize every caller; every other service is built fresh.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from backend.app.context import AppContext
from backend.canonical.records import Observation
from backend.canonical.vocabulary import ProviderId, Sport
from backend.performance.current_thresholds import ThresholdKey
from backend.providers.observed_opener import Opener
from backend.providers.wahoo_client import WahooClient
from backend.providers.wahoo_fit_download import download_wahoo_fit
from backend.providers.wahoo_oauth import WahooOAuthClient
from backend.providers.wahoo_plan_mapping import WahooPlanReferences
from backend.runtime import clock as runtime_clock
from backend.sync.daily import DailySyncMarkerService
from backend.sync.gates import ProviderResyncGate
from backend.sync.stream_backfill import StreamBackfillService
from backend.sync.wahoo_activity_details import WahooActivityDetailImport
from backend.sync.wahoo_connection import (
    WahooConnectionService,
    WahooSecretRegistry,
)
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
class WahooConnectionServices:
    service: Callable[[], WahooConnectionService]


@dataclass(frozen=True)
class WahooSyncServices:
    client: Callable[[], WahooClient]
    sync_service: Callable[[], WahooSyncService]
    activity_detail_import: Callable[[], WahooActivityDetailImport]
    fit_download: Callable[[], Callable[[str], bytes]]
    stream_backfill_service: Callable[[], StreamBackfillService]
    workout_export: Callable[[], WahooWorkoutExport]
    library_state: Callable[[], WahooLibraryState]
    plan_push_service: Callable[[], WahooPlanPushService]


def _utc_datetime() -> datetime:
    return datetime.now(UTC)


def build_wahoo_connection(
    ctx: AppContext,
    *,
    secret_registry: WahooSecretRegistry,
    on_connected: Callable[[], None],
) -> WahooConnectionServices:
    """One connection service for the process, so token refreshes stay serialized.

    The composition root passes the secret registry the log redactor reads and the
    hook that resumes the provider backfill once the athlete connected Wahoo.
    """
    lock = threading.Lock()
    shared: WahooConnectionService | None = None

    def service() -> WahooConnectionService:
        nonlocal shared
        with lock:
            if shared is None:
                shared = WahooConnectionService(
                    config=ctx.config,
                    oauth=lambda: WahooOAuthClient(
                        ctx.config, ctx.provider_transport.json_http_client().request
                    ),
                    database_manager=ctx.database,
                    key_values=ctx.key_values,
                    utc_now=runtime_clock.utc_now,
                    secret_registry=secret_registry,
                    on_connected=on_connected,
                )
            return shared

    return WahooConnectionServices(service)


def build_wahoo_sync(
    ctx: AppContext,
    *,
    connection: Callable[[], WahooConnectionService],
    daily_markers: Callable[[], DailySyncMarkerService],
    resync_gate: ProviderResyncGate,
    export_thresholds: Callable[[Any], Mapping[ThresholdKey, Observation]],
    history_earliest_date: date,
    fit_opener: Callable[[], Opener],
) -> WahooSyncServices:
    """One sync service, detail importer and plan-push service for the process.

    The composition root passes the connection lookup, the daily markers, the
    Wahoo resync gate, the ``db -> export thresholds`` reader of the plan
    references, the oldest day the stream backfill reaches and the opener that
    observes the FIT downloads.
    """
    lock = threading.Lock()
    shared_sync: WahooSyncService | None = None
    shared_plan_push: WahooPlanPushService | None = None
    shared_details: WahooActivityDetailImport | None = None

    def client() -> WahooClient:
        """A transport bound to the stored, refreshable Wahoo token."""
        current = connection()
        return WahooClient(
            request=ctx.provider_transport.json_http_client().request,
            access_token=current.access_token,
            refresh_access_token=current.refresh_access_token,
            invalidate_access_token=current.invalidate_access_token,
        )

    def sync_service() -> WahooSyncService:
        nonlocal shared_sync
        with lock:
            if shared_sync is None:
                shared_sync = WahooSyncService(
                    config=ctx.config,
                    connection=connection,
                    source=client,
                    storage=WahooSyncStorage(
                        database_manager=ctx.database,
                        key_values=ctx.key_values,
                    ),
                    daily_markers=daily_markers,
                    observer=lambda: ctx.provider_sync.operation_observer(),
                    clock=WahooSyncClock(_utc_datetime, lambda: ctx.clock.now().tzinfo),
                    logger=ctx.logger,
                    gate=resync_gate,
                    details=activity_detail_import,
                )
            return shared_sync

    def activity_detail_import() -> WahooActivityDetailImport:
        """The detail importer; it runs only after a sync has committed."""
        nonlocal shared_details
        with lock:
            if shared_details is None:
                shared_details = WahooActivityDetailImport(
                    database_manager=ctx.database,
                    key_values=ctx.key_values,
                    download=fit_download(),
                    monotonic=time.monotonic,
                    logger=ctx.logger,
                )
            return shared_details

    def fit_download() -> Callable[[str], bytes]:
        """The FIT download, observed through the composition's opener."""
        return lambda url: download_wahoo_fit(url, opener=fit_opener())

    def stream_backfill_service() -> StreamBackfillService:
        """The backfill of the FIT streams of past Wahoo workouts."""
        return StreamBackfillService(
            provider=ProviderId.WAHOO.value,
            source=WahooStreamSource(client=client, download=fit_download()),
            mapping=WahooStreamMapping(),
            database_manager=ctx.database,
            key_values=ctx.key_values,
            utc_now=lambda: _utc_datetime().isoformat(),
            configured=sync_service().configured,
            earliest_date=history_earliest_date,
            batch_limit=WAHOO_BATCH_LIMIT,
            operation=resync_gate.operation,
            replay_days=WAHOO_REPLAY_DAYS,
        )

    def workout_export() -> WahooWorkoutExport:
        """The library export target; the client resolves per remote call.

        One export serves one push run, so the thresholds are read once per run
        and plan sport, not once per workout.
        """
        cache: dict[Sport, WahooPlanReferences] = {}

        def references(sport: Sport) -> WahooPlanReferences:
            if sport not in cache:
                with ctx.database().reader() as db:
                    thresholds = export_thresholds(db)
                cache[sport] = plan_references(thresholds, sport)
            return cache[sport]

        return WahooWorkoutExport(client, now=_utc_datetime, references=references)

    def library_state() -> WahooLibraryState:
        """Read-only Wahoo state of library workouts, for the library view."""
        return WahooLibraryState(
            configured=sync_service().configured,
            database_manager=ctx.database,
            export=workout_export,
        )

    def plan_push_service() -> WahooPlanPushService:
        """One plan-push service, so its run lock serializes every caller."""
        nonlocal shared_plan_push
        configured = sync_service().configured
        with lock:
            if shared_plan_push is None:
                shared_plan_push = WahooPlanPushService(
                    configured=configured,
                    database_manager=ctx.database,
                    export=workout_export,
                    now=_utc_datetime,
                    redactor=ctx.redactor.redact_text,
                    gate=resync_gate,
                )
            return shared_plan_push

    return WahooSyncServices(
        client,
        sync_service,
        activity_detail_import,
        fit_download,
        stream_backfill_service,
        workout_export,
        library_state,
        plan_push_service,
    )
