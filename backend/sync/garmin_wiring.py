"""Build the Garmin synchronization and read services (#2101).

Every service reads the live configuration, database and domain owners from the
application context when it is built, so credentials saved in the app apply to
the next call without a restart. Each call returns a fresh service except the
process-wide change check, whose cadence state and 24-hour Personal API token
must outlive each loop pass.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.activities.zone_settings import ZoneSettings
from backend.app.context import AppContext
from backend.canonical.vocabulary import GARMIN_ID
from backend.errors import AppError
from backend.providers import garmin as garmin_provider
from backend.providers.garmin_personal import GarminPersonalClient
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import garmin, garmin_service
from backend.sync.garmin_activity_details import GarminActivityDetailService
from backend.sync.garmin_change_check import GarminChangeCheck
from backend.sync.garmin_personal_status import sdk_write_ready
from backend.sync.garmin_projection_service import (
    GarminCanonicalSources,
    GarminProjectionService,
)
from backend.sync.garmin_service import (
    GarminRemoteReader,
    GarminSyncCoordination,
    GarminSyncLifecycleState,
    GarminSyncService,
    GarminSyncSource,
    GarminTargetedRefreshService,
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
class GarminServices:
    fixture_loader: Callable[[], garmin.GarminFixtureLoader]
    client_factory: Callable[[], garmin_provider.GarminClientFactory]
    payload_service: Callable[[], garmin.GarminPayloadService]
    sync_state_service: Callable[[], garmin.GarminSyncStateService]
    strength_push_service: Callable[[], Any]
    sdk_write_ready: Callable[[], bool]
    body_export: Callable[[Any], Any]
    remote_reader: Callable[[], GarminRemoteReader]
    check_stored_login: Callable[[], None]
    change_check: Callable[[], GarminChangeCheck]
    change_personal_client: Callable[[], GarminPersonalClient | None]
    sync_service: Callable[[], GarminSyncService]
    activity_detail_service: Callable[[], GarminActivityDetailService]
    targeted_refresh_service: Callable[[], GarminTargetedRefreshService]
    wellness_history_service: Callable[[], GarminWellnessHistoryService]
    stream_backfill_service: Callable[[], StreamBackfillService]
    projection_service: Callable[[], GarminProjectionService]


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


def _datetime_now() -> datetime:
    return datetime.now(UTC)


def build_garmin(
    ctx: AppContext,
    *,
    root: Path,
    earliest_date: date,
    sync_chunk_days: int,
    all_sync_days: int,
    sync_state_repository: Callable[[], SyncStateRepository],
    daily_sync_markers: Callable[[], Any],
    resync_gate: Any,
    lock_wait_seconds: int,
    metric_export: Callable[[], dict[str, Any] | None],
    tokens: Any,
    run_zones: Callable[[], Callable[[Mapping[str, Any]], ZoneSettings | None]],
) -> GarminServices:
    """Garmin services over the live context.

    The composition root passes the data root, the history bounds, the sync state
    and daily marker lookups, the Garmin resync gate, the lock wait, the metric
    export hook, the token store and the run zone lookup.
    """
    utc_now = runtime_clock.utc_now
    # One change check and one reader per configuration, so the cadence
    # state and the 24-hour Personal API token outlive each loop pass.
    change_lock = threading.Lock()
    change_check_instance: GarminChangeCheck | None = None
    change_reader: tuple[tuple[Any, Any], GarminRemoteReader] | None = None

    def local_today() -> date:
        return ctx.clock.now().date()

    def snapshot_writer() -> GarminSnapshotWriter:
        return GarminSnapshotWriter(ctx.key_values, lambda: ctx.clock.now().tzinfo)

    def sync_coordination() -> GarminSyncCoordination:
        return GarminSyncCoordination(
            shared_garmin_sync_lock(), resync_gate, wait_seconds=lock_wait_seconds
        )

    def remote_configured(reader: Any) -> Callable[[], bool]:
        """Report a remote reader as configured only while no fixture is active."""
        loader = fixture_loader()
        return lambda: loader.path() is None and reader.configured()

    def fixture_loader() -> garmin.GarminFixtureLoader:
        return garmin.GarminFixtureLoader(
            ctx.config(), root, ctx.clock.now, utc_now, earliest_date, all_sync_days
        )

    def client_factory() -> garmin_provider.GarminClientFactory:
        """The lazy optional Garmin SDK boundary."""
        return garmin_provider.GarminClientFactory()

    def payload_service() -> garmin.GarminPayloadService:
        return garmin.GarminPayloadService(
            ctx.database(), ctx.key_values, sync_state_repository(), local_today
        )

    def sync_state_service() -> garmin.GarminSyncStateService:
        return garmin.GarminSyncStateService(
            ctx.database(),
            ctx.key_values,
            sync_state_repository(),
            daily_sync_markers(),
            ctx.redactor,
            utc_now,
            _datetime_now,
            lambda payload: ctx.athlete.equipment().sync_garmin_snapshot(payload),
            snapshot_writer=snapshot_writer(),
        )

    def sdk_write_ready_now() -> bool:
        """Whether Garmin workouts can be written: an SDK login, not skipped."""
        with ctx.database().reader() as db:
            return sdk_write_ready(
                ctx.config(), lambda key: ctx.key_values.get(db, key)
            )

    def strength_push_service() -> Any:
        """The explicit strength and run workout push; it opens no connection yet."""
        from backend.sync.garmin_strength_push import (
            GarminSdkWriteSession,
            GarminStrengthPushService,
        )

        return GarminStrengthPushService(
            configured=lambda: bool(sync_service().configured()),
            database_manager=ctx.database,
            sdk_session=GarminSdkWriteSession(
                remote_reader(), fixture_loader(), tokens
            ),
            today=local_today,
            now=_datetime_now,
            redactor=ctx.redactor.redact_text,
            gate=resync_gate,
            write_ready=sdk_write_ready_now,
            run_zones=run_zones,
        )

    def body_export(profile: Any) -> Any:
        from backend.sync.garmin_profile_body_export import GarminProfileBodyExport

        return GarminProfileBodyExport(
            profile, remote_reader(), fixture_loader(), tokens
        )

    def remote_reader() -> GarminRemoteReader:
        """Authenticated Garmin SDK reads, without contacting Garmin."""
        return GarminRemoteReader(
            ctx.config(),
            client_factory(),
            sync_state_service(),
            ctx.diagnostic_capture,
            ctx.redactor.redact_text,
            ctx.logger,
            utc_now,
            local_today,
            earliest_date,
            sync_chunk_days,
            all_sync_days,
            garmin_tokens=tokens,
        )

    def check_stored_login() -> None:
        """Verify the stored tokens while holding Garmin's sync guard.

        A running sync makes the check report busy. Holding the guard keeps a
        sync from refreshing the same token blob during the login, because a
        lost write-back could force a reconnect.
        """
        if fixture_loader().path() is not None:
            # Fixture mode never reaches the real Garmin SDK, as in the other entry points.
            raise AppError(
                503, "Die Garmin-Testdatei ist aktiv.", reason="check_unsupported"
            )
        try:
            with _non_blocking_garmin_guard(sync_coordination()):
                remote_reader().check_stored_login()
        except AppError as error:
            if error.reason == RESYNC_RUNNING_REASON:
                # A full resync holds the gate; report it like a running sync.
                raise AppError(
                    503,
                    "Eine Garmin-Synchronisierung läuft.",
                    reason="provider_busy",
                ) from error
            raise

    def change_personal_client() -> GarminPersonalClient | None:
        """The Personal API client of the current configuration and database.

        None in fixture mode, which never reaches the real Garmin.
        """
        nonlocal change_reader
        key = (ctx.config(), ctx.database())
        if fixture_loader().path() is not None:
            return None
        with change_lock:
            cached = change_reader
            if cached is None or any(a is not b for a, b in zip(cached[0], key)):
                cached = (key, remote_reader())
                change_reader = cached
        return cached[1].personal_client()

    def change_check() -> GarminChangeCheck:
        """The process-wide light Garmin change check (#2303)."""
        nonlocal change_check_instance
        with change_lock:
            if change_check_instance is None:
                change_check_instance = GarminChangeCheck(
                    personal=change_personal_client,
                    known_activity_ids=lambda days: (
                        payload_service().known_activity_ids(days)
                    ),
                    stored_sleep=lambda day: (
                        payload_service()
                        .view(["sleep"], start=day.isoformat(), end=day.isoformat())
                        .get("sleep")
                    ),
                    last_refresh=lambda: daily_sync_markers().last_success(GARMIN_ID),
                    local_now=ctx.clock.now,
                    logger=ctx.logger,
                    store_daytime=lambda day, values: (
                        targeted_refresh_service().store_daytime(day, values)
                    ),
                )
            return change_check_instance

    def sync_service() -> GarminSyncService:
        return garmin_service.GarminSyncService(
            GarminSyncSource(
                fixture_loader(), remote_reader(), earliest_date, local_today
            ),
            payload_service(),
            sync_state_service(),
            SyncOperationStateWriter(
                ctx.database(),
                ctx.key_values,
                runtime_events.STATE_EVENT_BUFFER,
                ctx.redactor.redact_text,
            ),
            ctx.provider_sync.operation_observer(),
            sync_coordination(),
            GarminSyncLifecycleState(
                ctx.database(), ctx.key_values, utc_now, ctx.logger
            ),
            metric_export=metric_export,
            activity_detail_backfill=activity_detail_service().backfill,
        )

    def activity_detail_service() -> GarminActivityDetailService:
        """The on-demand Garmin activity detail refresh.

        The guard shares Garmin's resync gate and lock with the sync service but
        never waits: a busy provider answers 503 instead of queueing a second read.
        While the Garmin fixture is active the detail fetch counts as not
        configured, so fixture mode never reaches the real Garmin SDK.
        """
        reader = remote_reader()
        coordination = sync_coordination()
        return GarminActivityDetailService(
            database_manager=ctx.database(),
            reader=reader,
            configured=remote_configured(reader),
            guard=lambda: _non_blocking_garmin_guard(coordination),
            utc_now=utc_now,
            key_values=ctx.key_values,
            capability_allowed=sync_state_service().capability_allowed,
        )

    def targeted_refresh_service() -> GarminTargetedRefreshService:
        """Bounded Garmin reads for nutrition and Analyse, without a full sync."""
        reader = remote_reader()
        return GarminTargetedRefreshService(
            reader=reader,
            database_manager=ctx.database(),
            snapshot_writer=snapshot_writer(),
            payload_service=payload_service(),
            coordination=sync_coordination(),
            utc_now=utc_now,
            configured=remote_configured(reader),
        )

    def wellness_history_service() -> GarminWellnessHistoryService:
        """The one-off, insert-only Garmin wellness history backfill."""
        reader = remote_reader()
        return GarminWellnessHistoryService(
            reader=reader,
            database_manager=ctx.database(),
            snapshot_writer=snapshot_writer(),
            sync_state_repository=sync_state_repository(),
            coordination=sync_coordination(),
            utc_now=utc_now,
            configured=remote_configured(reader),
        )

    def stream_backfill_service() -> StreamBackfillService:
        """The backfill of the FIT streams of past Garmin activities."""
        reader = remote_reader()
        coordination = sync_coordination()

        def guard() -> AbstractContextManager[None]:
            return coordinated_guard(coordination)

        return StreamBackfillService(
            provider=GARMIN_ID,
            source=GarminStreamSource(reader, guard),
            mapping=GarminStreamMapping(),
            database_manager=ctx.database,
            key_values=ctx.key_values,
            guard=guard,
            utc_now=utc_now,
            configured=remote_configured(reader),
            earliest_date=earliest_date,
            batch_limit=STREAM_BATCH_LIMIT,
        )

    def projection_service() -> GarminProjectionService:
        """Public and Coach projections over current Garmin state."""
        return GarminProjectionService(
            ctx.config(),
            payload_service(),
            sync_service(),
            sync_state_service(),
            ctx.morning_body_battery_service(),
            client_factory(),
            ctx.database(),
            ctx.key_values,
            ctx.redactor,
            ctx.clock.now,
            canonical=GarminCanonicalSources(
                observations=lambda: ctx.canonical_read,
                activity_summaries=lambda: ctx.canonical_read,
            ),
        )

    return GarminServices(
        fixture_loader,
        client_factory,
        payload_service,
        sync_state_service,
        strength_push_service,
        sdk_write_ready_now,
        body_export,
        remote_reader,
        check_stored_login,
        change_check,
        change_personal_client,
        sync_service,
        activity_detail_service,
        targeted_refresh_service,
        wellness_history_service,
        stream_backfill_service,
        projection_service,
    )
