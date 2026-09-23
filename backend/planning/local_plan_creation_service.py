"""Create local training-plan units and optional plan metadata."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend import change_history
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import workouts as planning_workouts


class LocalTrainingPlanCreationService:
    """Own the local transaction for creating a plan and its planned units."""

    def __init__(
        self,
        database_manager: Any,
        training_plan_repository: Any,
        planned_unit_service: Any,
        workout_library_service: Any,
        calendar_conflict_service: Any,
        planning_revision_service: Any,
        today: Callable[[], date],
        now: Callable[[], str],
        id_factory: Callable[[], Any],
        logger: Any,
    ) -> None:
        self._database_manager = database_manager
        self._training_plan_repository = training_plan_repository
        self._planned_unit_service = planned_unit_service
        self._workout_library_service = workout_library_service
        self._calendar_conflict_service = calendar_conflict_service
        self._planning_revision_service = planning_revision_service
        self._today = today
        self._now = now
        self._id_factory = id_factory
        self._logger = logger

    def validate_calendar(self, workouts: list[dict[str, Any]]) -> None:
        """Reject duplicate plan dates and dates already occupied locally."""
        requested_dates: set[str] = set()
        for workout in workouts:
            workout_date = workout["date"]
            if workout_date in requested_dates:
                raise AppError(
                    409,
                    f"Der Plan enthält mehrere Einheiten für den {workout_date}; pro Tag ist eine Einheit möglich.",
                    reason="plan_date_conflict",
                )
            if self._calendar_conflict_service.conflicts({"date": workout_date}):
                raise AppError(
                    409,
                    f"Für den {workout_date} existiert bereits eine lokale Kalendereinheit. Berücksichtige diesen Termin und plane zusätzliche Einheiten an freien Tagen.",
                    reason="plan_date_conflict",
                )
            requested_dates.add(workout_date)

    def save(
        self,
        workouts: list[dict[str, Any]],
        plan_name: str = "",
        goal: str = "",
        *,
        db: Any = None,
    ) -> list[dict[str, Any]]:
        """Store planned coach sessions locally, reusing cached templates first."""
        if not isinstance(workouts, list) or not workouts:
            raise AppError(400, "Mindestens eine Einheit ist erforderlich.")
        normalized_workouts = [
            planning_workouts.normalize_workout(item, today=self._today())
            for item in workouts
        ]
        if db is not None:
            return self._save_in_db(db, normalized_workouts, plan_name, goal)
        with self._database_manager.unit_of_work() as own_db:
            return self._save_in_db(own_db, normalized_workouts, plan_name, goal)

    def _save_in_db(
        self,
        db: Any,
        normalized_workouts: list[dict[str, Any]],
        plan_name: str,
        goal: str,
    ) -> list[dict[str, Any]]:
        plan_id = str(self._id_factory()) if plan_name.strip() else ""
        now = self._now()
        templates = [
            item
            for item in self._workout_library_service.list(db=db)
            if not item.get("date")
        ]
        if plan_id:
            dates = sorted(item["date"] for item in normalized_workouts)
            name = plan_name.strip()[:200]
            bounded_goal = goal.strip()[:2000]
            self._training_plan_repository.create(
                db,
                plan_id,
                name,
                bounded_goal,
                dates[0],
                dates[-1],
                "planned",
                now,
            )
            change_history.record_change(
                db,
                "training_plan",
                plan_id,
                "create",
                None,
                {
                    "id": plan_id,
                    "name": name,
                    "goal": bounded_goal,
                    "start_date": dates[0],
                    "end_date": dates[-1],
                    "status": "planned",
                },
            )

        self.validate_calendar(normalized_workouts)
        created = []
        for workout in normalized_workouts:
            stored = self._planned_workout_for_storage(
                workout, templates, plan_id, plan_name
            )
            entry = self._planned_unit_service.create(
                stored, db=db, bump_planning_revision=False
            )
            created.append({**entry, "created_at": now, "updated_at": now})
        if created:
            self._planning_revision_service.bump(db)
        return created

    def _planned_workout_for_storage(
        self,
        workout: dict[str, Any],
        templates: list[dict[str, Any]],
        plan_id: str,
        plan_name: str,
    ) -> dict[str, Any]:
        match = planning_library.find_similar_library_workout(workout, templates)
        if match is None:
            stored = {**workout, "source": "coach"}
        else:
            match_duration = planning_library.library_workout_duration_minutes(match)
            stored = {
                **workout,
                "sport": match.get("type") or workout["sport"],
                "name": match.get("name") or workout["name"],
                "description": match.get("description") or workout["description"],
                "duration_minutes": (
                    max(5, round(match_duration))
                    if match_duration is not None
                    else workout["duration_minutes"]
                ),
                "target": (
                    match.get("target")
                    if match.get("target") in {"AUTO", "POWER", "HR", "PACE"}
                    else "AUTO"
                ),
                "source": "library",
            }
            self._logger.info(
                "Reusing matching workout library template for local plan",
                extra={
                    "event": "workout_library_match",
                    "context": {"library_workout_id": str(match["id"])},
                },
            )
        return {
            **stored,
            **(
                {"plan_id": plan_id, "plan_name": plan_name.strip()[:200]}
                if plan_id
                else {}
            ),
        }
