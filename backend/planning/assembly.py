"""Composition for local planning persistence and approved preview application."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PlanningRepositories:
    competition: CompetitionRepository
    training_plans: TrainingPlanRepository
    key_values: Any
    plan_adjustments: PlanAdjustmentRepository


@dataclass(frozen=True)
class PlanningRuntime:
    revision: PlanningRevisionService
    event_buffer: Any
    utc_now: Callable[[], str]
    local_date: Callable[[], Any]
    uuid_factory: Callable[[], Any]
    redact: Callable[[str], str]


@dataclass(frozen=True)
class PlanningMutations:
    calendar_conflict_service: Callable[[], CalendarConflictService]
    publish_change: Callable[[], None]


class PlanningDataAssembly:
    """Create fresh local planning services using the existing domain owners."""

    @dataclass(frozen=True)
    class Inputs:
        database_manager: Callable[[], DatabaseManager]
        repositories: PlanningRepositories
        runtime: PlanningRuntime
        mutations: PlanningMutations

    def __init__(
        self,
        *,
        dependencies: "PlanningDataAssembly.Inputs",
    ) -> None:
        repositories = dependencies.repositories
        runtime = dependencies.runtime
        mutations = dependencies.mutations
        self._database_manager = dependencies.database_manager
        self._competition_repository = repositories.competition
        self._training_plan_repository = repositories.training_plans
        self._key_value_repository = repositories.key_values
        self._planning_revision_service = runtime.revision
        self._event_buffer = runtime.event_buffer
        self._utc_now = runtime.utc_now
        self._local_date = runtime.local_date
        self._uuid_factory = runtime.uuid_factory
        self._redact = runtime.redact
        self._calendar_conflict_service = mutations.calendar_conflict_service
        self._publish_change = mutations.publish_change
        self._plan_adjustment_repository = repositories.plan_adjustments

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
