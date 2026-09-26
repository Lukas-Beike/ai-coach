"""Composition for Coach planning mutations and local plan artifacts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.training_patch import CoachTrainingPatchService
from backend.db.manager import DatabaseManager
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.local_plan_creation_service import LocalTrainingPlanCreationService
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning import changes as planning_changes


class CoachPlanningToolsAssembly:
    """Create fresh Coach planning services from their explicit domain owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        local_plan_creation_service: Callable[[], LocalTrainingPlanCreationService],
        athlete_date: Callable[[], date],
        utc_now: Callable[[], str],
        uuid_factory: Callable[[], Any],
        workout_library_plan_service: Callable[[], WorkoutLibraryPlanService],
        training_change_validator: Callable[[], planning_changes.StructuredTrainingChangeValidator],
        training_change_service: Callable[[], planning_changes.StructuredTrainingChangeService],
        calendar_conflict_service: Callable[[], CalendarConflictService],
        key_value_repository: Any,
        event_buffer: Any,
        training_change_limit: int,
        adaptive_preview_service: Callable[[], AdaptiveReplanPreviewService],
        illness_pause_sync_service: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._local_plan_creation_service = local_plan_creation_service
        self._athlete_date = athlete_date
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._workout_library_plan_service = workout_library_plan_service
        self._training_change_validator = training_change_validator
        self._training_change_service = training_change_service
        self._calendar_conflict_service = calendar_conflict_service
        self._key_value_repository = key_value_repository
        self._event_buffer = event_buffer
        self._training_change_limit = training_change_limit
        self._adaptive_preview_service = adaptive_preview_service
        self._illness_pause_sync_service = illness_pause_sync_service

    def training_plan_artifact_service(self) -> TrainingPlanArtifactService:
        return TrainingPlanArtifactService(
            self._database_manager(),
            self._local_plan_creation_service(),
            self._athlete_date,
            self._utc_now,
            self._uuid_factory,
        )

    def library_plan_tool_service(self) -> CoachLibraryPlanToolService:
        return CoachLibraryPlanToolService(self._workout_library_plan_service())

    def training_patch_service(self) -> CoachTrainingPatchService:
        return CoachTrainingPatchService(
            self._database_manager(),
            self._database_lock,
            self._training_change_validator(),
            self._training_change_service(),
            self._local_plan_creation_service(),
            self._calendar_conflict_service(),
            self._key_value_repository,
            self._event_buffer,
            self._athlete_date,
            self._training_change_limit,
        )

    def adaptive_apply_service(self) -> CoachAdaptiveApplyService:
        return CoachAdaptiveApplyService(
            self._adaptive_preview_service(),
            self._illness_pause_sync_service(),
            self._database_manager(),
            self._database_lock,
        )
