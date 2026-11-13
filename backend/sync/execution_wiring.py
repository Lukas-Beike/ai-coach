"""Build the persistent sync-job dispatcher and the configured checks (#2101).

The dispatcher has one owner per provider. The Intervals.icu and Garmin owners
are built for each job and every service reads the live configuration and
owners from the application context, so credentials saved or removed in the app
apply to the next job without a restart.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.context import AppContext
from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.runtime import clock as runtime_clock
from backend.sync import executor as sync_executor
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.schedule_policies import WeatherSchedulePolicy
from backend.sync.wiring import SyncWindow


@dataclass(frozen=True)
class SyncJobExecutionServices:
    executor: Callable[[], sync_executor.SyncJobExecutor]


def build_sync_job_execution(
    ctx: AppContext,
    *,
    window: SyncWindow,
    selected_workout_sync_service: Callable[[], Any],
    competition_sync_service: Callable[[], Any],
    weather_sync_service: Callable[[], Any],
    intervals_resync_gate: ProviderResyncGate,
    after_job: Callable[[Mapping[str, Any]], None],
) -> SyncJobExecutionServices:
    """The dispatcher over the live provider owners.

    The composition root passes the shared history window, the Intervals.icu
    output services built in the flows, the weather sync, the Intervals.icu resync
    gate and the derived-data hook that runs after every job.
    """
    all_sync_days = window.all_sync_days

    def historical_owner() -> sync_executor.HistoricalSyncJobOwner:
        """The historical sync owner over the current state services."""
        return sync_executor.HistoricalSyncJobOwner(
            sync_state_repository=ctx.sync_persistence.state_repository(),
            queue_service=ctx.sync_job_queue.service(),
            local_now=ctx.clock.now,
            sync_period_defaults=window.sync_period_defaults,
            all_sync_days=all_sync_days,
            sync_chunk_days=window.sync_chunk_days,
            sync_earliest_date=window.sync_earliest_date,
        )

    def record_intervals_output(key: str) -> None:
        with ctx.database().unit_of_work() as db:
            ctx.key_values.set(db, key, runtime_clock.utc_now())

    def intervals() -> sync_executor.IntervalsJobAdapter:
        return sync_executor.IntervalsJobAdapter(
            jobs=sync_executor.IntervalsSyncJobOwner(
                selected_workout_sync_service=selected_workout_sync_service(),
                competition_sync_service=competition_sync_service(),
                sync_operation_observer=ctx.provider_sync.operation_observer(),
                intervals_resync_gate=intervals_resync_gate,
            ),
            nutrition_sync_service=ctx.nutrition.intervals_sync_service(),
            record_output=record_intervals_output,
        )

    def garmin() -> sync_executor.GarminJobAdapter:
        owner = historical_owner()
        return sync_executor.GarminJobAdapter(
            jobs=sync_executor.GarminSyncJobOwner(
                historical_sync=owner,
                garmin_sync_service=ctx.garmin.sync_service(),
                morning_body_battery_service=ctx.morning_body_battery_service(),
                garmin_fixture_loader=ctx.garmin.fixture_loader(),
                all_sync_days=all_sync_days,
                activity_detail_service=ctx.garmin.activity_detail_service(),
                wellness_history_service=ctx.garmin.wellness_history_service(),
                stream_backfill_service=ctx.garmin.stream_backfill_service(),
            ),
            plan_push=ctx.garmin.strength_push_service(),
        )

    def executor() -> sync_executor.SyncJobExecutor:
        """Create one dispatcher with the shared historical sync policy."""
        calendar_weather = sync_executor.CalendarWeatherSyncJobOwner(
            external_calendar_sync_service=ctx.external_calendar.sync_service(),
            weather_sync_service=weather_sync_service(),
        )
        job_owners: dict[str, sync_executor.ProviderJobOwner] = {
            INTERVALS_ID: sync_executor.PerJobOwner(intervals),
            GARMIN_ID: sync_executor.PerJobOwner(garmin),
            WEATHER_ID: sync_executor.CalendarWeatherJobAdapter(
                jobs=calendar_weather, provider_id=WEATHER_ID
            ),
            CALENDAR_ID: sync_executor.CalendarWeatherJobAdapter(
                jobs=calendar_weather, provider_id=CALENDAR_ID
            ),
            WAHOO_ID: sync_executor.WahooJobAdapter(
                sync=ctx.wahoo.sync_service(),
                plan_push=ctx.wahoo.plan_push_service(),
                stream_backfill=ctx.wahoo.stream_backfill_service(),
            ),
        }
        return sync_executor.SyncJobExecutor(
            job_owners=job_owners,
            historical_sync=historical_owner(),
            outcome_service=ctx.sync_job_queue.outcome_service(),
            all_sync_days=all_sync_days,
            after_job=after_job,
        )

    return SyncJobExecutionServices(executor)


def provider_configured_checks(ctx: AppContext) -> dict[str, Callable[[], bool]]:
    """Return each provider's live "has the settings it needs" check."""
    return {
        INTERVALS_ID: lambda: bool(ctx.config().intervals_api_key),
        GARMIN_ID: lambda: bool(ctx.garmin.sync_service().configured()),
        WEATHER_ID: lambda: WeatherSchedulePolicy(ctx.athlete.profile()).configured(),
        CALENDAR_ID: lambda: bool(ctx.config().calendar_ical_url),
        WAHOO_ID: lambda: bool(ctx.wahoo.sync_service().configured()),
    }


def configured_for_job(
    checks: Mapping[str, Callable[[], bool]], job_type: str
) -> tuple[str, ...]:
    """Return the configured providers that accept the job type, in table order."""
    registry = DEFAULT_PROVIDER_REGISTRY
    return tuple(
        provider_id
        for provider_id in registry.ids()
        if registry.supports_job(provider_id, job_type) and checks[provider_id]()
    )
