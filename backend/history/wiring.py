"""Build the change-history and undo services from the application context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.app.context import AppContext
from backend.db.repositories import ProfileRepository
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService


@dataclass(frozen=True)
class HistoryServices:
    change_history_service: Callable[[], ChangeHistoryService]
    undo_service: Callable[[], HistoryUndoService]


def build_history(ctx: AppContext) -> HistoryServices:
    """Fresh services per call over the current database and domain owners."""
    profiles = ProfileRepository(ctx.key_values)

    def record_services() -> dict[str, Any]:
        athlete, nutrition = ctx.athlete, ctx.nutrition
        return {
            "nutrition_entry": nutrition.diary_service(),
            "checkin": athlete.checkin(),
            "nutrition_template": nutrition.meal_library_service(),
            "nutrition_product": nutrition.product_catalog_service(),
            # The Coach's food gap fill is recorded and undone there.
            "food_database_entry": nutrition.food_mirror(),
            **athlete.equipment_history(),
        }

    def change_history_service() -> ChangeHistoryService:
        athlete = ctx.athlete
        return ChangeHistoryService(
            ctx.database(),
            profiles,
            zone_service=athlete.zones(),
            feedback_service=athlete.activity_feedback(),
            session_corrections=athlete.session_corrections(),
            record_services=record_services(),
        )

    def undo_service() -> HistoryUndoService:
        athlete, planning = ctx.athlete, ctx.planning
        profile = athlete.profile()
        return HistoryUndoService(
            ctx.database(),
            change_history_service(),
            profile,
            planning.workout_library(),
            planning.competition(),
            planning.planned_unit(),
            planning.training_plan(),
            ctx.planning_revision,
            zone_service=athlete.zones(),
            feedback_service=athlete.activity_feedback(),
            session_corrections=athlete.session_corrections(),
            record_services=record_services(),
            profile_mutation_coordinator=profile.mutation_coordinator,
        )

    return HistoryServices(change_history_service, undo_service)
