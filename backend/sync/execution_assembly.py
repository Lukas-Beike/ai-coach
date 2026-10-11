"""Composition for the persistent sync-job dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.sync import executor as sync_executor
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_runtime import ProviderRuntimeRegistry


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
    sync_service: Callable[[], Any]
    performance_refresh_service: Callable[[], Any]
    selected_workout_sync_service: Callable[[], Any]
    competition_sync_service: Callable[[], Any]
    nutrition_sync_service: Callable[[], Any]
    operation_observer: Callable[[], SyncOperationObserver]
    resync_gate: ProviderResyncGate
    activity_detail_service: Callable[[], Any] | None = None


@dataclass(frozen=True)
class GarminJobDependencies:
    sync_service: Callable[[], Any]
    morning_body_battery_service: Callable[[], Any]
    fixture_loader: Callable[[], Any]


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
    historical_sync: sync_executor.HistoricalSyncJobOwner,
    intervals: IntervalsJobDependencies,
) -> sync_executor.IntervalsSyncJobOwner:
    """Create the Intervals.icu job owner; activity detail is optional."""
    return sync_executor.IntervalsSyncJobOwner(
        historical_sync=historical_sync,
        intervals_sync_service=intervals.sync_service(),
        performance_refresh_service=intervals.performance_refresh_service(),
        selected_workout_sync_service=intervals.selected_workout_sync_service(),
        competition_sync_service=intervals.competition_sync_service(),
        sync_operation_observer=intervals.operation_observer(),
        intervals_resync_gate=intervals.resync_gate,
        activity_detail_service=intervals.activity_detail_service()
        if intervals.activity_detail_service
        else None,
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
    """Build provider job routing over explicit domain service factories.

    Without ``provider_runtime`` the built-in owners are composed directly. With
    it, the dispatcher routes through the registry's job owners instead.
    """

    @dataclass(frozen=True)
    class Inputs:
        historical: HistoricalSyncDependencies
        state: SyncJobStateDependencies
        intervals: IntervalsJobDependencies
        garmin: GarminJobDependencies
        calendar_weather: CalendarWeatherJobDependencies

    def __init__(
        self,
        *,
        dependencies: SyncJobExecutionAssembly.Inputs,
        provider_runtime: Callable[[], ProviderRuntimeRegistry] | None = None,
    ) -> None:
        self._historical = dependencies.historical
        self._state = dependencies.state
        self._intervals = dependencies.intervals
        self._garmin = dependencies.garmin
        self._calendar_weather = dependencies.calendar_weather
        self._provider_runtime = provider_runtime

    def executor(self) -> sync_executor.SyncJobExecutor:
        """Create one dispatcher with shared historical sync policy."""
        if self._provider_runtime is not None:
            return self._runtime_executor(self._provider_runtime())
        historical_sync = build_historical_owner(self._historical, self._state)
        nutrition_sync_service = self._intervals.nutrition_sync_service()
        intervals_jobs = build_intervals_owner(historical_sync, self._intervals)
        garmin_jobs = build_garmin_owner(
            historical_sync, self._garmin, self._historical.all_sync_days
        )
        calendar_weather_jobs = build_calendar_weather_owner(self._calendar_weather)
        job_owners = sync_executor.build_job_owners(
            intervals_jobs=intervals_jobs,
            nutrition_sync_service=nutrition_sync_service,
            garmin_jobs=garmin_jobs,
            calendar_weather_jobs=calendar_weather_jobs,
        )
        return sync_executor.SyncJobExecutor(
            job_owners=job_owners,
            historical_sync=historical_sync,
            outcome_service=self._state.outcome_service(),
            all_sync_days=self._historical.all_sync_days,
        )

    def _runtime_executor(
        self, runtime: ProviderRuntimeRegistry
    ) -> sync_executor.SyncJobExecutor:
        return sync_executor.SyncJobExecutor(
            job_owners=runtime.job_owners(),
            historical_sync=build_historical_owner(self._historical, self._state),
            outcome_service=self._state.outcome_service(),
            all_sync_days=self._historical.all_sync_days,
            registry=runtime.static,
        )
