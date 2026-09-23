"""Public training-plan state projection for the HTTP API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.calendar import canonical as calendar_canonical
from backend.db.manager import DatabaseManager
from backend.planning import calendar_read_model
from backend.planning import season as planning_season
from backend.weather import cache as weather_cache
from backend.weather import history as weather_history


@dataclass(frozen=True)
class PublicPlanDependencies:
    sync_state: Any
    planned_units: Any
    activity_feedback: Any
    weather: Any
    adaptive_followup: Any
    database_manager_factory: Callable[[], DatabaseManager]
    db_lock: Any
    key_values: Any
    training_plans: Any
    external_calendar: Any
    external_calendar_sync: Any
    daily_context: Any
    checkins: Any
    competitions: Any
    adaptive_preview: Any
    coach_quick_actions: Any
    today: Callable[[], date]
    external_calendar_configured: bool
    external_calendar_window_days: int
    default_workout_name: str


class PublicPlanStateService:
    """Compose bounded local planning reads into the public plan response."""

    def __init__(self, dependencies: PublicPlanDependencies) -> None:
        self._sync_state = dependencies.sync_state
        self._planned_units = dependencies.planned_units
        self._activity_feedback = dependencies.activity_feedback
        self._weather = dependencies.weather
        self._adaptive_followup = dependencies.adaptive_followup
        self._database_manager_factory = dependencies.database_manager_factory
        self._db_lock = dependencies.db_lock
        self._key_values = dependencies.key_values
        self._training_plans = dependencies.training_plans
        self._external_calendar = dependencies.external_calendar
        self._external_calendar_sync = dependencies.external_calendar_sync
        self._daily_context = dependencies.daily_context
        self._checkins = dependencies.checkins
        self._competitions = dependencies.competitions
        self._adaptive_preview = dependencies.adaptive_preview
        self._coach_quick_actions = dependencies.coach_quick_actions
        self._today = dependencies.today
        self._external_calendar_configured = dependencies.external_calendar_configured
        self._external_calendar_window_days = dependencies.external_calendar_window_days
        self._default_workout_name = dependencies.default_workout_name

    def read(self, local_only: bool = False) -> dict[str, Any]:
        snapshot = self._sync_state.latest_snapshot() or {}
        local_planned = self._planned_units.list(500)
        canonical_planned = calendar_canonical.canonical_planned_workouts(
            [], local_planned
        )
        activities = (
            snapshot.get("recent_activities", []) if isinstance(snapshot, dict) else []
        )
        activities = activities[:1000] if isinstance(activities, list) else []
        activities = self._activity_feedback.attach_to_activities(activities)
        weather = self._weather.state(canonical_planned, refresh=not local_only)
        if weather.pop("_refreshed", False):
            self._adaptive_followup.check("weather")
        with self._db_lock, self._database_manager_factory().unit_of_work() as db:
            history = self._key_values.get(db, weather_cache.HISTORY_KEY)
        weather = weather_history.calendar_state(history, weather, today=self._today())
        provider_sync = (
            snapshot.get("provider_sync", {}) if isinstance(snapshot, dict) else {}
        )
        calendar_window = (
            provider_sync.get("calendar_window", {})
            if isinstance(provider_sync, dict)
            else {}
        )
        competitions = self._competitions.list()
        external_events = self._external_calendar.list_events(
            1000, training_relevant_only=True
        )
        calendar_projection = calendar_read_model.project_planning_calendar(
            local_planned,
            activities,
            weather,
            competitions,
            external_events,
            today=self._today(),
            provider_window=calendar_window,
            default_name=self._default_workout_name,
        )
        return {
            "plans": self._training_plans.list(limit=30),
            **calendar_projection,
            "weather": weather,
            "external_calendar": self._external_calendar.state(
                configured=self._external_calendar_configured,
                running=self._external_calendar_sync.running(),
                window_days=self._external_calendar_window_days,
            ),
            "daily_planning_context": self._daily_context.build(
                snapshot,
                canonical_planned,
                weather,
                self._checkins.list(365),
                self._external_calendar.list_events(50, training_relevant_only=True),
            ),
            "planning": planning_season.planning_state(
                competitions,
                self._today(),
                self._adaptive_preview.latest_preview(),
                self._adaptive_preview.status(),
            ),
            "coach_quick_actions": self._coach_quick_actions.state(),
        }
