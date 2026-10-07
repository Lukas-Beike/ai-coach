from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.planning import changes as planning_changes
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.local_plan_creation_service import (
    LocalTrainingPlanCreationService,
)
from backend.planning.replacement_service import (
    StructuredTrainingPlanReplacementService,
)
from backend.planning.state_service import StructuredTrainingStateService


@dataclass(frozen=True)
class PlanningServiceOwners:
    database_manager: Callable[[], Any]
    planned_unit_service: Callable[[], Any]
    workout_library_service: Callable[[], Any]
    competition_service: Callable[[], Any]
    training_plan_service: Callable[[], Any]
    checkin_service: Callable[[], Any]


@dataclass(frozen=True)
class PlanningRepositories:
    state_repository: Any
    training_plan_repository: Any
    key_values: Any
    revision_service: Any
    plan_adjustment_repository: Any


@dataclass(frozen=True)
class DailyPlanningSources:
    activity_feedback_service: Callable[[], Any]
    external_calendar_reader: Callable[[], Any]
    weather_service: Callable[[], Any]
    morning_body_battery_service: Callable[[], Any]
    local_date: Callable[[], Any]
    calendar_window_days: int
    checkin_text_limit: int


@dataclass(frozen=True)
class PlanningRuntime:
    sync_job_queue_service: Callable[[], Any]
    coach_artifact_refs: Callable[[], Any]
    utc_now: Callable[[], Any]
    uuid_factory: Callable[[], Any]
    event_buffer: Any
    logger: Any


@dataclass(frozen=True)
class PlanningChangeLimits:
    training_change_limit: int
    default_illness_pause_days: int
    weather_adaptive_max_minutes: int


class PlanningWorkflowAssembly:
    """Compose planning reads, local mutations, and adaptive previews."""

    @dataclass(frozen=True)
    class Inputs:
        owners: PlanningServiceOwners
        repositories: PlanningRepositories
        daily_sources: DailyPlanningSources
        runtime: PlanningRuntime
        limits: PlanningChangeLimits

    def __init__(self, *, dependencies: PlanningWorkflowAssembly.Inputs) -> None:
        owners = dependencies.owners
        repositories = dependencies.repositories
        daily = dependencies.daily_sources
        runtime = dependencies.runtime
        limits = dependencies.limits
        self._database_manager = owners.database_manager
        self._planned_unit_service = owners.planned_unit_service
        self._workout_library_service = owners.workout_library_service
        self._competition_service = owners.competition_service
        self._training_plan_service = owners.training_plan_service
        self._checkin_service = owners.checkin_service
        self._planning_state_repository = repositories.state_repository
        self._training_plan_repository = repositories.training_plan_repository
        self._key_values = repositories.key_values
        self._planning_revision = repositories.revision_service
        self._plan_adjustment_repository = repositories.plan_adjustment_repository
        self._activity_feedback_service = daily.activity_feedback_service
        self._external_calendar_reader = daily.external_calendar_reader
        self._weather_service = daily.weather_service
        self._morning_body_battery_service = daily.morning_body_battery_service
        self._local_date = daily.local_date
        self._calendar_window_days = daily.calendar_window_days
        self._checkin_text_limit = daily.checkin_text_limit
        self._sync_job_queue_service = runtime.sync_job_queue_service
        self._coach_artifact_refs = runtime.coach_artifact_refs
        self._utc_now = runtime.utc_now
        self._uuid_factory = runtime.uuid_factory
        self._event_buffer = runtime.event_buffer
        self._logger = runtime.logger
        self._training_change_limit = limits.training_change_limit
        self._default_illness_pause_days = limits.default_illness_pause_days
        self._weather_adaptive_max_minutes = limits.weather_adaptive_max_minutes

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

    def structured_training_change_validator(
        self,
    ) -> planning_changes.StructuredTrainingChangeValidator:
        return planning_changes.StructuredTrainingChangeValidator(
            self._planning_state_repository, self.calendar_conflict_service()
        )

    def structured_training_change_service(
        self,
    ) -> planning_changes.StructuredTrainingChangeService:
        return planning_changes.StructuredTrainingChangeService(
            self._database_manager(),
            self.structured_training_change_validator(),
            planning_changes.StructuredTrainingPlanResolver(
                self._training_plan_repository
            ),
            self._planned_unit_service(),
            self._planning_revision,
            self._training_plan_service(),
            self._local_date,
            self._training_change_limit,
            lambda: self._event_buffer.publish("planning", {"status": "changed"}),
        )

    def structured_training_plan_replacement_service(
        self,
    ) -> StructuredTrainingPlanReplacementService:
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
