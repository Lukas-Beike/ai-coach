"""Composition for daily and startup synchronization scheduling."""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.athlete.profile import ProfileService
from backend.config import Config
from backend.db.manager import DatabaseManager, background_writer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import scheduler
from backend.sync.backfill_resume import BackfillChainResumer
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_assembly import WahooJobDependencies
from backend.sync.garmin_change_check import GarminChangeCheck
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.queue import SyncJobQueueService
from backend.sync.schedule_policies import (
    ProviderSchedulePolicy,
    WahooSchedulePolicy,
    build_schedule_policies,
)
from backend.sync.state import SyncStateRepository


@dataclass(frozen=True)
class SyncScheduleOwners:
    profile_service: Callable[[], ProfileService]
    queue_service: Callable[[], SyncJobQueueService]
    daily_sync_marker_service: Callable[[], DailySyncMarkerService]
    garmin_sync_service: Callable[[], GarminSyncService]


@dataclass(frozen=True)
class SyncSchedulePersistence:
    sync_state_repository: Callable[[], SyncStateRepository]
    # Whether a provider's failed refresh holds its next automatic attempt.
    retry_held: Callable[[str], bool] | None = None


@dataclass(frozen=True)
class SyncScheduleControls:
    maintenance_gate: MaintenanceGate
    sleep: Callable[[float], None]


@dataclass(frozen=True)
class SyncSchedulePolicy:
    config: Callable[[], Config]
    garmin_automatic_sync_days: int
    auto_update_label: str
    sync_chunk_days: int
    sync_earliest_date: date


@dataclass(frozen=True)
class DailySyncLoopSettings:
    morning_body_battery_service: Callable[[], Any]
    logger: logging.Logger
    # Enables the idle WAL checkpoint of the loop when given.
    database_manager: Callable[[], DatabaseManager] | None = None
    # Whether the morning reading runs on this pass (the Garmin change check).
    morning_due: Callable[[], bool] | None = None


@dataclass(frozen=True)
class SyncScheduleProviders:
    """Provider owners the schedule policies read, resolved per scheduler build."""

    garmin_resync_gate: ProviderResyncGate
    weather_refresh_due: Callable[[], bool]
    wahoo: WahooJobDependencies
    sync_period_defaults: Mapping[str, int]
    all_sync_days: int
    # The light change check that schedules the automatic Garmin refresh (#2303).
    garmin_change_check: Callable[[], GarminChangeCheck] | None = None


class SyncSchedulerAssembly:
    """Create configured scheduler and daily-loop objects on demand.

    Schedule policies are built fresh for each scheduler, so a scheduler sees
    the configuration of the moment it was built.
    """

    @dataclass(frozen=True)
    class Inputs:
        owners: SyncScheduleOwners
        persistence: SyncSchedulePersistence
        controls: SyncScheduleControls
        policy: SyncSchedulePolicy
        daily_loop: DailySyncLoopSettings
        providers: SyncScheduleProviders

    def __init__(
        self,
        *,
        dependencies: SyncSchedulerAssembly.Inputs,
    ) -> None:
        owners = dependencies.owners
        persistence = dependencies.persistence
        controls = dependencies.controls
        policy = dependencies.policy
        daily_loop = dependencies.daily_loop
        self._profile_service = owners.profile_service
        self._queue_service = owners.queue_service
        self._daily_sync_marker_service = owners.daily_sync_marker_service
        self._garmin_sync_service = owners.garmin_sync_service
        self._sync_state_repository = persistence.sync_state_repository
        self._retry_held = persistence.retry_held
        self._maintenance_gate = controls.maintenance_gate
        self._sleep = controls.sleep
        self._config = policy.config
        self._garmin_automatic_sync_days = policy.garmin_automatic_sync_days
        self._auto_update_label = policy.auto_update_label
        self._sync_chunk_days = policy.sync_chunk_days
        self._sync_earliest_date = policy.sync_earliest_date
        self._morning_body_battery_service = daily_loop.morning_body_battery_service
        self._logger = daily_loop.logger
        self._database_manager = daily_loop.database_manager
        self._morning_due = daily_loop.morning_due
        self._providers = dependencies.providers

    def daily_scheduler(self) -> scheduler.DailySyncScheduler:
        """Create a daily schedule using the current provider configuration."""
        config = self._config()
        calendar_enabled = bool(config.calendar_ical_url)
        profile = self._profile_service()
        queue = self._queue_service()
        markers = self._daily_sync_marker_service()
        garmin = self._garmin_sync_service()
        return scheduler.DailySyncScheduler(
            queue,
            markers,
            self._maintenance_gate,
            config=scheduler.DailySyncSchedulerConfig(
                auto_update_label=self._auto_update_label,
            ),
            schedule_policies=self._schedule_policies(
                profile=profile,
                garmin=garmin,
                calendar_enabled=calendar_enabled,
            ),
            retry_held=self._retry_held,
            backfill_resumer=self.backfill_resumer().resume,
        )

    def backfill_resumer(self) -> BackfillChainResumer:
        """Create the resumer of stopped backfill chains for the current providers."""
        config = self._config()
        profile = self._profile_service()
        garmin = self._garmin_sync_service()
        return BackfillChainResumer(
            self._queue_service(),
            self._sync_state_repository(),
            self._schedule_policies(
                profile=profile,
                garmin=garmin,
                calendar_enabled=bool(config.calendar_ical_url),
            ),
            chunk_days=self._sync_chunk_days,
            earliest_date=self._sync_earliest_date,
        )

    def startup_scheduler(self) -> scheduler.StartupSyncScheduler:
        """Create a startup schedule using the current provider configuration."""
        config = self._config()
        calendar_enabled = bool(config.calendar_ical_url)
        profile = self._profile_service()
        queue = self._queue_service()
        garmin = self._garmin_sync_service()
        sync_state = self._sync_state_repository()
        return scheduler.StartupSyncScheduler(
            queue,
            sync_state,
            config=scheduler.StartupSyncSchedulerConfig(
                sync_chunk_days=self._sync_chunk_days,
                sync_earliest_date=self._sync_earliest_date,
            ),
            schedule_policies=self._schedule_policies(
                profile=profile,
                garmin=garmin,
                calendar_enabled=calendar_enabled,
            ),
        )

    def _schedule_policies(
        self,
        *,
        profile: ProfileService,
        garmin: GarminSyncService,
        calendar_enabled: bool,
    ) -> Mapping[str, ProviderSchedulePolicy]:
        """Build the provider policies from the snapshot taken by the caller."""
        providers = self._providers
        wahoo = providers.wahoo
        change_check = providers.garmin_change_check
        return build_schedule_policies(
            profile=profile,
            garmin=garmin,
            calendar_enabled=calendar_enabled,
            garmin_automatic_sync_days=self._garmin_automatic_sync_days,
            garmin_resync_gate=providers.garmin_resync_gate,
            garmin_change_check=None if change_check is None else change_check(),
            weather_refresh_due=providers.weather_refresh_due,
            wahoo=WahooSchedulePolicy(
                configured=lambda: wahoo.sync_service().configured(),
                sync_state=self._sync_state_repository(),
                sync_period_defaults=providers.sync_period_defaults,
                all_sync_days=providers.all_sync_days,
                resync_gate=wahoo.resync_gate,
            ),
        )

    def daily_loop(self) -> scheduler.DailySyncLoop:
        """Create the unstarted periodic loop and its stop event."""
        return scheduler.DailySyncLoop(
            self.daily_scheduler(),
            self._morning_body_battery_service(),
            sleep=self._sleep,
            logger=self._logger,
            stop_event=threading.Event(),
            housekeeping=self._queue_service().prune_finished,
            wal_checkpoint=(
                None
                if self._database_manager is None
                else functools.partial(self._checkpoint_wal, self._database_manager)
            ),
            morning_due=self._morning_due,
        )

    def _checkpoint_wal(self, database_manager: Callable[[], DatabaseManager]) -> None:
        """Truncate the WAL as deferrable work behind foreground writers."""
        with self._maintenance_gate.operation(), background_writer():
            database_manager().checkpoint_wal()
