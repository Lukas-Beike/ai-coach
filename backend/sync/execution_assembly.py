"""Composition for the persistent sync-job dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from backend.sync import executor as sync_executor
from backend.sync.observation import SyncOperationObserver
from backend.sync.gates import ProviderResyncGate


class SyncJobExecutionAssembly:
    """Build provider job routing over explicit domain service factories."""

    def __init__(
        self,
        *,
        sync_state_repository: Callable[[], Any],
        queue_service: Callable[[], Any],
        local_now: Callable[[], datetime],
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
        sync_chunk_days: int,
        sync_earliest_date: date,
        intervals_sync_service: Callable[[], Any],
        performance_refresh_service: Callable[[], Any],
        selected_workout_sync_service: Callable[[], Any],
        competition_sync_service: Callable[[], Any],
        operation_observer: Callable[[], SyncOperationObserver],
        intervals_resync_gate: ProviderResyncGate,
        garmin_sync_service: Callable[[], Any],
        morning_body_battery_service: Callable[[], Any],
        garmin_fixture_loader: Callable[[], Any],
        external_calendar_sync_service: Callable[[], Any],
        weather_sync_service: Callable[[], Any],
        outcome_service: Callable[[], Any],
    ) -> None:
        self._sync_state_repository = sync_state_repository
        self._queue_service = queue_service
        self._local_now = local_now
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._sync_chunk_days = sync_chunk_days
        self._sync_earliest_date = sync_earliest_date
        self._intervals_sync_service = intervals_sync_service
        self._performance_refresh_service = performance_refresh_service
        self._selected_workout_sync_service = selected_workout_sync_service
        self._competition_sync_service = competition_sync_service
        self._operation_observer = operation_observer
        self._intervals_resync_gate = intervals_resync_gate
        self._garmin_sync_service = garmin_sync_service
        self._morning_body_battery_service = morning_body_battery_service
        self._garmin_fixture_loader = garmin_fixture_loader
        self._external_calendar_sync_service = external_calendar_sync_service
        self._weather_sync_service = weather_sync_service
        self._outcome_service = outcome_service

    def executor(self) -> sync_executor.SyncJobExecutor:
        """Create one dispatcher with shared historical sync policy."""
        historical_sync = sync_executor.HistoricalSyncJobOwner(
            sync_state_repository=self._sync_state_repository(),
            queue_service=self._queue_service(),
            local_now=self._local_now,
            sync_period_defaults=self._sync_period_defaults,
            all_sync_days=self._all_sync_days,
            sync_chunk_days=self._sync_chunk_days,
            sync_earliest_date=self._sync_earliest_date,
        )
        provider_dispatcher = sync_executor.SyncJobProviderDispatcher(
            intervals_jobs=sync_executor.IntervalsSyncJobOwner(
                historical_sync=historical_sync,
                intervals_sync_service=self._intervals_sync_service(),
                performance_refresh_service=self._performance_refresh_service(),
                selected_workout_sync_service=self._selected_workout_sync_service(),
                competition_sync_service=self._competition_sync_service(),
                sync_operation_observer=self._operation_observer(),
                intervals_resync_gate=self._intervals_resync_gate,
            ),
            garmin_jobs=sync_executor.GarminSyncJobOwner(
                historical_sync=historical_sync,
                garmin_sync_service=self._garmin_sync_service(),
                morning_body_battery_service=self._morning_body_battery_service(),
                garmin_fixture_loader=self._garmin_fixture_loader(),
                all_sync_days=self._all_sync_days,
            ),
            calendar_weather_jobs=sync_executor.CalendarWeatherSyncJobOwner(
                external_calendar_sync_service=self._external_calendar_sync_service(),
                weather_sync_service=self._weather_sync_service(),
            ),
        )
        return sync_executor.SyncJobExecutor(
            provider_dispatcher=provider_dispatcher,
            historical_sync=historical_sync,
            outcome_service=self._outcome_service(),
            all_sync_days=self._all_sync_days,
        )
