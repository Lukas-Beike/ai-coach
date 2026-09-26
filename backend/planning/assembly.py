"""Composition for local planning persistence and approved preview application."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.db import DatabaseManager
from backend.db.repositories import (
    CompetitionRepository,
    PlanAdjustmentRepository,
    TrainingPlanRepository,
)
from backend.planning.adaptive import AdaptiveReplanApplyService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.competition_service import CompetitionService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.planning.training_plans import TrainingPlanService


class PlanningDataAssembly:
    """Create fresh local planning services using the existing domain owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        competition_repository: CompetitionRepository,
        training_plan_repository: TrainingPlanRepository,
        key_value_repository: Any,
        planning_revision_service: PlanningRevisionService,
        event_buffer: Any,
        utc_now: Callable[[], str],
        local_date: Callable[[], Any],
        uuid_factory: Callable[[], Any],
        redact: Callable[[str], str],
        calendar_conflict_service: Callable[[], CalendarConflictService],
        publish_change: Callable[[], None],
        plan_adjustment_repository: PlanAdjustmentRepository,
    ) -> None:
        self._database_manager = database_manager
        self._competition_repository = competition_repository
        self._training_plan_repository = training_plan_repository
        self._key_value_repository = key_value_repository
        self._planning_revision_service = planning_revision_service
        self._event_buffer = event_buffer
        self._utc_now = utc_now
        self._local_date = local_date
        self._uuid_factory = uuid_factory
        self._redact = redact
        self._calendar_conflict_service = calendar_conflict_service
        self._publish_change = publish_change
        self._plan_adjustment_repository = plan_adjustment_repository

    def competition(self) -> CompetitionService:
        return CompetitionService(
            self._database_manager(), self._competition_repository, self._utc_now
        )

    def training_plan(self) -> TrainingPlanService:
        return TrainingPlanService(
            self._database_manager(),
            self._training_plan_repository,
            self._key_value_repository,
            self._planning_revision_service,
            self._event_buffer,
            self._utc_now,
        )

    def planned_unit(self) -> PlannedUnitService:
        return PlannedUnitService(
            self._database_manager(),
            self._planning_revision_service,
            self._utc_now,
            self._local_date,
            self._uuid_factory,
            self._redact,
            self._calendar_conflict_service(),
            self._publish_change,
        )

    def workout_library(self) -> WorkoutLibraryService:
        return WorkoutLibraryService(
            self._database_manager(),
            self._utc_now,
            self._uuid_factory,
            self._publish_change,
        )

    def adaptive_apply(self) -> AdaptiveReplanApplyService:
        return AdaptiveReplanApplyService(
            self._database_manager(),
            self._plan_adjustment_repository,
            self._planning_revision_service,
            self._local_date,
            self._utc_now,
        )
