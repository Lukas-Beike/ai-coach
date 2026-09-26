"""Composition for read-only Coach tools over existing domain owners."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.coach.read_tools import CoachReadToolService


class CoachReadToolsAssembly:
    """Create fresh activity and general read-only tool services."""

    def __init__(
        self,
        *,
        activity_read_service: Callable[[], Any],
        garmin_payload_service: Callable[[], Any],
        profile_service: Callable[[], Any],
        today: Callable[[], date],
        structured_training_state_service: Callable[[], Any],
        workout_library_service: Callable[[], Any],
        planned_unit_service: Callable[[], Any],
        change_history_service: Callable[[], Any],
        competition_service: Callable[[], Any],
        training_plan_service: Callable[[], Any],
        nutrition_service: Callable[[], Any],
        training_change_limit: Callable[[], int],
    ) -> None:
        self._activity_read_service = activity_read_service
        self._garmin_payload_service = garmin_payload_service
        self._profile_service = profile_service
        self._today = today
        self._structured_training_state_service = structured_training_state_service
        self._workout_library_service = workout_library_service
        self._planned_unit_service = planned_unit_service
        self._change_history_service = change_history_service
        self._competition_service = competition_service
        self._training_plan_service = training_plan_service
        self._nutrition_service = nutrition_service
        self._training_change_limit = training_change_limit

    def activity_read_service(self) -> CoachActivityReadToolService:
        return CoachActivityReadToolService(
            self._activity_read_service(),
            self._garmin_payload_service(),
            self._profile_service(),
            self._today,
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
        )
