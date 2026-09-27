"""Composition for local Coach dialogue and athlete check-in services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.coach.context import CoachQuickActionsService
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.coach.clarification import CoachClarificationService
from backend.coach.morning import ManualMorningCheckinService, MorningCheckinStateService


@dataclass(frozen=True)
class CoachLocalState:
    database_manager: Callable[[], Any]
    database_lock: Any
    key_values: Any


@dataclass(frozen=True)
class CoachLocalPlanning:
    sync_job_queue: Callable[[], Any]
    local_date: Callable[[], Any]
    adaptive_preview: Callable[[], Any]
    planned_workout_label: str


@dataclass(frozen=True)
class CoachLocalGarmin:
    sync_service: Callable[[], Any]
    payload_service: Callable[[], Any]
    morning_body_battery: Callable[[], Any]
    logger: Any


class CoachLocalAssembly:
    """Build fresh Coach-local services from the shared application owners."""

    @dataclass(frozen=True)
    class Inputs:
        state: CoachLocalState
        planning: CoachLocalPlanning
        garmin: CoachLocalGarmin

    def __init__(
        self,
        *,
        dependencies: "CoachLocalAssembly.Inputs",
    ) -> None:
        state = dependencies.state
        planning = dependencies.planning
        garmin = dependencies.garmin
        self._database_manager = state.database_manager
        self._database_lock = state.database_lock
        self._key_values = state.key_values
        self._sync_job_queue = planning.sync_job_queue
        self._local_date = planning.local_date
        self._adaptive_preview = planning.adaptive_preview
        self._planned_workout_label = planning.planned_workout_label
        self._garmin_sync = garmin.sync_service
        self._garmin_payload = garmin.payload_service
        self._morning_body_battery = garmin.morning_body_battery
        self._logger = garmin.logger

    def quick_actions_service(self) -> CoachQuickActionsService:
        return CoachQuickActionsService(
            self._database_manager(), self._key_values, self._adaptive_preview(),
            self._local_date, self._planned_workout_label,
        )

    def dialogue_action_service(self) -> CoachDialogueActionService:
        manager = self._database_manager()
        return CoachDialogueActionService(
            manager, self._database_lock, self._sync_job_queue,
            CoachDialoguePlanScopeService(manager, self._database_lock),
            self._local_date,
        )

    def clarification_service(self) -> CoachClarificationService:
        return CoachClarificationService(
            self._database_manager(), self._key_values, self._database_lock
        )

    def manual_morning_checkin_service(self) -> ManualMorningCheckinService:
        return ManualMorningCheckinService(
            self._garmin_sync(), self._garmin_payload(),
            self._morning_body_battery(), self._local_date, self._logger,
        )

    def morning_checkin_state_service(self) -> MorningCheckinStateService:
        return MorningCheckinStateService(
            self._database_manager(), self._key_values, self._local_date
        )
