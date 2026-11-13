"""Build the sync persistence, status, queue, worker and command services (#2101).

Every service reads the live configuration, database and domain owners from the
application context when it is used, so a configuration change or a restore
applies without a restart.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.context import AppContext
from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import freshness, job_outcomes, jobs, observation, queue, refresh
from backend.sync import worker as sync_worker
from backend.sync.adaptive import IllnessPauseSyncService
from backend.sync.authority import PlanningAuthorityService
from backend.sync.commands import (
    GarminSynchronousRefresh,
    ProviderRefreshCommandService,
    SynchronousRefresh,
    WahooSynchronousRefresh,
)
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_assembly import SyncJobExecutionAssembly
from backend.sync.garmin_personal_status import sdk_write_ready
from backend.sync.gates import resetting_providers
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.state import SyncStateRepository

PROVIDER_REFRESH_RETRY_BASE_SECONDS = 15 * 60
PROVIDER_REFRESH_RETRY_MAX_SECONDS = 6 * 60 * 60
SYNC_JOB_RETRY_BASE_SECONDS = 15 * 60
SYNC_JOB_RETRY_MAX_SECONDS = 6 * 60 * 60
SYNC_JOB_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class SyncPersistenceServices:
    state_repository: Callable[[], SyncStateRepository]
    daily_markers: Callable[[], DailySyncMarkerService]


@dataclass(frozen=True)
class ProviderSyncServices:
    refresh_tracker: Callable[[], refresh.ProviderRefreshTracker]
    operation_observer: Callable[[], observation.SyncOperationObserver]
    freshness_service: Callable[[], freshness.ProviderFreshnessService]


@dataclass(frozen=True)
class SyncJobQueueServices:
    store: Callable[[], jobs.SyncJobStore]
    service: Callable[[], queue.SyncJobQueueService]
    outcome_service: Callable[[], job_outcomes.SyncJobOutcomeService]


@dataclass(frozen=True)
class SyncWorkerServices:
    create: Callable[[], sync_worker.SyncJobWorker]


@dataclass(frozen=True)
class SyncCommandServices:
    illness_pause: Callable[[], IllnessPauseSyncService]
    provider_refresh: Callable[[], ProviderRefreshCommandService]
    conflicts: Callable[[], SyncConflictCommandService]
    plan_push: Callable[[], PlanPushCommandService]
    authority: Callable[[], PlanningAuthorityService]
    structured_plan_sync: Callable[[], StructuredPlanSyncService]
    repair_manifest: Callable[[], PlanRepairManifestService]


def _utc_datetime() -> datetime:
    return datetime.now(UTC)


def build_sync_persistence(ctx: AppContext) -> SyncPersistenceServices:
    """Fresh persistence services bound to the current manager and athlete clock."""
    utc_now = runtime_clock.utc_now

    def state_repository() -> SyncStateRepository:
        return SyncStateRepository(ctx.database(), ctx.key_values, utc_now)

    def daily_markers() -> DailySyncMarkerService:
        return DailySyncMarkerService(ctx.database(), ctx.key_values, ctx.clock.now)

    return SyncPersistenceServices(state_repository, daily_markers)


def build_provider_sync(ctx: AppContext) -> ProviderSyncServices:
    """The shared refresh tracker, its observer and the freshness projection."""
    event_buffer = runtime_events.STATE_EVENT_BUFFER

    def refresh_tracker() -> refresh.ProviderRefreshTracker:
        return refresh.PROVIDER_REFRESH_TRACKER_CACHE.get(
            ctx.database(),
            event_buffer,
            _utc_datetime,
            ctx.ids,
            retention_days=freshness.PROVIDER_REFRESH_RETENTION_DAYS,
            max_rows=freshness.PROVIDER_REFRESH_MAX_ROWS,
            retry_base_seconds=PROVIDER_REFRESH_RETRY_BASE_SECONDS,
            retry_max_seconds=PROVIDER_REFRESH_RETRY_MAX_SECONDS,
        )

    def operation_observer() -> observation.SyncOperationObserver:
        return observation.SyncOperationObserver(
            refresh_tracker(), ctx.maintenance, ctx.logger
        )

    def freshness_service() -> freshness.ProviderFreshnessService:
        return freshness.ProviderFreshnessService(
            ctx.config(), ctx.database(), ctx.key_values, _utc_datetime
        )

    return ProviderSyncServices(refresh_tracker, operation_observer, freshness_service)


def build_sync_job_queue(
    ctx: AppContext,
    *,
    all_sync_days: int,
    daily_sync_markers: Callable[[], DailySyncMarkerService],
) -> SyncJobQueueServices:
    """Fresh job store and queue projections over the shared event and wake owners."""
    event_buffer = runtime_events.STATE_EVENT_BUFFER
    utc_now = runtime_clock.utc_now
    wake_event = sync_worker.shared_sync_job_wake_event

    def foreground_busy() -> bool:
        return ctx.coach_background_jobs.job_store().busy()

    def store() -> jobs.SyncJobStore:
        return jobs.SyncJobStore(
            ctx.database(),
            utc_now,
            ctx.ids,
            foreground_busy=foreground_busy,
            held_providers=resetting_providers,
        )

    def service() -> queue.SyncJobQueueService:
        return queue.SyncJobQueueService(
            store(),
            event_buffer,
            ctx.maintenance,
            wake_event(),
            all_sync_days,
            daily_sync_markers(),
        )

    def outcome_service() -> job_outcomes.SyncJobOutcomeService:
        return job_outcomes.SyncJobOutcomeService(
            store(),
            event_buffer,
            wake_event(),
            ctx.redactor.redact_text,
            ctx.logger,
            _utc_datetime,
            SYNC_JOB_RETRY_BASE_SECONDS,
            SYNC_JOB_RETRY_MAX_SECONDS,
        )

    return SyncJobQueueServices(store, service, outcome_service)


def build_sync_worker(
    ctx: AppContext, *, executor: Callable[[], Any]
) -> SyncWorkerServices:
    """The unstarted worker over the queue store, the executor and the wake event."""

    def create() -> sync_worker.SyncJobWorker:
        store = ctx.sync_job_queue.store()
        return sync_worker.SyncJobWorker(
            store,
            executor(),
            ctx.maintenance,
            SYNC_JOB_POLL_SECONDS,
            wake_event=sync_worker.shared_sync_job_wake_event(),
            requeue_unowned=store.requeue_unowned_running,
        )

    return SyncWorkerServices(create)


def build_sync_commands(
    ctx: AppContext,
    *,
    intervals_client: Callable[[], Any],
    synchronous_refreshes: Callable[[], Mapping[str, SynchronousRefresh]],
    after_refresh: Callable[[Mapping[str, Any]], None],
    training_change_limit: int,
) -> SyncCommandServices:
    """Fresh command services over the shared sync and planning owners.

    The composition root passes the Intervals.icu client lookup (tests replace the
    transport it names), the inline refreshes, the derived-data hook and the Coach
    change limit, so this domain imports neither the executor wiring nor Coach.
    """

    utc_now = runtime_clock.utc_now

    def today() -> Any:
        return ctx.clock.now().date()

    def illness_pause() -> IllnessPauseSyncService:
        return IllnessPauseSyncService(
            ctx.config(),
            intervals_client(),
            adaptive_replan_apply_service=ctx.planning.adaptive_apply(),
            competition_service=ctx.planning.competition(),
            adaptive_replan_preview_service=(
                ctx.planning_workflows.adaptive_replan_preview_service()
            ),
            redactor=ctx.redactor,
            today=today,
        )

    def provider_refresh() -> ProviderRefreshCommandService:
        return ProviderRefreshCommandService(
            ctx.sync_job_queue.service(), synchronous_refreshes(), after_refresh
        )

    def conflicts() -> SyncConflictCommandService:
        return SyncConflictCommandService(
            ctx.planning.competition(), ctx.sync_job_queue.service()
        )

    def plan_push() -> PlanPushCommandService:
        def garmin_writable() -> bool:
            with ctx.database().reader() as db:
                return sdk_write_ready(
                    ctx.config(), lambda key: ctx.key_values.get(db, key)
                )

        return PlanPushCommandService(ctx.sync_job_queue.service(), garmin_writable)

    def authority() -> PlanningAuthorityService:
        return PlanningAuthorityService(
            ctx.database(),
            ctx.workout_library_sync.sync_state_service(),
            ctx.planning_revision,
            utc_now,
            local_today=today,
        )

    def structured_plan_sync() -> StructuredPlanSyncService:
        return StructuredPlanSyncService(
            ctx.database(), authority(), plan_push(), training_change_limit
        )

    def repair_manifest() -> PlanRepairManifestService:
        return PlanRepairManifestService(ctx.database(), authority())

    return SyncCommandServices(
        illness_pause,
        provider_refresh,
        conflicts,
        plan_push,
        authority,
        structured_plan_sync,
        repair_manifest,
    )


def coach_synchronous_refreshes(
    dependencies: SyncJobExecutionAssembly.Inputs,
) -> dict[str, SynchronousRefresh]:
    """Return the inline refreshes a waiting Coach request runs (Garmin, Wahoo)."""
    historical = dependencies.historical
    all_sync_days = historical.all_sync_days
    state = dependencies.state.sync_state_repository()
    return {
        GARMIN_ID: GarminSynchronousRefresh(
            dependencies.garmin.sync_service(),
            dependencies.garmin.morning_body_battery_service(),
            all_sync_days,
        ),
        WAHOO_ID: WahooSynchronousRefresh(
            dependencies.wahoo.sync_service(),
            all_sync_days,
            stored_days=lambda: state.sync_period(
                WAHOO_ID, historical.sync_period_defaults, all_sync_days
            ),
        ),
    }
