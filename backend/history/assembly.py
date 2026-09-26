"""Compose local change-history projections and undo workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService


class HistoryAssembly:
    """Create fresh history services over shared athlete and planning owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        profile_repository: Any,
        profile_service: Callable[[], Any],
        workout_library_service: Callable[[], Any],
        competition_service: Callable[[], Any],
        planned_unit_service: Callable[[], Any],
        training_plan_service: Callable[[], Any],
        planning_revision_service: Any,
    ) -> None:
        self._database_manager = database_manager
        self._profile_repository = profile_repository
        self._profile_service = profile_service
        self._workout_library_service = workout_library_service
        self._competition_service = competition_service
        self._planned_unit_service = planned_unit_service
        self._training_plan_service = training_plan_service
        self._planning_revision_service = planning_revision_service

    def change_history_service(self) -> ChangeHistoryService:
        return ChangeHistoryService(
            self._database_manager(), self._profile_repository
        )

    def undo_service(self) -> HistoryUndoService:
        return HistoryUndoService(
            self._database_manager(), self.change_history_service(),
            self._profile_service(), self._workout_library_service(),
            self._competition_service(), self._planned_unit_service(),
            self._training_plan_service(), self._planning_revision_service,
        )
