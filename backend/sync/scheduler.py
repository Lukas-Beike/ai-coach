"""Schedule due daily provider refreshes in their established order."""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.athlete.profile import ProfileService
from backend.errors import AppError
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.backfill_resume import historical_backfill_payload
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.jobs import BACKFILL_CURSOR_STREAMS
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.queue import SyncJobQueueService
from backend.sync.schedule_policies import (
    ProviderSchedulePolicy,
    build_schedule_policies,
)
from backend.sync.state import SyncStateRepository

LOGGER = logging.getLogger("intervals_coach")
AUTO_UPDATE_LABEL = "stündliche automatische Aktualisierung"
_HISTORICAL_BACKFILL = "historical_backfill"


@dataclass(frozen=True)
class DailySyncSchedulerConfig:
    calendar_url_enabled: bool
    garmin_automatic_sync_days: int
    auto_update_label: str


class DailySyncScheduler:
    """Own the order and eligibility decisions for daily refresh jobs."""

    def __init__(
        self,
        profile: ProfileService,
        queue: SyncJobQueueService,
        markers: DailySyncMarkerService,
        garmin: GarminSyncService,
        maintenance_gate: MaintenanceGate,
        *,
        config: DailySyncSchedulerConfig,
        schedule_policies: Mapping[str, ProviderSchedulePolicy] | None = None,
        registry: ProviderRegistry | None = None,
        retry_held: Callable[[str], bool] | None = None,
        backfill_resumer: Callable[[], None] | None = None,
    ) -> None:
        self._queue = queue
        self._markers = markers
        # Re-queues backfill chains that stopped before the history floor.
        self._backfill_resumer = backfill_resumer
        # True while a provider's failed refresh says its retry is not due yet.
        self._retry_held = retry_held
        self._maintenance_gate = maintenance_gate
        self._config = config
        self._registry = DEFAULT_PROVIDER_REGISTRY if registry is None else registry
        self._daily_marker_ids = self._registry.daily_marker_ids()
        self._policies: Mapping[str, ProviderSchedulePolicy] = (
            build_schedule_policies(
                profile=profile,
                garmin=garmin,
                calendar_enabled=config.calendar_url_enabled,
                garmin_automatic_sync_days=config.garmin_automatic_sync_days,
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
                    self._schedule_provider_safely(provider_id, policy)
            if self._backfill_resumer is not None:
                self._backfill_resumer()

    def _schedule_provider_safely(
        self, provider_id: str, policy: ProviderSchedulePolicy
    ) -> None:
        """Schedule one provider; its failure never skips the providers after it."""
        try:
            self._schedule_provider(provider_id, policy)
        except AppError as exc:
            if exc.reason == "maintenance":
                raise
            self._log_provider_failure(provider_id, exc)
        except Exception as exc:  # noqa: BLE001 - one provider must not stop the pass
            self._log_provider_failure(provider_id, exc)

    @staticmethod
    def _log_provider_failure(provider_id: str, exc: Exception) -> None:
        LOGGER.error(
            "Scheduling a provider refresh failed",
            extra={
                "event": "daily_sync_provider_failed",
                "context": {
                    "provider": provider_id,
                    "error_class": type(exc).__name__,
                },
            },
        )

    def _schedule_provider(
        self, provider_id: str, policy: ProviderSchedulePolicy
    ) -> None:
        if not policy.configured():
            return
        if policy.blocked() or self._queue.active(provider_id):
            return
        if self._retry_held is not None and self._retry_held(provider_id):
            return
        # Last, so a provider check that reads remotely runs only when the
        # refresh could be queued.
        if not self._refresh_due(provider_id, policy):
            return
        self._queue.enqueue(
            provider_id,
            "refresh",
            policy.refresh_payload("daily", self._config.auto_update_label),
            requested_by="scheduler",
        )

    def _refresh_due(self, provider_id: str, policy: ProviderSchedulePolicy) -> bool:
        """The hourly marker, unless the policy decides itself (``refresh_due``)."""
        if provider_id not in self._daily_marker_ids:
            return True
        marker_due = functools.partial(self._markers.is_due, provider_id)
        decide = getattr(policy, "refresh_due", None)
        return bool(decide(marker_due)) if callable(decide) else marker_due()


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
        housekeeping: Callable[[], object] | None = None,
        wal_checkpoint: Callable[[], object] | None = None,
        morning_due: Callable[[], bool] | None = None,
    ) -> None:
        # False while the Garmin change check waits for the night (#2303).
        self._morning_due = morning_due
        self._housekeeping = housekeeping
        self._wal_checkpoint = wal_checkpoint
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
            self._run_housekeeping()
            self._run_wal_checkpoint()
            try:
                self._daily_scheduler.schedule()
                self._refresh_morning()
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
                        "context": {
                            "error_class": type(exc).__name__,
                            "reason": getattr(exc, "reason", None),
                        },
                    },
                )

    def _refresh_morning(self) -> None:
        """Refresh the morning reading unless the change check holds it back."""
        if self._morning_due is None or self._morning_due():
            self._morning_battery.refresh()

    def _run_housekeeping(self) -> None:
        """Run the periodic upkeep; its failure never skips the scheduling."""
        if self._housekeeping is None:
            return
        try:
            self._housekeeping()
        except Exception as exc:  # noqa: BLE001 - keep the daily loop alive
            self._logger.error(
                "Sync housekeeping failed",
                extra={
                    "event": "sync_housekeeping_failed",
                    "context": {
                        "error_class": type(exc).__name__,
                        "reason": getattr(exc, "reason", None),
                    },
                },
            )

    def _run_wal_checkpoint(self) -> None:
        """Truncate the idle WAL; a failure never stops the loop."""
        if self._wal_checkpoint is None:
            return
        try:
            self._wal_checkpoint()
        except AppError as exc:
            if exc.reason != "maintenance":
                self._log_checkpoint_failure(exc)
        except Exception as exc:  # noqa: BLE001 - keep the daily loop alive
            self._log_checkpoint_failure(exc)

    def _log_checkpoint_failure(self, exc: Exception) -> None:
        self._logger.error(
            "Database WAL checkpoint failed",
            extra={
                "event": "wal_checkpoint_failed",
                "context": {"error_class": type(exc).__name__},
            },
        )


@dataclass(frozen=True)
class StartupSyncSchedulerConfig:
    calendar_enabled: bool
    garmin_automatic_sync_days: int
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
                calendar_enabled=config.calendar_enabled,
                garmin_automatic_sync_days=config.garmin_automatic_sync_days,
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
        # Each backfill chain walks its own cursor to the floor once; a restart
        # resumes below the cursor (the wellness walk is the one-off #1730).
        for job_type in BACKFILL_CURSOR_STREAMS:
            if self._registry.supports_job(provider_id, job_type):
                self._enqueue_historical_backfill(provider_id, job_type)

    def _enqueue_historical_backfill(
        self, provider: str, job_type: str = _HISTORICAL_BACKFILL
    ) -> None:
        if self._queue.active(provider, job_type):
            return
        payload = self._historical_backfill_payload(provider, job_type)
        if payload is not None:
            self._queue.enqueue(
                provider,
                job_type,
                payload,
                requested_by="startup",
            )

    def _historical_backfill_payload(
        self, provider: str, job_type: str = _HISTORICAL_BACKFILL
    ) -> dict[str, Any] | None:
        return historical_backfill_payload(
            self._sync_state,
            provider,
            job_type,
            chunk_days=self._config.sync_chunk_days,
            earliest_date=self._config.sync_earliest_date,
            reason=f"startup {job_type.replace('_', ' ')}",
        )
