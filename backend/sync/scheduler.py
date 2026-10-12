"""Schedule due daily provider refreshes in their established order."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.athlete.profile import ProfileService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import ProviderSchedulePolicy
from backend.sync.queue import SyncJobQueueService
from backend.sync.schedule_policies import build_schedule_policies, intervals_busy
from backend.sync.state import SyncStateRepository

AUTO_UPDATE_LABEL = "stündliche automatische Aktualisierung"
_HISTORICAL_BACKFILL = "historical_backfill"


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
        schedule_policies: Mapping[str, ProviderSchedulePolicy] | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self._queue = queue
        self._markers = markers
        self._database = database
        self._key_values = key_values
        self._database_lock = database_lock
        self._intervals_resync_gate = intervals_resync_gate
        self._maintenance_gate = maintenance_gate
        self._config = config
        self._registry = DEFAULT_PROVIDER_REGISTRY if registry is None else registry
        self._daily_marker_ids = self._registry.daily_marker_ids()
        self._policies: Mapping[str, ProviderSchedulePolicy] = (
            build_schedule_policies(
                profile=profile,
                garmin=garmin,
                sync_state=sync_state,
                calendar_enabled=config.calendar_url_enabled,
                intervals_enabled=config.intervals_key_enabled,
                garmin_automatic_sync_days=config.garmin_automatic_sync_days,
                sync_period_defaults=config.sync_period_defaults,
                all_sync_days=config.all_sync_days,
                intervals_blocked=self._intervals_blocked,
            )
            if schedule_policies is None
            else schedule_policies
        )

    def schedule(self) -> None:
        """Enqueue eligible refresh jobs in the registry's daily rank order."""
        with self._maintenance_gate.operation():
            for provider_id in self._registry.daily_order():
                policy = self._policies.get(provider_id)
                if policy is not None:
                    self._schedule_provider(provider_id, policy)

    def _schedule_provider(
        self, provider_id: str, policy: ProviderSchedulePolicy
    ) -> None:
        if not policy.configured():
            return
        if provider_id in self._daily_marker_ids and not self._markers.is_due(
            provider_id
        ):
            return
        if policy.blocked() or self._queue.active(provider_id):
            return
        self._queue.enqueue(
            provider_id,
            "refresh",
            policy.refresh_payload("daily", self._config.auto_update_label),
            requested_by="scheduler",
        )

    def _intervals_blocked(self) -> bool:
        return intervals_busy(
            self._database,
            self._key_values,
            self._database_lock,
            self._intervals_resync_gate,
        )


class DailySyncLoop:
    """Run daily scheduling and morning battery refresh on a fixed cadence."""

    def __init__(
        self,
        daily_scheduler: DailySyncScheduler,
        morning_battery: MorningBodyBatteryService,
        *,
        sleep: Callable[[float], None],
        logger: logging.Logger,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._daily_scheduler = daily_scheduler
        self._morning_battery = morning_battery
        self._sleep = sleep
        self._logger = logger
        self._stop_event = stop_event

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def run(self) -> None:
        while True:
            if self._stop_event is not None:
                if self._stop_event.wait(300):
                    return
            else:
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
            except Exception as exc:  # noqa: BLE001 - keep the daily loop alive
                self._logger.error(
                    "Automatic synchronization scheduling failed",
                    extra={
                        "event": "daily_sync_failed",
                        "error_class": type(exc).__name__,
                        "reason": getattr(exc, "reason", None),
                    },
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


def _never_blocked() -> bool:
    # Startup never asks a policy whether it is blocked; see schedule_policies.
    return False


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
        schedule_policies: Mapping[str, ProviderSchedulePolicy] | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self._queue = queue
        self._sync_state = sync_state
        self._config = config
        self._registry = DEFAULT_PROVIDER_REGISTRY if registry is None else registry
        self._policies: Mapping[str, ProviderSchedulePolicy] = (
            build_schedule_policies(
                profile=profile,
                garmin=garmin,
                sync_state=sync_state,
                calendar_enabled=config.calendar_enabled,
                intervals_enabled=config.intervals_enabled,
                garmin_automatic_sync_days=config.garmin_automatic_sync_days,
                sync_period_defaults=config.sync_period_defaults,
                all_sync_days=config.all_sync_days,
                intervals_blocked=_never_blocked,
            )
            if schedule_policies is None
            else schedule_policies
        )

    def schedule(self) -> None:
        """Queue startup work in the registry's startup rank order."""
        for provider_id in self._registry.startup_order():
            policy = self._policies.get(provider_id)
            if policy is not None:
                self._schedule_provider(provider_id, policy)

    def _schedule_provider(
        self, provider_id: str, policy: ProviderSchedulePolicy
    ) -> None:
        if not policy.configured():
            return
        if not self._queue.active(provider_id, "refresh"):
            self._queue.enqueue(
                provider_id,
                "refresh",
                policy.refresh_payload("startup", "startup"),
                requested_by="startup",
            )
        if self._registry.supports_job(provider_id, _HISTORICAL_BACKFILL):
            self._enqueue_historical_backfill(provider_id)

    def _enqueue_historical_backfill(self, provider: str) -> None:
        if self._queue.active(provider, _HISTORICAL_BACKFILL):
            return
        payload = self._historical_backfill_payload(provider)
        if payload is not None:
            self._queue.enqueue(
                provider,
                _HISTORICAL_BACKFILL,
                payload,
                requested_by="startup",
            )

    def _historical_backfill_payload(self, provider: str) -> dict[str, Any] | None:
        cursor = self._sync_state.cursor(provider, "historical").get("cursor")
        if cursor and str(cursor) <= self._config.sync_earliest_date.isoformat():
            return None
        try:
            resume_end = (
                date.fromisoformat(iso_date_prefix(str(cursor))) - timedelta(days=1)
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
