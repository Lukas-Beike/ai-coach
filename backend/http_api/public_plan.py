"""Public training-plan state projection for the HTTP API."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.calendar import canonical as calendar_canonical
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.public_metrics import (
    neutral_calendar_entries,
    neutral_calendar_state,
)
from backend.canonical.records import Observation
from backend.db.manager import DatabaseManager
from backend.performance.session_analysis_reads import calendar_profiles
from backend.planning import calendar_read_model
from backend.planning import season as planning_season
from backend.planning.compact_activities import ActivitySummarySource
from backend.weather import cache as weather_cache
from backend.weather import history as weather_history


@dataclass(frozen=True)
class PublicPlanDependencies:
    planned_units: Any
    activity_feedback: Any
    weather: Any
    adaptive_followup: Any
    database_manager_factory: Callable[[], DatabaseManager]
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
    # Recent activity summaries come from the canonical activity summary port.
    activity_rows: ActivitySummarySource | None = None
    # Canonical zone configurations and sport thresholds set the plan zones.
    zone_configurations: Callable[[], Sequence[ZoneConfiguration]] = tuple
    # (db) -> the plan-zone thresholds, read inside the plan's read snapshot.
    sport_thresholds: Callable[[Any], Sequence[Observation]] = lambda _db: ()


class PublicPlanStateService:
    """Compose bounded local planning reads into the public plan response."""

    def __init__(self, dependencies: PublicPlanDependencies) -> None:
        self._planned_units = dependencies.planned_units
        self._activity_feedback = dependencies.activity_feedback
        self._weather = dependencies.weather
        self._adaptive_followup = dependencies.adaptive_followup
        self._database_manager_factory = dependencies.database_manager_factory
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
        self._activity_rows = dependencies.activity_rows
        self._zone_configurations = dependencies.zone_configurations
        self._sport_thresholds = dependencies.sport_thresholds

    def read_public(self, local_only: bool = False) -> dict[str, Any]:
        """Return the plan state with neutral metric names for the browser.

        ``read`` keeps the stored metric keys because the training report
        consumes them internally.
        """
        return neutral_calendar_state(self.read(local_only=local_only))

    def read(self, local_only: bool = False) -> dict[str, Any]:
        manager = self._database_manager_factory()
        weather = None
        if not local_only:
            # The weather refresh may call the provider and write its cache, so
            # it is its own step; the read below never waits for the writer.
            with manager.read_snapshot():
                canonical_planned = calendar_canonical.canonical_planned_workouts(
                    self._planned_units.list(500)
                )
            weather = self._weather.state(canonical_planned, refresh=True)
            if weather.pop("_refreshed", False):
                self._adaptive_followup.check("weather")
        # Every read below shares one read-only snapshot.
        with manager.read_snapshot() as db:
            return self._read(weather, db)

    def read_training_day(self, day: date) -> list[dict[str, Any]]:
        """Return the public training-calendar entries around one local day.

        Reads only the planned units and activities of the day and its two
        neighbours (a unit can be completed on the next day) in one snapshot,
        not the full calendar read model; callers pick the entries they need.
        """
        start, end = day - timedelta(days=1), day + timedelta(days=1)
        manager = self._database_manager_factory()
        with manager.read_snapshot() as db:
            planned = self._planned_units.list_between(start, end)
            activities = (
                self._activity_rows.between(db, start, end)
                if self._activity_rows
                else []
            )
            thresholds = self._sport_thresholds(db)
        profiles = calendar_profiles(manager)
        calendar = calendar_read_model.project_training_day(
            planned,
            [self._with_profile(row, profiles) for row in activities],
            today=self._today(),
            sport_thresholds=thresholds,
            zone_configurations=self._zone_configurations(),
        )
        return neutral_calendar_entries(calendar)

    def _history_and_profiles(self) -> tuple[Any, dict[str, Any]]:
        """Read the weather history and the stored workout profiles by session."""
        manager = self._database_manager_factory()
        with manager.reader() as db:
            history = self._key_values.get(db, weather_cache.HISTORY_KEY)
        return history, calendar_profiles(manager)

    @staticmethod
    def _with_profile(row: Any, profiles: dict[str, Any]) -> Any:
        """Attach the session's stored canonical workout profile, if any."""
        if not isinstance(row, dict):
            return row
        profile = profiles.get(str(row.get("id") or ""))
        if profile is None:
            return row
        return {**row, "workout_profile": profile}

    def _read(self, weather: dict[str, Any] | None, db: Any) -> dict[str, Any]:
        local_planned = self._planned_units.list(500, push_state=True)
        canonical_planned = calendar_canonical.canonical_planned_workouts(local_planned)
        activities = self._activity_rows.compact() if self._activity_rows else []
        activities = self._activity_feedback.attach_to_activities(activities[:1000])
        if weather is None:
            weather = self._weather.state(canonical_planned, refresh=False)
        history, profiles = self._history_and_profiles()
        activities = [self._with_profile(row, profiles) for row in activities]
        weather = weather_history.calendar_state(history, weather, today=self._today())
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
            default_name=self._default_workout_name,
            sport_thresholds=self._sport_thresholds(db),
            zone_configurations=self._zone_configurations(),
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
                canonical_planned,
                weather,
                self._checkins.list(365),
                self._external_calendar.list_events_in_window(
                    self._external_calendar_window_days, training_relevant_only=True
                ),
            ),
            "planning": planning_season.planning_state(
                competitions,
                self._today(),
                self._adaptive_preview.latest_preview(),
                self._adaptive_preview.status(),
            ),
            "coach_quick_actions": self._coach_quick_actions.state(),
        }
