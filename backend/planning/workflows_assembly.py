from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.planning import changes as planning_changes
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.planning.local_plan_creation_service import LocalTrainingPlanCreationService
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.replacement_service import StructuredTrainingPlanReplacementService
from backend.planning.state_service import StructuredTrainingStateService


class PlanningWorkflowAssembly:
    """Compose planning reads, local mutations, and adaptive previews."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        planned_unit_service: Callable[[], Any],
        workout_library_service: Callable[[], Any],
        competition_service: Callable[[], Any],
        training_plan_service: Callable[[], Any],
        checkin_service: Callable[[], Any],
        activity_feedback_service: Callable[[], Any],
        planning_state_repository: Any,
        training_plan_repository: Any,
        key_values: Any,
        planning_revision: Any,
        plan_adjustment_repository: Any,
        external_calendar_reader: Callable[[], Any],
        weather_service: Callable[[], Any],
        morning_body_battery_service: Callable[[], Any],
        sync_job_queue_service: Callable[[], Any],
        coach_artifact_refs: Callable[[], Any],
        local_date: Callable[[], Any],
        utc_now: Callable[[], Any],
        uuid_factory: Callable[[], Any],
        event_buffer: Any,
        logger: Any,
        training_change_limit: int,
        calendar_window_days: int,
        checkin_text_limit: int,
        default_illness_pause_days: int,
        weather_adaptive_max_minutes: int,
    ) -> None:
        self._database_manager = database_manager
        self._planned_unit_service = planned_unit_service
        self._workout_library_service = workout_library_service
        self._competition_service = competition_service
        self._training_plan_service = training_plan_service
        self._checkin_service = checkin_service
        self._activity_feedback_service = activity_feedback_service
        self._planning_state_repository = planning_state_repository
        self._training_plan_repository = training_plan_repository
        self._key_values = key_values
        self._planning_revision = planning_revision
        self._plan_adjustment_repository = plan_adjustment_repository
        self._external_calendar_reader = external_calendar_reader
        self._weather_service = weather_service
        self._morning_body_battery_service = morning_body_battery_service
        self._sync_job_queue_service = sync_job_queue_service
        self._coach_artifact_refs = coach_artifact_refs
        self._local_date = local_date
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._event_buffer = event_buffer
        self._logger = logger
        self._training_change_limit = training_change_limit
        self._calendar_window_days = calendar_window_days
        self._checkin_text_limit = checkin_text_limit
        self._default_illness_pause_days = default_illness_pause_days
        self._weather_adaptive_max_minutes = weather_adaptive_max_minutes

    def calendar_conflict_service(self) -> CalendarConflictService:
        return CalendarConflictService(
            self._database_manager(), self._external_calendar_reader()
        )

    def workout_library_plan_service(self) -> WorkoutLibraryPlanService:
        return WorkoutLibraryPlanService(
            self._database_manager(),
            self._planned_unit_service(),
            self.calendar_conflict_service(),
            lambda: self._event_buffer.publish("coach", {"status": "changed"}),
        )

    def local_plan_creation_service(self) -> LocalTrainingPlanCreationService:
        return LocalTrainingPlanCreationService(
            self._database_manager(),
            self._training_plan_repository,
            self._planned_unit_service(),
            self._workout_library_service(),
            self.calendar_conflict_service(),
            self._planning_revision,
            self._local_date,
            self._utc_now,
            self._uuid_factory,
            self._logger,
        )

    def daily_planning_context_service(self) -> DailyPlanningContextService:
        return DailyPlanningContextService(
            self._database_manager(),
            self._key_values,
            self._checkin_service(),
            self._external_calendar_reader(),
            self._morning_body_battery_service(),
            self._activity_feedback_service(),
            self._local_date,
            self._calendar_window_days,
        )

    def structured_training_state_service(self) -> StructuredTrainingStateService:
        return StructuredTrainingStateService(
            self._database_manager(),
            self._planning_state_repository,
            self._competition_service(),
            self._training_plan_service(),
            self._coach_artifact_refs(),
            self._sync_job_queue_service().list,
            self._local_date,
        )

    def structured_training_change_validator(self) -> planning_changes.StructuredTrainingChangeValidator:
        return planning_changes.StructuredTrainingChangeValidator(
            self._planning_state_repository, self.calendar_conflict_service()
        )

    def structured_training_change_service(self) -> planning_changes.StructuredTrainingChangeService:
        return planning_changes.StructuredTrainingChangeService(
            self._database_manager(),
            self.structured_training_change_validator(),
            planning_changes.StructuredTrainingPlanResolver(self._training_plan_repository),
            self._planned_unit_service(),
            self._planning_revision,
            self._training_plan_service(),
            self._local_date,
            self._training_change_limit,
            lambda: self._event_buffer.publish("planning", {"status": "changed"}),
        )

    def structured_training_plan_replacement_service(self) -> StructuredTrainingPlanReplacementService:
        return StructuredTrainingPlanReplacementService(
            self._database_manager(),
            self._planning_state_repository,
            self._planning_revision,
            self._training_plan_repository,
            self._key_values,
            self.calendar_conflict_service(),
            self._planned_unit_service(),
            self._local_date,
            self._utc_now,
            self._uuid_factory,
        )

    def adaptive_replan_preview_service(self) -> AdaptiveReplanPreviewService:
        return AdaptiveReplanPreviewService(
            self._database_manager(),
            self._plan_adjustment_repository,
            self._checkin_service(),
            self._planned_unit_service(),
            self._external_calendar_reader(),
            self._weather_service(),
            self._local_date,
            self._utc_now,
            self._uuid_factory,
            self._calendar_window_days,
            self._checkin_text_limit,
            self._default_illness_pause_days,
            self._weather_adaptive_max_minutes,
        )


