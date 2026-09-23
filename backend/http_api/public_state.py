"""Compose the complete public application state response."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.http_api.bootstrap_calendar import PublicStateCalendarProjection
from backend.http_api.state_prelude import (
    PublicStateLocalPrelude,
    PublicStateWeatherPrelude,
)
from backend.performance import context as performance_context
from backend.planning import season as planning_season
from backend.sync import intervals_state

if TYPE_CHECKING:
    from backend.activities.feedback import ActivityFeedbackService
    from backend.athlete.checkins import CheckinService
    from backend.coach.context import CoachQuickActionsService
    from backend.coach.conversation import CoachMessageService
    from backend.coach.morning import MorningCheckinStateService
    from backend.config import Config
    from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
    from backend.planning.library_service import WorkoutLibraryService
    from backend.planning.training_plans import TrainingPlanService
    from backend.providers.state import ProviderStateService
    from backend.settings import SettingsService
    from backend.sync.full_resync import FullProviderResyncService
    from backend.sync.freshness import ProviderFreshnessService
    from backend.sync.garmin import GarminPayloadService, GarminSyncStateService
    from backend.sync.garmin_projection_service import GarminProjectionService
    from backend.sync.garmin_service import GarminSyncService
    from backend.sync.library import WorkoutLibrarySyncStateService
    from backend.sync.state import SyncStateRepository
    from backend.sync.status import SyncPublicStateService
    from backend.athlete.profile import ProfileService


@dataclass(frozen=True)
class PublicStateDependencies:
    """Concrete owners used to build the public state response."""

    local_prelude: PublicStateLocalPrelude
    weather_prelude: PublicStateWeatherPrelude
    calendar_projection: PublicStateCalendarProjection
    database_manager: Callable[[], DatabaseManager]
    database_lock: Any
    key_values: KeyValueRepository
    app_name: str
    app_version: str
    config: Config
    settings: SettingsService
    coach_messages: CoachMessageService
    training_plans: TrainingPlanService
    workout_library: WorkoutLibraryService
    profile: ProfileService
    checkins: CheckinService
    activity_feedback: ActivityFeedbackService
    sync_state: SyncStateRepository
    provider_freshness: ProviderFreshnessService
    garmin_sync_state: GarminSyncStateService
    sync_public_state: SyncPublicStateService
    garmin_payload: GarminPayloadService
    garmin_projection: GarminProjectionService
    intervals_sync_lock: Any
    workout_library_sync_running: Callable[[], bool]
    workout_library_sync_state: WorkoutLibrarySyncStateService
    garmin_sync: GarminSyncService
    provider_resync: FullProviderResyncService
    planning_preview: AdaptiveReplanPreviewService
    morning_checkin: MorningCheckinStateService
    coach_quick_actions: CoachQuickActionsService
    provider_state: ProviderStateService
    sync_period_defaults: dict[str, int]
    all_sync_days: int
    calendar_history_days: int
    calendar_future_days: int
    local_now: Callable[[], datetime]


class PublicStateService:
    """Own the full public state orchestration and response contract."""

    def __init__(self, dependencies: PublicStateDependencies) -> None:
        self._deps = dependencies

    @contextmanager
    def _unit_of_work(self) -> Iterator[tuple[DatabaseManager, Any]]:
        deps = self._deps
        with deps.database_lock:
            manager = deps.database_manager()
            with manager.unit_of_work() as db:
                yield manager, db

    def _get_value(self, key: str, manager: DatabaseManager) -> str | None:
        deps = self._deps
        with deps.database_lock, manager.unit_of_work() as db:
            return deps.key_values.get(db, key)

    def read(self, local_only: bool = False) -> dict[str, Any]:
        deps = self._deps
        prelude = deps.local_prelude.read(local_only)
        snapshot = prelude.snapshot
        activities = prelude.activities
        local_planned = prelude.local_planned
        canonical_planned = prelude.canonical_planned
        calendar_window = prelude.calendar_window
        weather = deps.weather_prelude.project(canonical_planned, prelude.weather)

        with self._unit_of_work() as (manager, db):
            calendar_data = deps.calendar_projection.read(
                snapshot,
                canonical_planned,
                local_planned,
                activities,
                weather,
                calendar_window,
            )
            checkins = calendar_data.checkins
            competitions = calendar_data.competitions
            external_calendar = calendar_data.external_calendar
            daily_context = calendar_data.daily_context
            calendar_projection = calendar_data.calendar_projection
            freshness = deps.provider_freshness.current(
                profile=deps.profile.get(),
                garmin_has_core_error=bool(deps.garmin_sync_state.core_error_entries()),
                garmin_tokenstore_exists=Path(deps.config.garmin_tokenstore).exists(),
            )
            sync = deps.sync_public_state.browser_state(freshness=freshness)
            return {
                "app": {"name": deps.app_name, "version": deps.app_version},
                "messages": deps.coach_messages.list(),
                "plans": deps.training_plans.list(),
                "library": deps.workout_library.list(include_archived=True),
                "activities": activities,
                **calendar_projection,
                "weather": weather,
                "profile": deps.profile.get(),
                "competitions": competitions,
                "checkins": checkins,
                "local_feedback": deps.checkins.context(),
                "activity_feedback": deps.activity_feedback.context(),
                "planning": planning_season.planning_state(
                    competitions,
                    deps.local_now().date(),
                    deps.planning_preview.latest_preview(),
                    deps.planning_preview.status(),
                ),
                "external_calendar": external_calendar,
                "daily_planning_context": daily_context,
                "performance": performance_context.current_performance_context(
                    snapshot,
                    deps.garmin_payload.snapshot(),
                    deps.profile.get(),
                    deps.local_now().date(),
                ),
                "garmin": deps.garmin_projection.public_state(),
                "intervals": intervals_state.public_state(
                    configured=bool(deps.config.intervals_api_key),
                    running=deps.intervals_sync_lock.locked()
                    or deps.workout_library_sync_running(),
                    status=self._get_value("sync_status", manager) or None,
                    last_sync_at=self._get_value("last_sync_at", manager),
                    last_sync_error=self._get_value("last_sync_error", manager) or None,
                    last_library_sync_at=self._get_value("last_library_sync_at", manager),
                    last_library_sync_error=self._get_value("last_library_sync_error", manager) or None,
                    pagination_value=self._get_value("last_sync_pagination", manager),
                    snapshot=snapshot,
                    library_sync_state=deps.workout_library_sync_state.summary(),
                    today=deps.local_now().date(),
                    history_days=deps.calendar_history_days,
                    future_days=deps.calendar_future_days,
                ),
                "provider_freshness": freshness,
                "garmin_sync": {
                    "running": deps.garmin_sync.running(),
                    "status": self._get_value("garmin_sync_status", manager) or None,
                },
                "provider_resync": {
                    "intervals": deps.provider_resync.state("intervals", db),
                    "garmin": deps.provider_resync.state("garmin", db),
                },
                "sync": sync,
                "library_sync": {
                    "last_sync_at": self._get_value("last_library_sync_at", manager),
                    "last_error": self._get_value("last_library_sync_error", manager) or None,
                    "state": deps.workout_library_sync_state.summary(),
                },
                "sync_settings": {
                    "intervals_days": deps.sync_state.sync_period(
                        "intervals", deps.sync_period_defaults, deps.all_sync_days
                    ),
                    "garmin_days": deps.sync_state.sync_period(
                        "garmin", deps.sync_period_defaults, deps.all_sync_days
                    ),
                },
                "calendar_display": deps.settings.calendar_display_settings(),
                "competition_sync": {
                    "last_sync_at": self._get_value("last_competition_sync_at", manager),
                    "last_error": self._get_value("last_competition_sync_error", manager) or None,
                    "running": self._get_value("competition_sync_running", manager) == "1",
                    "status": self._get_value("competition_sync_status", manager) or None,
                },
                "performance_refresh": {
                    "last_refresh_at": self._get_value("last_performance_refresh_at", manager),
                    "last_error": self._get_value("last_performance_error", manager) or None,
                    "running": self._get_value("performance_refresh_running", manager) == "1",
                },
                "morning_checkin": deps.morning_checkin.state(),
                "coach_quick_actions": deps.coach_quick_actions.state(),
                "ai_provider": {
                    "selected": deps.settings.selected_ai_provider(),
                    "options": deps.settings.available_ai_providers(),
                },
                "model": {
                    "selected": deps.settings.selected_model(),
                    "options": deps.settings.available_model_options(),
                },
                "thinking_level": {
                    "selected": deps.settings.selected_thinking_level(),
                    "options": deps.settings.available_thinking_level_options(),
                },
                "configured": {
                    "openai": bool(deps.config.openai_api_key),
                    "gemini": bool(deps.config.gemini_api_key),
                    "intervals": bool(deps.config.intervals_api_key),
                    "weather": bool(weather.get("configured")),
                    "external_calendar": bool(deps.config.calendar_ical_url),
                },
                "usage": deps.provider_state.summary(
                    deps.settings.selected_ai_provider() or "openai"
                ),
            }
