"""Prepare local bootstrap state before optional provider weather refreshes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.activities.feedback import ActivityFeedbackService
from backend.calendar import canonical as calendar_canonical
from backend.db.manager import DatabaseManager
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.planning.planned_unit_service import PlannedUnitService
from backend.sync.adaptive import AdaptivePreviewFollowupService
from backend.sync.state import SyncStateRepository
from backend.weather.service import WeatherService


@dataclass(frozen=True)
class CalendarWindowRange:
    history_days: int
    future_days: int


@dataclass
class LocalStatePrelude:
    snapshot: dict[str, Any]
    activities: list[dict[str, Any]]
    local_planned: list[dict[str, Any]]
    canonical_planned: list[dict[str, Any]]
    calendar_window: dict[str, Any]
    weather: dict[str, Any] | None
    performance_inputs: CanonicalPerformanceInputs | None = None


class PublicStateLocalPrelude:
    """Own the single local bootstrap read and offline weather projection."""

    def __init__(
        self,
        sync_state: SyncStateRepository,
        activity_feedback: ActivityFeedbackService,
        planned_units: PlannedUnitService,
        weather: WeatherService,
        database_manager: DatabaseManager,
        database_lock: Any,
        today: Callable[[], date],
        window: CalendarWindowRange,
        performance_inputs: Callable[[Any, Any], CanonicalPerformanceInputs | None]
        | None = None,
    ) -> None:
        self._sync_state = sync_state
        self._activity_feedback = activity_feedback
        self._planned_units = planned_units
        self._weather = weather
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._today = today
        self._window = window
        self._performance_inputs = performance_inputs

    def read(self, local_only: bool) -> LocalStatePrelude:
        with self._database_lock, self._database_manager.unit_of_work() as db:
            snapshot = self._sync_state.latest_snapshot()
            performance_inputs = (
                self._performance_inputs(db, snapshot)
                if self._performance_inputs is not None
                else None
            )
            activities = self._activity_feedback.attach_to_activities(
                snapshot.get("recent_activities", [])
                if isinstance(snapshot, dict)
                else []
            )
            local_planned = self._planned_units.list()
            canonical_planned = calendar_canonical.canonical_planned_workouts(
                [], local_planned
            )
            provider_sync = (
                snapshot.get("provider_sync", {}) if isinstance(snapshot, dict) else {}
            )
            calendar_window = (
                provider_sync.get("calendar_window")
                if isinstance(provider_sync, dict)
                else None
            )
            if not isinstance(calendar_window, dict):
                today = self._today()
                calendar_window = {
                    "start": (
                        today - timedelta(days=self._window.history_days)
                    ).isoformat(),
                    "end": (
                        today + timedelta(days=self._window.future_days)
                    ).isoformat(),
                }
            weather = (
                self._weather.state(canonical_planned, refresh=False)
                if local_only
                else None
            )
        return LocalStatePrelude(
            snapshot,
            activities,
            local_planned,
            canonical_planned,
            calendar_window,
            weather,
            performance_inputs,
        )


class PublicStateWeatherPrelude:
    """Refresh weather outside the local database lock and trigger follow-up."""

    def __init__(
        self, weather: WeatherService, adaptive_followup: AdaptivePreviewFollowupService
    ) -> None:
        self._weather = weather
        self._adaptive_followup = adaptive_followup

    def project(
        self,
        canonical_planned: list[dict[str, Any]],
        local_weather: dict[str, Any] | None,
    ) -> dict[str, Any]:
        weather = (
            local_weather
            if local_weather is not None
            else self._weather.state(canonical_planned, refresh=True)
        )
        if weather.pop("_refreshed", False):
            self._adaptive_followup.check("weather")
        return weather
