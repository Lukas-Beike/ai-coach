"""Composition for daily and startup synchronization scheduling."""

from __future__ import annotations

from dataclasses import dataclass

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from backend.athlete.profile import ProfileService
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import scheduler
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository


@dataclass(frozen=True)
class SyncScheduleOwners:
    profile_service: Callable[[], ProfileService]
    queue_service: Callable[[], SyncJobQueueService]
    daily_sync_marker_service: Callable[[], DailySyncMarkerService]
    garmin_sync_service: Callable[[], GarminSyncService]


@dataclass(frozen=True)
class SyncSchedulePersistence:
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    database_lock: Any
    sync_state_repository: Callable[[], SyncStateRepository]


@dataclass(frozen=True)
class SyncScheduleControls:
    intervals_resync_gate: ProviderResyncGate
    maintenance_gate: MaintenanceGate
    sleep: Callable[[float], None]


@dataclass(frozen=True)
class SyncSchedulePolicy:
    config: Callable[[], Config]
    garmin_automatic_sync_days: int
    auto_update_label: str
    sync_period_defaults: Mapping[str, int]
    all_sync_days: int
    sync_chunk_days: int
    sync_earliest_date: date


@dataclass(frozen=True)
class DailySyncLoopSettings:
    morning_body_battery_service: Callable[[], Any]
    logger: logging.Logger


class SyncSchedulerAssembly:
    """Create configured scheduler and daily-loop objects on demand."""

    @dataclass(frozen=True)
    class Inputs:
        owners: SyncScheduleOwners
        persistence: SyncSchedulePersistence
        controls: SyncScheduleControls
        policy: SyncSchedulePolicy
        daily_loop: DailySyncLoopSettings

    def __init__(self, *, dependencies: "SyncSchedulerAssembly.Inputs") -> None:
        owners = dependencies.owners
        persistence = dependencies.persistence
        controls = dependencies.controls
        policy = dependencies.policy
        daily_loop = dependencies.daily_loop
        self._profile_service = owners.profile_service
        self._queue_service = owners.queue_service
        self._daily_sync_marker_service = owners.daily_sync_marker_service
        self._garmin_sync_service = owners.garmin_sync_service
        self._database_manager = persistence.database_manager
        self._key_values = persistence.key_values
        self._database_lock = persistence.database_lock
        self._sync_state_repository = persistence.sync_state_repository
        self._intervals_resync_gate = controls.intervals_resync_gate
        self._maintenance_gate = controls.maintenance_gate
        self._sleep = controls.sleep
        self._config = policy.config
        self._garmin_automatic_sync_days = policy.garmin_automatic_sync_days
        self._auto_update_label = policy.auto_update_label
        self._sync_period_defaults = policy.sync_period_defaults
        self._all_sync_days = policy.all_sync_days
        self._sync_chunk_days = policy.sync_chunk_days
        self._sync_earliest_date = policy.sync_earliest_date
        self._morning_body_battery_service = daily_loop.morning_body_battery_service
        self._logger = daily_loop.logger

    def daily_scheduler(self) -> scheduler.DailySyncScheduler:
        """Create a daily schedule using the current provider configuration."""
        config = self._config()
        return scheduler.DailySyncScheduler(
            self._profile_service(),
            self._queue_service(),
            self._daily_sync_marker_service(),
            self._garmin_sync_service(),
            self._database_manager(),
            self._key_values,
            self._database_lock,
            self._sync_state_repository(),
            self._intervals_resync_gate,
            self._maintenance_gate,
            config=scheduler.DailySyncSchedulerConfig(
                calendar_url_enabled=bool(config.calendar_ical_url),
                intervals_key_enabled=bool(config.intervals_api_key),
                garmin_automatic_sync_days=self._garmin_automatic_sync_days,
                auto_update_label=self._auto_update_label,
                sync_period_defaults=self._sync_period_defaults,
                all_sync_days=self._all_sync_days,
            ),
        )

    def startup_scheduler(self) -> scheduler.StartupSyncScheduler:
        """Create a startup schedule using the current provider configuration."""
        config = self._config()
        return scheduler.StartupSyncScheduler(
            self._profile_service(),
            self._queue_service(),
            self._garmin_sync_service(),
            self._sync_state_repository(),
            config=scheduler.StartupSyncSchedulerConfig(
                calendar_enabled=bool(config.calendar_ical_url),
                intervals_enabled=bool(config.intervals_api_key),
                garmin_automatic_sync_days=self._garmin_automatic_sync_days,
                sync_period_defaults=self._sync_period_defaults,
                all_sync_days=self._all_sync_days,
                sync_chunk_days=self._sync_chunk_days,
                sync_earliest_date=self._sync_earliest_date,
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
        )
