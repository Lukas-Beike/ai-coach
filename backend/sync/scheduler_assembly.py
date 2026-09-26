"""Composition for daily and startup synchronization scheduling."""

from __future__ import annotations

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


class SyncSchedulerAssembly:
    """Create configured scheduler and daily-loop objects on demand."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        profile_service: Callable[[], ProfileService],
        queue_service: Callable[[], SyncJobQueueService],
        daily_sync_marker_service: Callable[[], DailySyncMarkerService],
        garmin_sync_service: Callable[[], GarminSyncService],
        database_manager: Callable[[], DatabaseManager],
        key_values: KeyValueRepository,
        database_lock: Any,
        sync_state_repository: Callable[[], SyncStateRepository],
        intervals_resync_gate: ProviderResyncGate,
        maintenance_gate: MaintenanceGate,
        morning_body_battery_service: Callable[[], Any],
        sleep: Callable[[float], None],
        logger: logging.Logger,
        garmin_automatic_sync_days: int,
        auto_update_label: str,
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
        sync_chunk_days: int,
        sync_earliest_date: date,
    ) -> None:
        self._config = config
        self._profile_service = profile_service
        self._queue_service = queue_service
        self._daily_sync_marker_service = daily_sync_marker_service
        self._garmin_sync_service = garmin_sync_service
        self._database_manager = database_manager
        self._key_values = key_values
        self._database_lock = database_lock
        self._sync_state_repository = sync_state_repository
        self._intervals_resync_gate = intervals_resync_gate
        self._maintenance_gate = maintenance_gate
        self._morning_body_battery_service = morning_body_battery_service
        self._sleep = sleep
        self._logger = logger
        self._garmin_automatic_sync_days = garmin_automatic_sync_days
        self._auto_update_label = auto_update_label
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._sync_chunk_days = sync_chunk_days
        self._sync_earliest_date = sync_earliest_date

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
