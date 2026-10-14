"""Concrete schedule policies for daily and startup provider refreshes.

Each policy answers the scheduler's questions for one provider: whether it is
configured, whether a daily refresh must wait, and the refresh payload. The
checks and payloads are the ones the scheduler used before ranks moved into the
provider descriptors, so the enqueued jobs stay identical.

Configuration flags are snapshots taken when a scheduler is built, as before.
Live services (profile, Garmin, sync state) are read at each decision. The
scheduler keeps the queue-activity checks and the daily due markers. ``blocked``
is consulted only by the daily run: startup never waited on a running sync or a
resync reset, and the protocol carries no trigger to say otherwise.

Provider identifiers come from the descriptor constants. Nothing here compares
provider names, so the coupling ratchet records no entries for this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from backend.athlete.profile import ProfileService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.descriptors import (
    CALENDAR_ID,
    GARMIN_ID,
    INTERVALS_ID,
    WAHOO_ID,
    WEATHER_ID,
)
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_runtime import ProviderSchedulePolicy
from backend.sync.state import SyncStateRepository

ScheduleTrigger = Literal["daily", "startup"]


class WeatherSchedulePolicy:
    """Scheduled when a weather location is saved; startup forces the refresh."""

    def __init__(self, profile: ProfileService) -> None:
        self._profile = profile

    def configured(self) -> bool:
        return bool(self._profile.get().get("weather_location", "").strip())

    def blocked(self) -> bool:
        return False

    def refresh_payload(self, trigger: ScheduleTrigger, reason: str) -> dict[str, Any]:
        return {"force": trigger == "startup", "reason": reason}


class CalendarSchedulePolicy:
    """Scheduled when the public calendar URL was configured at build time."""

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled

    def configured(self) -> bool:
        return self._enabled

    def blocked(self) -> bool:
        return False

    def refresh_payload(self, _trigger: ScheduleTrigger, reason: str) -> dict[str, Any]:
        return {"reason": reason}


class GarminSchedulePolicy:
    """Scheduled when Garmin is configured, with its automatic sync window."""

    def __init__(self, garmin: GarminSyncService, automatic_sync_days: int) -> None:
        self._garmin = garmin
        self._automatic_sync_days = automatic_sync_days

    def configured(self) -> bool:
        return self._garmin.configured()

    def blocked(self) -> bool:
        return False

    def refresh_payload(self, _trigger: ScheduleTrigger, reason: str) -> dict[str, Any]:
        days, end_date = self._garmin.automatic_sync_window(self._automatic_sync_days)
        payload: dict[str, Any] = {"days": days, "reason": reason}
        if end_date is not None:
            payload["end_date"] = end_date.isoformat()
        return payload


class IntervalsSchedulePolicy:
    """Scheduled when the Intervals.icu key was configured at build time.

    ``blocked_by`` reports a running sync or an Intervals.icu resync reset.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        sync_state: SyncStateRepository,
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
        blocked_by: Callable[[], bool],
    ) -> None:
        self._enabled = enabled
        self._sync_state = sync_state
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._blocked_by = blocked_by

    def configured(self) -> bool:
        return self._enabled

    def blocked(self) -> bool:
        return self._blocked_by()

    def refresh_payload(self, _trigger: ScheduleTrigger, reason: str) -> dict[str, Any]:
        days = self._sync_state.sync_period(
            INTERVALS_ID, self._sync_period_defaults, self._all_sync_days
        )
        return {"days": days, "reason": reason}


class WahooSchedulePolicy:
    """Scheduled once Wahoo is configured and the athlete connected it.

    The window is the stored Wahoo sync period, clamped by the owner to the
    descriptor limits. ``blocked`` reports a Wahoo resync reset.
    """

    def __init__(
        self,
        *,
        configured: Callable[[], bool],
        sync_state: SyncStateRepository,
        sync_period_defaults: Mapping[str, int],
        all_sync_days: int,
        resync_gate: ProviderResyncGate,
    ) -> None:
        self._configured = configured
        self._sync_state = sync_state
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._resync_gate = resync_gate

    def configured(self) -> bool:
        return self._configured()

    def blocked(self) -> bool:
        return self._resync_gate.is_resetting()

    def refresh_payload(self, _trigger: ScheduleTrigger, reason: str) -> dict[str, Any]:
        days = self._sync_state.sync_period(
            WAHOO_ID, self._sync_period_defaults, self._all_sync_days
        )
        return {"days": days, "reason": reason}


def intervals_busy(
    database: DatabaseManager,
    key_values: KeyValueRepository,
    database_lock: Any,
    resync_gate: ProviderResyncGate,
) -> bool:
    """Return whether a running sync or an Intervals.icu resync blocks a refresh."""
    with database_lock, database.unit_of_work() as db:
        running = key_values.get(db, "sync_running") == "1"
    return running or resync_gate.is_resetting()


def build_schedule_policies(
    *,
    profile: ProfileService,
    garmin: GarminSyncService,
    sync_state: SyncStateRepository,
    calendar_enabled: bool,
    intervals_enabled: bool,
    garmin_automatic_sync_days: int,
    sync_period_defaults: Mapping[str, int],
    all_sync_days: int,
    intervals_blocked: Callable[[], bool],
) -> dict[str, ProviderSchedulePolicy]:
    """Return the four built-in policies keyed by descriptor provider id."""
    return {
        WEATHER_ID: WeatherSchedulePolicy(profile),
        CALENDAR_ID: CalendarSchedulePolicy(enabled=calendar_enabled),
        GARMIN_ID: GarminSchedulePolicy(garmin, garmin_automatic_sync_days),
        INTERVALS_ID: IntervalsSchedulePolicy(
            enabled=intervals_enabled,
            sync_state=sync_state,
            sync_period_defaults=sync_period_defaults,
            all_sync_days=all_sync_days,
            blocked_by=intervals_blocked,
        ),
    }
