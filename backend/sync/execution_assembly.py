"""Composition for the persistent sync-job dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.sync import executor as sync_executor
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID


@dataclass(frozen=True)
class HistoricalSyncDependencies:
    local_now: Callable[[], datetime]
    sync_period_defaults: Mapping[str, int]
    all_sync_days: int
    sync_chunk_days: int
    sync_earliest_date: date


@dataclass(frozen=True)
class SyncJobStateDependencies:
    sync_state_repository: Callable[[], Any]
    queue_service: Callable[[], Any]
    outcome_service: Callable[[], Any]


@dataclass(frozen=True)
class IntervalsJobDependencies:
    selected_workout_sync_service: Callable[[], Any]
    competition_sync_service: Callable[[], Any]
    nutrition_sync_service: Callable[[], Any]
    operation_observer: Callable[[], SyncOperationObserver]
    resync_gate: ProviderResyncGate


@dataclass(frozen=True)
class GarminJobDependencies:
    sync_service: Callable[[], Any]
    morning_body_battery_service: Callable[[], Any]
    fixture_loader: Callable[[], Any]
    activity_detail_service: Callable[[], Any] | None = None
    strength_push_service: Callable[[], Any] | None = None
    wellness_history_service: Callable[[], Any] | None = None
    stream_backfill_service: Callable[[], Any] | None = None
    # The light change check that schedules the automatic refresh (#2303).
    change_check: Callable[[], Any] | None = None


@dataclass(frozen=True)
class WahooJobDependencies:
    """The Wahoo sync and plan-push services, resolved only when needed."""

    sync_service: Callable[[], Any]
    plan_push_service: Callable[[], Any]
    resync_gate: ProviderResyncGate
    stream_backfill_service: Callable[[], Any] | None = None


@dataclass(frozen=True)
class CalendarWeatherJobDependencies:
    calendar_sync_service: Callable[[], Any]
    weather_sync_service: Callable[[], Any]


def build_historical_owner(
    historical: HistoricalSyncDependencies, state: SyncJobStateDependencies
) -> sync_executor.HistoricalSyncJobOwner:
    """Create the historical sync owner over the current state services."""
    return sync_executor.HistoricalSyncJobOwner(
        sync_state_repository=state.sync_state_repository(),
        queue_service=state.queue_service(),
        local_now=historical.local_now,
        sync_period_defaults=historical.sync_period_defaults,
        all_sync_days=historical.all_sync_days,
        sync_chunk_days=historical.sync_chunk_days,
        sync_earliest_date=historical.sync_earliest_date,
    )


def build_intervals_owner(
    intervals: IntervalsJobDependencies,
) -> sync_executor.IntervalsSyncJobOwner:
    """Create the Intervals.icu output job owner."""
    return sync_executor.IntervalsSyncJobOwner(
        selected_workout_sync_service=intervals.selected_workout_sync_service(),
        competition_sync_service=intervals.competition_sync_service(),
        sync_operation_observer=intervals.operation_observer(),
        intervals_resync_gate=intervals.resync_gate,
    )


def build_garmin_owner(
    historical_sync: sync_executor.HistoricalSyncJobOwner,
    garmin: GarminJobDependencies,
    all_sync_days: int,
) -> sync_executor.GarminSyncJobOwner:
    """Create the Garmin job owner over the shared historical policy."""
    return sync_executor.GarminSyncJobOwner(
        historical_sync=historical_sync,
        garmin_sync_service=garmin.sync_service(),
        morning_body_battery_service=garmin.morning_body_battery_service(),
        garmin_fixture_loader=garmin.fixture_loader(),
        all_sync_days=all_sync_days,
        activity_detail_service=garmin.activity_detail_service()
        if garmin.activity_detail_service
        else None,
        wellness_history_service=garmin.wellness_history_service()
        if garmin.wellness_history_service
        else None,
        stream_backfill_service=garmin.stream_backfill_service()
        if garmin.stream_backfill_service
        else None,
    )


def build_calendar_weather_owner(
    calendar_weather: CalendarWeatherJobDependencies,
) -> sync_executor.CalendarWeatherSyncJobOwner:
    """Create the owner for the external calendar and weather providers."""
    return sync_executor.CalendarWeatherSyncJobOwner(
        external_calendar_sync_service=calendar_weather.calendar_sync_service(),
        weather_sync_service=calendar_weather.weather_sync_service(),
    )


class SyncJobExecutionAssembly:
    """Build the job dispatcher with one owner per provider.

    Intervals.icu and Garmin owners are rebuilt for each job, so credentials
    saved or removed in the app apply to the next job without a restart.
    """

    @dataclass(frozen=True)
    class Inputs:
        historical: HistoricalSyncDependencies
        state: SyncJobStateDependencies
        intervals: IntervalsJobDependencies
        garmin: GarminJobDependencies
        calendar_weather: CalendarWeatherJobDependencies
        wahoo: WahooJobDependencies

    def __init__(
        self,
        *,
        dependencies: SyncJobExecutionAssembly.Inputs,
        after_job: Callable[[Mapping[str, Any]], None] = lambda _job: None,
    ) -> None:
        self._deps = dependencies
        self._after_job = after_job

    def executor(self) -> sync_executor.SyncJobExecutor:
        """Create one dispatcher with shared historical sync policy."""
        deps = self._deps
        all_sync_days = deps.historical.all_sync_days

        def intervals() -> sync_executor.IntervalsJobAdapter:
            return sync_executor.IntervalsJobAdapter(
                jobs=build_intervals_owner(deps.intervals),
                nutrition_sync_service=deps.intervals.nutrition_sync_service(),
            )

        def garmin() -> sync_executor.GarminJobAdapter:
            historical_sync = build_historical_owner(deps.historical, deps.state)
            push = deps.garmin.strength_push_service
            return sync_executor.GarminJobAdapter(
                jobs=build_garmin_owner(historical_sync, deps.garmin, all_sync_days),
                plan_push=None if push is None else push(),
            )

        wahoo = deps.wahoo
        backfill = wahoo.stream_backfill_service
        calendar_weather = build_calendar_weather_owner(deps.calendar_weather)
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
                sync=wahoo.sync_service(),
                plan_push=wahoo.plan_push_service(),
                stream_backfill=None if backfill is None else backfill(),
            ),
        }
        return sync_executor.SyncJobExecutor(
            job_owners=job_owners,
            historical_sync=build_historical_owner(deps.historical, deps.state),
            outcome_service=deps.state.outcome_service(),
            all_sync_days=all_sync_days,
            after_job=self._after_job,
        )
