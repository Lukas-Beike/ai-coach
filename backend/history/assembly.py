"""Compose local change-history projections and undo workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService


@dataclass(frozen=True)
class HistoryPersistence:
    database_manager: Callable[[], Any]
    profile_repository: Any


@dataclass(frozen=True)
class HistoryAthleteServices:
    profile_service: Callable[[], Any]
    competition_service: Callable[[], Any]


@dataclass(frozen=True)
class HistoryPlanningServices:
    workout_library_service: Callable[[], Any]
    planned_unit_service: Callable[[], Any]
    training_plan_service: Callable[[], Any]
    planning_revision_service: Any


class HistoryAssembly:
    """Create fresh history services over shared athlete and planning owners."""

    @dataclass(frozen=True)
    class Inputs:
        persistence: HistoryPersistence
        athlete: HistoryAthleteServices
        planning: HistoryPlanningServices

    def __init__(
        self,
        *,
        dependencies: HistoryAssembly.Inputs,
    ) -> None:
        self._database_manager = dependencies.persistence.database_manager
        self._profile_repository = dependencies.persistence.profile_repository
        self._profile_service = dependencies.athlete.profile_service
        self._competition_service = dependencies.athlete.competition_service
        self._workout_library_service = dependencies.planning.workout_library_service
        self._planned_unit_service = dependencies.planning.planned_unit_service
        self._training_plan_service = dependencies.planning.training_plan_service
        self._planning_revision_service = (
            dependencies.planning.planning_revision_service
        )

    def change_history_service(self) -> ChangeHistoryService:
        return ChangeHistoryService(self._database_manager(), self._profile_repository)

    def undo_service(self) -> HistoryUndoService:
        return HistoryUndoService(
            self._database_manager(),
            self.change_history_service(),
            self._profile_service(),
            self._workout_library_service(),
            self._competition_service(),
            self._planned_unit_service(),
            self._training_plan_service(),
            self._planning_revision_service,
        )
