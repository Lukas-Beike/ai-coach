"""Composition for read-only Coach tools over existing domain owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.coach.read_tools import CoachReadToolService


@dataclass(frozen=True)
class CoachActivityReadSources:
    activity_read_service: Callable[[], Any]
    garmin_payload_service: Callable[[], Any]
    profile_service: Callable[[], Any]
    today: Callable[[], date]
    report_services: Callable[[], Any] | None = None


@dataclass(frozen=True)
class CoachPlanningReadSources:
    structured_training_state_service: Callable[[], Any]
    workout_library_service: Callable[[], Any]
    planned_unit_service: Callable[[], Any]
    change_history_service: Callable[[], Any]
    competition_service: Callable[[], Any]
    training_plan_service: Callable[[], Any]


@dataclass(frozen=True)
class CoachReadToolPolicy:
    nutrition_service: Callable[[], Any]
    training_change_limit: Callable[[], int]
    context_service: Callable[[], Any] | None = None


class CoachReadToolsAssembly:
    """Create fresh activity and general read-only tool services."""

    @dataclass(frozen=True)
    class Inputs:
        activity: CoachActivityReadSources
        planning: CoachPlanningReadSources
        policy: CoachReadToolPolicy

    def __init__(
        self,
        *,
        dependencies: CoachReadToolsAssembly.Inputs,
    ) -> None:
        activity = dependencies.activity
        planning = dependencies.planning
        policy = dependencies.policy
        self._activity_read_service = activity.activity_read_service
        self._garmin_payload_service = activity.garmin_payload_service
        self._profile_service = activity.profile_service
        self._today = activity.today
        self._report_services = activity.report_services
        self._structured_training_state_service = (
            planning.structured_training_state_service
        )
        self._workout_library_service = planning.workout_library_service
        self._planned_unit_service = planning.planned_unit_service
        self._change_history_service = planning.change_history_service
        self._competition_service = planning.competition_service
        self._training_plan_service = planning.training_plan_service
        self._nutrition_service = policy.nutrition_service
        self._training_change_limit = policy.training_change_limit
        self._context_service = policy.context_service

    def activity_read_service(self) -> CoachActivityReadToolService:
        return CoachActivityReadToolService(
            self._activity_read_service(),
            self._garmin_payload_service(),
            self._profile_service(),
            self._today,
            self._report_services() if self._report_services else None,
        )

    def read_service(self) -> CoachReadToolService:
        return CoachReadToolService(
            self._profile_service,
            self._structured_training_state_service,
            self.activity_read_service,
            self._workout_library_service,
            self._planned_unit_service,
            self._change_history_service,
            self._competition_service,
            self._training_plan_service,
            self._training_change_limit(),
            self._nutrition_service,
            self._context_service,
        )
