"""Schedule due daily provider refreshes in their established order."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.athlete.profile import ProfileService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository


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
        calendar_url_enabled: bool,
        intervals_key_enabled: bool,
        garmin_automatic_sync_days: int,
        auto_update_label: str,
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
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
        self._calendar_url_enabled = calendar_url_enabled
        self._intervals_key_enabled = intervals_key_enabled
        self._garmin_automatic_sync_days = garmin_automatic_sync_days
        self._auto_update_label = auto_update_label
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days

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
            {"force": False, "reason": self._auto_update_label},
            requested_by="scheduler",
        )

    def _schedule_calendar(self) -> None:
        if (
            not self._calendar_url_enabled
            or not self._markers.is_due("calendar")
            or self._queue.active("calendar")
        ):
            return
        self._queue.enqueue(
            "calendar",
            "refresh",
            {"reason": self._auto_update_label},
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
                "days": self._garmin_automatic_sync_days,
                "reason": self._auto_update_label,
            },
            requested_by="scheduler",
        )

    def _schedule_intervals(self) -> None:
        if (
            not self._intervals_key_enabled
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
                    "intervals", self._sync_period_defaults, self._all_sync_days
                ),
                "reason": self._auto_update_label,
            },
            requested_by="scheduler",
        )

    def _sync_running(self) -> bool:
        with self._database_lock, self._database.unit_of_work() as db:
            return self._key_values.get(db, "sync_running") == "1"
