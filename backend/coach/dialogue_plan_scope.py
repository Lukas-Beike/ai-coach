"""Validate local planning references in a structured Coach dialogue."""

from __future__ import annotations

import json
from typing import Any

from backend.coach.authorization import require_coach_scope
from backend.db.manager import DatabaseManager
from backend.errors import AppError

SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"
SELECT_USER_MESSAGE_SQL = "SELECT id FROM messages WHERE client_turn_id=? AND role='user'"


class CoachDialoguePlanScopeService:
    """Check date and provenance bounds while leaving all data ownership in the DB manager."""

    def __init__(self, database_manager: DatabaseManager, db_lock: Any) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock

    def validate(self, name: str, arguments: dict[str, Any], action: dict[str, Any]) -> None:
        start, end = action["period"]["start"], action["period"]["end"]
        action.pop("_artifact_explicit", None)
        workouts = arguments.get("workouts", []) or (arguments.get("payload") or {}).get("workouts", [])
        for workout in workouts:
            self._check_date(workout.get("date"), start, end)

        with self._db_lock, self._database_manager.unit_of_work() as db:
            for change in arguments.get("changes", []):
                local_id = str(change.get("local_id") or "")
                require_coach_scope(action, f"planned_unit:{local_id}")
                row = db.execute(SELECT_PLANNED_PAYLOAD_SQL, (local_id,)).fetchone()
                if not row:
                    raise AppError(404, "Die ausgewählte Einheit fehlt.", reason="request_object_missing")
                self._check_date(json.loads(row["payload"]).get("date"), start, end)
                if change.get("date"):
                    self._check_date(change["date"], start, end)

            if name == "commit_training_plan":
                self._validate_artifact(action, start, end, db)

            if name == "apply_workout_library_plan":
                for entry in arguments.get("entries", []):
                    self._check_date(entry.get("date"), start, end)

    @staticmethod
    def _check_date(value: Any, start: str, end: str) -> None:
        value = str(value or "")[:10]
        if not start <= value <= end:
            raise AppError(403, "Die Änderung liegt außerhalb des beauftragten Zeitraums.", reason="request_period")

    def _validate_artifact(self, action: dict[str, Any], start: str, end: str, db: Any) -> None:
        artifact = db.execute(
            "SELECT client_turn_id, payload FROM coach_plan_artifacts WHERE id=?",
            (action.get("artifact_id"),),
        ).fetchone()
        origin = db.execute(SELECT_USER_MESSAGE_SQL, (artifact["client_turn_id"],)).fetchone() if artifact else None
        if not origin or origin["id"] not in action["request"]["source_message_ids"]:
            raise AppError(409, "Dieser Entwurf gehört nicht zum aktuellen lokalen Gespräch.", reason="artifact_conversation_conflict")
        for workout in json.loads(artifact["payload"]).get("workouts", []):
            self._check_date(workout.get("date"), start, end)
        action["_artifact_explicit"] = True
