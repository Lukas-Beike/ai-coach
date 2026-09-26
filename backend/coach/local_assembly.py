"""Composition for local Coach dialogue and athlete check-in services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.context import CoachQuickActionsService
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.coach.clarification import CoachClarificationService
from backend.coach.morning import ManualMorningCheckinService, MorningCheckinStateService


class CoachLocalAssembly:
    """Build fresh Coach-local services from the shared application owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        database_lock: Any,
        key_values: Any,
        sync_job_queue: Callable[[], Any],
        local_date: Callable[[], Any],
        adaptive_preview: Callable[[], Any],
        planned_workout_label: str,
        garmin_sync: Callable[[], Any],
        garmin_payload: Callable[[], Any],
        morning_body_battery: Callable[[], Any],
        logger: Any,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._sync_job_queue = sync_job_queue
        self._local_date = local_date
        self._adaptive_preview = adaptive_preview
        self._planned_workout_label = planned_workout_label
        self._garmin_sync = garmin_sync
        self._garmin_payload = garmin_payload
        self._morning_body_battery = morning_body_battery
        self._logger = logger

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
