"""Dispatch read-only Coach tools to their owning domain services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.athlete.profile import ProfileService
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.nutrition.service import NutritionService
from backend.planning.competition_service import CompetitionService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.state_service import StructuredTrainingStateService
from backend.planning.training_plans import TrainingPlanService


class CoachReadToolService:
    """Own read-tool selection, bounds, and response projection."""

    def __init__(
        self,
        profile_service: Callable[[], ProfileService],
        structured_training_state_service: Callable[[], StructuredTrainingStateService],
        activity_read_tool_service: Callable[[], CoachActivityReadToolService],
        workout_library_service: Callable[[], WorkoutLibraryService],
        planned_unit_service: Callable[[], PlannedUnitService],
        change_history_service: Callable[[], ChangeHistoryService],
        competition_service: Callable[[], CompetitionService],
        training_plan_service: Callable[[], TrainingPlanService],
        training_change_limit: int,
        nutrition_service: Callable[[], NutritionService] | None = None,
    ) -> None:
        self._profile_service = profile_service
        self._structured_training_state_service = structured_training_state_service
        self._activity_read_tool_service = activity_read_tool_service
        self._workout_library_service = workout_library_service
        self._planned_unit_service = planned_unit_service
        self._change_history_service = change_history_service
        self._competition_service = competition_service
        self._training_plan_service = training_plan_service
        self._training_change_limit = training_change_limit
        self._nutrition_service = nutrition_service

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        if name == "read_profile":
            return {"ok": True, "profile": self._profile_service().get()}
        if name == "read_training_state":
            return {
                "ok": True,
                **self._structured_training_state_service().read(
                    include_inactive=bool(arguments.get("include_inactive")),
                    cursor=arguments.get("cursor"),
                    limit=arguments.get("limit"),
                ),
            }
        if name in {"list_recent_activities", "get_activity_details"}:
            return self._activity_read_tool_service().execute(name, arguments)
        if name == "list_workout_library":
            limit = self._bounded_integer(
                arguments, "limit", 100, 500, "Bibliothekslimit ist ungültig."
            )
            return {
                "ok": True,
                "templates": self._workout_library_service().list(
                    limit, include_archived=bool(arguments.get("include_archived"))
                ),
            }
        if name == "list_planned_workouts":
            limit = self._bounded_integer(
                arguments,
                "limit",
                100,
                self._training_change_limit,
                "Planungslimit ist ungültig.",
            )
            return {"ok": True, **self._planned_unit_service().list_for_coach(limit)}
        if name == "list_change_history":
            limit = self._bounded_integer(
                arguments, "limit", 100, 500, "Historienlimit ist ungültig."
            )
            return {"ok": True, "changes": self._change_history_service().list(limit)}
        if name == "list_competitions":
            return {"ok": True, "competitions": self._competition_service().list()}
        if name == "list_training_plans":
            return {"ok": True, "training_plans": self._training_plan_service().list(100)}
        if name == "read_nutrition":
            return self._read_nutrition(arguments)
        return None

    def _read_nutrition(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._nutrition_service:
            return {"ok": False, "error": "NutritionService ist nicht verfügbar."}
        service = self._nutrition_service()
        if arguments.get("date"):
            return {"ok": True, **service.get_day_summary(str(arguments["date"]))}
        if arguments.get("start") and arguments.get("end"):
            return {
                "ok": True,
                "summaries": service.get_range_summary(
                    str(arguments["start"]), str(arguments["end"])
                ),
            }
        return {"ok": True, **service.get_today_summary()}

    @staticmethod
    def _bounded_integer(
        arguments: dict[str, Any], key: str, default: int, maximum: int, error: str
    ) -> int:
        try:
            return max(1, min(int(arguments.get(key, default)), maximum))
        except (TypeError, ValueError) as exc:
            raise AppError(400, error, reason="invalid_list_request") from exc
