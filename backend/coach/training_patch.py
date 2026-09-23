"""Apply one authorized Coach training patch as a single local transaction."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.coach.authorization import require_coach_scope
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.planning import training_plans, workouts
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.changes import (
    StructuredTrainingChangeService,
    StructuredTrainingChangeValidator,
)
from backend.planning.local_plan_creation_service import (
    LocalTrainingPlanCreationService,
)
from backend.runtime.events import StateEventBuffer

SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"
SELECT_PLANNING_REVISION_SQL = "SELECT revision FROM planning_state WHERE id=1"


class CoachTrainingPatchService:
    """Own schedule validation, revision check, plan changes, and constraints."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: Any,
        change_validator: StructuredTrainingChangeValidator,
        change_service: StructuredTrainingChangeService,
        plan_creation: LocalTrainingPlanCreationService,
        calendar_conflicts: CalendarConflictService,
        key_values: KeyValueRepository,
        events: StateEventBuffer,
        today: Callable[[], date],
        change_limit: int,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._change_validator = change_validator
        self._change_service = change_service
        self._plan_creation = plan_creation
        self._calendar_conflicts = calendar_conflicts
        self._key_values = key_values
        self._events = events
        self._today = today
        self._change_limit = change_limit

    def apply(self, arguments: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        changes, raw_workouts = arguments.get("changes", []), arguments.get("workouts", [])
        if (
            not isinstance(changes, list)
            or not isinstance(raw_workouts, list)
            or not 1 <= len(changes) + len(raw_workouts) <= self._change_limit
        ):
            raise AppError(400, "Der Änderungssatz ist leer oder zu groß.", reason="change_limit")
        normalized = [workouts.normalize_workout(item, today=self._today()) for item in raw_workouts]
        if normalized:
            require_coach_scope(action, "local_plan")
        ids = [str(item.get("local_id") or "") for item in changes]
        if len(set(ids)) != len(ids):
            raise AppError(400, "Eine Einheit darf nur einmal im Änderungssatz vorkommen.", reason="invalid_change")

        with self._db_lock, self._database_manager.unit_of_work() as db:
            revision = db.execute(SELECT_PLANNING_REVISION_SQL).fetchone()["revision"]
            if type(arguments.get("expected_revision")) is not int or arguments["expected_revision"] != revision:
                raise AppError(409, "Der Plan wurde inzwischen geändert. Lies den aktuellen Stand erneut.", reason="planning_revision_conflict")
            self._validate_schedule(changes, normalized, ids, db)
            changed = (
                self._change_service.apply_in_db(db, arguments, require_revision=True)
                if changes else {"changes": []}
            )
            plan_name = str(arguments.get("plan_name") or ("Coach-Plan" if action["request"]["constraints"] else ""))
            created = (
                self._plan_creation.save(normalized, plan_name, str(arguments.get("goal") or ""), db=db)
                if normalized else []
            )
            self._store_constraints(created, ids, action["request"]["constraints"], db)
            revision = db.execute(SELECT_PLANNING_REVISION_SQL).fetchone()["revision"]
        self._events.publish("planning", {"status": "changed"})
        return {
            "ok": True,
            "status": "applied",
            "planning_revision": revision,
            "changes": changed["changes"],
            "library_entry_ids": [item["id"] for item in created],
        }

    def _validate_schedule(
        self, changes: list[dict[str, Any]], normalized: list[dict[str, Any]], ids: list[str], db: Any
    ) -> None:
        self._change_validator.validate_batch(changes, db)
        final_dates: set[str] = set()
        for change in changes:
            if change.get("action") not in {"delete", "archive"}:
                row = db.execute(SELECT_PLANNED_PAYLOAD_SQL, (change["local_id"],)).fetchone()
                final_dates.add(str(change.get("date") or json.loads(row["payload"])["date"])[:10])
        for workout in normalized:
            day = workout["date"][:10]
            if day in final_dates or self._calendar_conflicts.conflicts({"date": day}, set(ids)):
                raise AppError(409, f"Für den {day} besteht ein Kalenderkonflikt.", reason="plan_date_conflict")
            final_dates.add(day)

    def _store_constraints(
        self, created: list[dict[str, Any]], ids: list[str], constraints: list[str], db: Any
    ) -> None:
        plan_ids = {str(item.get("plan_id") or "") for item in created}
        for local_id in ids:
            row = db.execute(SELECT_PLANNED_PAYLOAD_SQL, (local_id,)).fetchone()
            plan_ids.add(str(json.loads(row["payload"]).get("plan_id") or ""))
        if constraints:
            for plan_id in plan_ids - {""}:
                self._key_values.set(
                    db, training_plans.COACH_PLAN_CONSTRAINTS_PREFIX + plan_id,
                    json.dumps(constraints, ensure_ascii=False),
                )
