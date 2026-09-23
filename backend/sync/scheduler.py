"""Schedule due daily provider refreshes in their established order."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.athlete.profile import ProfileService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository


@dataclass(frozen=True)
class DailySyncSchedulerConfig:
    calendar_url_enabled: bool
    intervals_key_enabled: bool
    garmin_automatic_sync_days: int
    auto_update_label: str
    sync_period_defaults: Mapping[str, int]
    all_sync_days: int


class DailySyncScheduler:
    """Own the order and eligibility decisions for daily refresh jobs."""

    def __init__(
        self,
        profile: ProfileService,
        queue: SyncJobQueueService,
        markers: DailySyncMarkerService,
        garmin: GarminSyncService,
        database: DatabaseManager,
        key_values: KeyValueRepository,
        database_lock: Any,
        sync_state: SyncStateRepository,
        intervals_resync_gate: ProviderResyncGate,
        maintenance_gate: MaintenanceGate,
        *,
        config: DailySyncSchedulerConfig,
    ) -> None:
        self._profile = profile
        self._queue = queue
        self._markers = markers
        self._garmin = garmin
        self._database = database
        self._key_values = key_values
        self._database_lock = database_lock
        self._sync_state = sync_state
        self._intervals_resync_gate = intervals_resync_gate
        self._maintenance_gate = maintenance_gate
        self._config = config

    def schedule(self) -> None:
        """Enqueue eligible weather, calendar, Garmin, and Intervals jobs."""
        with self._maintenance_gate.operation():
            self._schedule_weather()
            self._schedule_calendar()
            self._schedule_garmin()
            self._schedule_intervals()

    def _schedule_weather(self) -> None:
        if not self._profile.get().get("weather_location", "").strip() or self._queue.active("weather"):
            return
        self._queue.enqueue(
            "weather",
            "refresh",
            {"force": False, "reason": self._config.auto_update_label},
            requested_by="scheduler",
        )

    def _schedule_calendar(self) -> None:
        if (
            not self._config.calendar_url_enabled
            or not self._markers.is_due("calendar")
            or self._queue.active("calendar")
        ):
            return
        self._queue.enqueue(
            "calendar",
            "refresh",
            {"reason": self._config.auto_update_label},
            requested_by="scheduler",
        )

    def _schedule_garmin(self) -> None:
        if (
            not self._garmin.configured()
            or not self._markers.is_due("garmin")
            or self._queue.active("garmin")
        ):
            return
        self._queue.enqueue(
            "garmin",
            "refresh",
            {
                "days": self._config.garmin_automatic_sync_days,
                "reason": self._config.auto_update_label,
            },
            requested_by="scheduler",
        )

    def _schedule_intervals(self) -> None:
        if (
            not self._config.intervals_key_enabled
            or not self._markers.is_due("intervals")
            or self._sync_running()
            or self._intervals_resync_gate.is_resetting()
        ):
            return
        if self._queue.active("intervals"):
            return
        self._queue.enqueue(
            "intervals",
            "refresh",
            {
                "days": self._sync_state.sync_period(
                    "intervals",
                    self._config.sync_period_defaults,
                    self._config.all_sync_days,
                ),
                "reason": self._config.auto_update_label,
            },
            requested_by="scheduler",
        )

    def _sync_running(self) -> bool:
        with self._database_lock, self._database.unit_of_work() as db:
            return self._key_values.get(db, "sync_running") == "1"


class DailySyncLoop:
    """Run daily scheduling and morning battery refresh on a fixed cadence."""

    def __init__(
        self,
        daily_scheduler: DailySyncScheduler,
        morning_battery: MorningBodyBatteryService,
        *,
        sleep: Callable[[float], None],
        logger: logging.Logger,
    ) -> None:
        self._daily_scheduler = daily_scheduler
        self._morning_battery = morning_battery
        self._sleep = sleep
        self._logger = logger

    def run(self) -> None:
        while True:
            self._sleep(300)
            try:
                self._daily_scheduler.schedule()
                self._morning_battery.refresh()
            except AppError as exc:
                if exc.reason != "maintenance":
                    self._logger.error(
                        "Automatic synchronization scheduling failed",
                        extra={"event": "daily_sync_failed"},
                    )


@dataclass(frozen=True)
class StartupSyncSchedulerConfig:
    calendar_enabled: bool
    intervals_enabled: bool
    garmin_automatic_sync_days: int
    sync_period_defaults: Mapping[str, int]
    all_sync_days: int
    sync_chunk_days: int
    sync_earliest_date: date


class StartupSyncScheduler:
    """Enqueue configured startup refreshes and historical backfills."""

    def __init__(
        self,
        profile: ProfileService,
        queue: SyncJobQueueService,
        garmin: GarminSyncService,
        sync_state: SyncStateRepository,
        *,
        config: StartupSyncSchedulerConfig,
    ) -> None:
        self._profile = profile
        self._queue = queue
        self._garmin = garmin
        self._sync_state = sync_state
        self._config = config

    def schedule(self) -> None:
        """Queue startup work in the established provider order."""
        self._schedule_calendar()
        self._schedule_intervals()
        self._schedule_garmin()
        self._schedule_weather()

    def _schedule_calendar(self) -> None:
        if self._config.calendar_enabled and not self._queue.active("calendar", "refresh"):
            self._queue.enqueue(
                "calendar", "refresh", {"reason": "startup"}, requested_by="startup"
            )

    def _schedule_intervals(self) -> None:
        if not self._config.intervals_enabled:
            return
        if not self._queue.active("intervals", "refresh"):
            self._queue.enqueue(
                "intervals",
                "refresh",
                {
                    "days": self._sync_state.sync_period(
                        "intervals",
                        self._config.sync_period_defaults,
                        self._config.all_sync_days,
                    ),
                    "reason": "startup",
                },
                requested_by="startup",
            )
        self._enqueue_historical_backfill("intervals")

    def _schedule_garmin(self) -> None:
        if not self._garmin.configured():
            return
        if not self._queue.active("garmin", "refresh"):
            self._queue.enqueue(
                "garmin",
                "refresh",
                {
                    "days": self._config.garmin_automatic_sync_days,
                    "reason": "startup",
                },
                requested_by="startup",
            )
        self._enqueue_historical_backfill("garmin")

    def _schedule_weather(self) -> None:
        location = self._profile.get().get("weather_location", "")
        if location.strip() and not self._queue.active("weather", "refresh"):
            self._queue.enqueue(
                "weather",
                "refresh",
                {"force": True, "reason": "startup"},
                requested_by="startup",
            )

    def _enqueue_historical_backfill(self, provider: str) -> None:
        if self._queue.active(provider, "historical_backfill"):
            return
        payload = self._historical_backfill_payload(provider)
        if payload is not None:
            self._queue.enqueue(
                provider,
                "historical_backfill",
                payload,
                requested_by="startup",
            )

    def _historical_backfill_payload(self, provider: str) -> dict[str, Any] | None:
        cursor = self._sync_state.cursor(provider, "historical").get("cursor")
        if cursor and str(cursor) <= self._config.sync_earliest_date.isoformat():
            return None
        try:
            resume_end = (
                date.fromisoformat(str(cursor)[:10]) - timedelta(days=1)
                if cursor
                else None
            )
        except ValueError:
            resume_end = None
        payload: dict[str, Any] = {
            "days": self._config.sync_chunk_days,
            "reason": "startup historical backfill",
        }
        if resume_end is not None:
            payload["end_date"] = resume_end.isoformat()
        return payload
