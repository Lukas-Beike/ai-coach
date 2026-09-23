"""Apply saved workout-library templates to the local plan."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import (
    CORRUPT_LIBRARY_ERROR,
    INVALID_LIBRARY_ID_ERROR,
    INVALID_PLANNING_DATE_ERROR,
    AppError,
)

SELECT_LIBRARY_PAYLOAD_SQL = "SELECT payload FROM workout_library WHERE local_id = ?"


class WorkoutLibraryPlanService:
    """Plan local workout-library templates as one atomic batch."""

    def __init__(
        self,
        database_manager: Any,
        planned_unit_service: Any,
        calendar_conflict_service: Any,
        publish_change: Callable[[], None],
    ) -> None:
        self._database_manager = database_manager
        self._planned_unit_service = planned_unit_service
        self._calendar_conflict_service = calendar_conflict_service
        self._publish_change = publish_change

    def apply(self, entries: Any) -> dict[str, Any]:
        if not isinstance(entries, list) or not entries:
            raise AppError(400, "Mindestens eine Bibliothekseinheit ist erforderlich.")
        if len(entries) > 14:
            raise AppError(
                400,
                "Es können höchstens 14 Bibliothekseinheiten gleichzeitig eingeplant werden.",
            )

        with self._database_manager.unit_of_work() as db:
            requested = [self._library_plan_request(db, item) for item in entries]
            self._raise_conflicts(self._library_plan_conflicts(requested))
            planned = [self._apply_request(db, request) for request in requested]

        self._publish_change()
        return {"status": "local", "planned": planned, "local_planned": len(planned)}

    @staticmethod
    def _library_plan_request(db: Any, item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise AppError(400, "Jede Planung muss ein Objekt sein.")
        try:
            workout_id = str(uuid.UUID(str(item.get("library_workout_id") or "")))
        except (ValueError, AttributeError) as exc:
            raise AppError(400, INVALID_LIBRARY_ID_ERROR) from exc
        plan_date = str(item.get("date") or "").strip()
        try:
            date.fromisoformat(plan_date)
        except (TypeError, ValueError) as exc:
            raise AppError(400, INVALID_PLANNING_DATE_ERROR) from exc

        row = db.execute(SELECT_LIBRARY_PAYLOAD_SQL, (workout_id,)).fetchone()
        if not row:
            raise AppError(
                404, "Bibliothekseinheit nicht gefunden. Bitte zuerst synchronisieren."
            )
        try:
            workout = json.loads(row["payload"])
        except (TypeError, ValueError) as exc:
            raise AppError(500, CORRUPT_LIBRARY_ERROR) from exc
        if not isinstance(workout, dict):
            raise AppError(500, CORRUPT_LIBRARY_ERROR)
        return {"library_workout_id": workout_id, "date": plan_date, "workout": workout}

    def _library_plan_conflicts(
        self, requested: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        seen_dates: dict[str, str] = {}
        for request in requested:
            plan_date = request["date"]
            workout_id = request["library_workout_id"]
            previous_id = seen_dates.get(plan_date)
            if previous_id:
                conflicts.append(
                    {
                        "name": (
                            "Doppelte Bibliothekseinheit"
                            if previous_id == workout_id
                            else "Mehrere Einheiten"
                        ),
                        "date": plan_date,
                    }
                )
            seen_dates[plan_date] = workout_id

            source = request["workout"]
            source_date = str(source.get("date") or "")[:10]
            already_planned = source_date == plan_date and source.get("source") in {
                "coach",
                "library",
            }
            request["already_planned"] = already_planned
            if not already_planned:
                conflicts.extend(
                    self._calendar_conflict_service.conflicts(
                        {"date": plan_date}, {workout_id}
                    )
                )
        return conflicts

    @staticmethod
    def _raise_conflicts(conflicts: list[dict[str, Any]]) -> None:
        if not conflicts:
            return
        descriptions = ", ".join(
            f"{item.get('date')}: {item.get('name') or 'Einheit'}"
            for item in conflicts[:8]
        )
        suffix = (
            " Weitere Konflikte wurden nicht aufgelistet." if len(conflicts) > 8 else ""
        )
        raise AppError(
            409,
            f"Planung wegen bestehender Kalendereinheiten nicht möglich: {descriptions}.{suffix}",
        )

    def _apply_request(self, db: Any, request: dict[str, Any]) -> dict[str, Any]:
        source = request["workout"]
        if request["already_planned"]:
            local_entry = source
            local_status = "already_planned"
        else:
            local_entry = self._planned_unit_service.create(
                {
                    "date": request["date"],
                    "sport": source.get("type") or source.get("sport") or "Ride",
                    "name": source.get("name") or "Bibliotheks-Einheit",
                    "description": source.get("description") or "",
                    "duration_minutes": source.get("duration_minutes")
                    or max(5, round(float(source.get("moving_time") or 300) / 60)),
                    "target": source.get("target") or "AUTO",
                    "source": "library",
                    "rationale": "Aus der lokalen Trainingsbibliothek übernommen.",
                },
                db=db,
            )
            local_status = "local"
        return {
            "library_workout_id": request["library_workout_id"],
            "date": request["date"],
            "status": local_status,
            "library_entry": local_entry,
        }
