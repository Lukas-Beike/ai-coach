from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.bootstrap_calendar import PublicStateCalendarProjection
from backend.http_api.bootstrap_state import (
    PublicBootstrapDependencies,
    PublicBootstrapService,
)
from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.http_api.public_state import PublicStateDependencies, PublicStateService
from backend.http_api.public_weather import PublicWeatherStateService
from backend.http_api.state_prelude import (
    CalendarWindowRange,
    PublicStateLocalPrelude,
    PublicStateWeatherPrelude,
)
from backend.sync.status import SyncPublicStateService


class PublicStateAssembly:
    """Compose public read projections from the existing domain assemblies."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        database_lock: Callable[[], Any],
        config: Callable[[], Any],
        settings: Callable[[], Any],
        maintenance_gate: Callable[[], Any],
        app_name: str,
        app_version: str,
        key_values: Callable[[], Any],
        sync_persistence: Callable[[], Any],
        planning_data: Callable[[], Any],
        athlete_data: Callable[[], Any],
        external_calendar: Callable[[], Any],
        provider_sync: Callable[[], Any],
        garmin: Callable[[], Any],
        sync_job_queue: Callable[[], Any],
        weather: Callable[[], Any],
        workout_library_sync: Callable[[], Any],
        provider_resync: Callable[[], Any],
        coach_conversation: Callable[[], Any],
        calendar_local: Callable[[], Any],
        planning_season: Callable[[], Any],
        intervals_state: Callable[[], Any],
        diagnostic_capture: Callable[[], Any],
        intervals_sync_lock: Callable[[], Any],
        workout_library_sync_running: Callable[[], Callable[[], bool]],
        state_version_service: Callable[[], Any],
        daily_planning_context_service: Callable[[], Any],
        adaptive_preview_followup_service: Callable[[], Any],
        adaptive_replan_preview_service: Callable[[], Any],
        morning_checkin_state_service: Callable[[], Any],
        coach_quick_actions_service: Callable[[], Any],
        provider_state_service: Callable[[], Any],
        local_date: Callable[[], Any],
        local_now: Callable[[], Any],
        external_calendar_window_days: Callable[[], int],
        calendar_history_days: Callable[[], int],
        calendar_future_days: Callable[[], int],
        sync_period_defaults: Callable[[], Any],
        all_sync_days: Callable[[], int],
        planned_workout_label: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._config = config
        self._settings = settings
        self._maintenance_gate = maintenance_gate
        self._app_name = app_name
        self._app_version = app_version
        self._key_values = key_values
        self._sync_persistence = sync_persistence
        self._planning_data = planning_data
        self._athlete_data = athlete_data
        self._external_calendar = external_calendar
        self._provider_sync = provider_sync
        self._garmin = garmin
        self._sync_job_queue = sync_job_queue
        self._weather = weather
        self._workout_library_sync = workout_library_sync
        self._provider_resync = provider_resync
        self._coach_conversation = coach_conversation
        self._calendar_local = calendar_local
        self._planning_season = planning_season
        self._intervals_state = intervals_state
        self._diagnostic_capture = diagnostic_capture
        self._intervals_sync_lock = intervals_sync_lock
        self._workout_library_sync_running = workout_library_sync_running
        self._state_version_service = state_version_service
        self._daily_planning_context_service = daily_planning_context_service
        self._adaptive_preview_followup_service = adaptive_preview_followup_service
        self._adaptive_replan_preview_service = adaptive_replan_preview_service
        self._morning_checkin_state_service = morning_checkin_state_service
        self._coach_quick_actions_service = coach_quick_actions_service
        self._provider_state_service = provider_state_service
        self._local_date = local_date
        self._local_now = local_now
        self._external_calendar_window_days = external_calendar_window_days
        self._calendar_history_days = calendar_history_days
        self._calendar_future_days = calendar_future_days
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._planned_workout_label = planned_workout_label

    def performance_state_service(self) -> PublicPerformanceStateService:
        sync = self._sync_persistence()
        garmin = self._garmin()
        athlete = self._athlete_data()
        return PublicPerformanceStateService(
            sync.state_repository(),
            garmin.payload_service(),
            athlete.profile(),
            garmin.projection_service(),
            self._local_date,
        )

    def feedback_state_service(self) -> PublicFeedbackStateService:
        athlete = self._athlete_data()
        return PublicFeedbackStateService(athlete.checkin(), athlete.activity_feedback())

    def sync_public_state_service(self) -> SyncPublicStateService:
        config = self._config()
        athlete = self._athlete_data()
        garmin = self._garmin()
        return SyncPublicStateService(
            config,
            self._database_manager(),
            self._key_values(),
            self._provider_sync().freshness_service(),
            athlete.profile(),
            garmin.sync_state_service(),
            self._maintenance_gate(),
            self._sync_job_queue().service(),
            self._state_version_service(),
            self._intervals_sync_lock(),
        )

    def weather_state_service(self) -> PublicWeatherStateService:
        return PublicWeatherStateService(self._weather().service())

    def bootstrap_service(self) -> PublicBootstrapService:
        config = self._config()
        sync = self._sync_persistence()
        planning = self._planning_data()
        athlete = self._athlete_data()
        calendar = self._external_calendar()
        provider = self._provider_sync()
        garmin = self._garmin()
        conversation = self._coach_conversation()
        return PublicBootstrapService(PublicBootstrapDependencies(
            database_manager=self._database_manager,
            database_lock=self._database_lock(),
            config=config,
            app_name=self._app_name,
            app_version=self._app_version,
            key_values=self._key_values(),
            sync_state_repository=sync.state_repository,
            planned_unit_service=planning.planned_unit,
            competition_service=planning.competition,
            external_calendar_reader=calendar.reader,
            profile_service=athlete.profile,
            provider_freshness_service=provider.freshness_service,
            garmin_sync_state_service=garmin.sync_state_service,
            garmin_sync_service=garmin.sync_service,
            sync_job_queue_service=self._sync_job_queue().service,
            state_version_service=self._state_version_service,
            coach_message_service=conversation.message_service,
            training_plan_service=planning.training_plan,
            local_calendar_events=self._calendar_local().local_calendar_events,
            planning_state=self._planning_season().planning_state,
            adaptive_replan_preview_service=self._adaptive_replan_preview_service,
            external_calendar_sync_service=calendar.sync_service,
            external_calendar_window_days=self._external_calendar_window_days(),
            planned_calendar_history_days=self._calendar_history_days(),
            planned_calendar_future_days=self._calendar_future_days(),
            garmin_projection_service=garmin.projection_service,
            diagnostic_capture=self._diagnostic_capture(),
            intervals_public_state=self._intervals_state().public_state,
            intervals_sync_lock=self._intervals_sync_lock(),
            workout_library_sync_running=self._workout_library_sync_running(),
            workout_library_sync_state_service=self._workout_library_sync().sync_state_service,
            full_provider_resync_service=self._provider_resync().full_resync_service,
            sync_public_state_service=self.sync_public_state_service,
            sync_period_defaults=self._sync_period_defaults(),
            all_sync_days=self._all_sync_days(),
            settings=self._settings(),
            local_date=self._local_date,
            morning_checkin_state_service=self._morning_checkin_state_service,
            coach_quick_actions_service=self._coach_quick_actions_service,
            provider_state_service=self._provider_state_service,
        ))

    def plan_state_service(self) -> PublicPlanStateService:
        sync = self._sync_persistence()
        planning = self._planning_data()
        athlete = self._athlete_data()
        calendar = self._external_calendar()
        config = self._config()
        return PublicPlanStateService(PublicPlanDependencies(
            sync_state=sync.state_repository(),
            planned_units=planning.planned_unit(),
            activity_feedback=athlete.activity_feedback(),
            weather=self._weather().service(),
            adaptive_followup=self._adaptive_preview_followup_service(),
            database_manager_factory=self._database_manager,
            db_lock=self._database_lock(),
            key_values=self._key_values(),
            training_plans=planning.training_plan(),
            external_calendar=calendar.reader(),
            external_calendar_sync=calendar.sync_service(),
            daily_context=self._daily_planning_context_service(),
            checkins=athlete.checkin(),
            competitions=planning.competition(),
            adaptive_preview=self._adaptive_replan_preview_service(),
            coach_quick_actions=self._coach_quick_actions_service(),
            today=self._local_date,
            external_calendar_configured=bool(config.calendar_ical_url),
            external_calendar_window_days=self._external_calendar_window_days(),
            default_workout_name=self._planned_workout_label(),
        ))

    def local_prelude_service(self) -> PublicStateLocalPrelude:
        return PublicStateLocalPrelude(
            self._sync_persistence().state_repository(),
            self._athlete_data().activity_feedback(),
            self._planning_data().planned_unit(),
            self._weather().service(),
            self._database_manager(),
            self._database_lock(),
            self._local_date,
            CalendarWindowRange(self._calendar_history_days(), self._calendar_future_days()),
        )

    def weather_prelude_service(self) -> PublicStateWeatherPrelude:
        return PublicStateWeatherPrelude(
            self._weather().service(), self._adaptive_preview_followup_service()
        )

    def calendar_projection_service(self) -> PublicStateCalendarProjection:
        config = self._config()
        planning = self._planning_data()
        athlete = self._athlete_data()
        calendar = self._external_calendar()
        return PublicStateCalendarProjection(
            athlete.checkin(),
            planning.competition(),
            calendar.reader(),
            calendar.sync_service(),
            self._daily_planning_context_service(),
            external_calendar_configured=bool(config.calendar_ical_url),
            external_calendar_window_days=self._external_calendar_window_days(),
            default_workout_name=self._planned_workout_label(),
            today=self._local_date,
        )

    def state_service(self) -> PublicStateService:
        database_lock = self._database_lock()
        with database_lock:
            config = self._config()
            planning = self._planning_data()
            athlete = self._athlete_data()
            sync = self._sync_persistence()
            garmin = self._garmin()
            provider = self._provider_sync()
            return PublicStateService(PublicStateDependencies(
                local_prelude=self.local_prelude_service(),
                weather_prelude=self.weather_prelude_service(),
                calendar_projection=self.calendar_projection_service(),
                database_manager=self._database_manager,
                database_lock=database_lock,
                key_values=self._key_values(),
                app_name=self._app_name,
                app_version=self._app_version,
                config=config,
                settings=self._settings(),
                coach_messages=self._coach_conversation().message_service(),
                training_plans=planning.training_plan(),
                workout_library=planning.workout_library(),
                profile=athlete.profile(),
                public_feedback=self.feedback_state_service(),
                public_performance=self.performance_state_service(),
                sync_state=sync.state_repository(),
                provider_freshness=provider.freshness_service(),
                garmin_sync_state=garmin.sync_state_service(),
                sync_public_state=self.sync_public_state_service(),
                intervals_sync_lock=self._intervals_sync_lock(),
                workout_library_sync_running=self._workout_library_sync_running(),
                workout_library_sync_state=self._workout_library_sync().sync_state_service(),
                garmin_sync=garmin.sync_service(),
                provider_resync=self._provider_resync().full_resync_service(),
                planning_preview=self._adaptive_replan_preview_service(),
                morning_checkin=self._morning_checkin_state_service(),
                coach_quick_actions=self._coach_quick_actions_service(),
                provider_state=self._provider_state_service(),
                sync_period_defaults=self._sync_period_defaults(),
                all_sync_days=self._all_sync_days(),
                calendar_history_days=self._calendar_history_days(),
                calendar_future_days=self._calendar_future_days(),
                local_now=self._local_now(),
            ))
