"""Local workout-library persistence use cases."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend import change_history
from backend.errors import CORRUPT_LIBRARY_ERROR, AppError
from backend.planning import library, workouts

INSERT_LIBRARY_SQL = (
    "INSERT INTO workout_library(id, local_id, external_id, payload, sync_dirty, "
    "sync_state, sync_error, last_synced_at, updated_at) "
    "VALUES (?, ?, NULL, ?, 1, 'local', NULL, NULL, ?)"
)
UPDATE_LIBRARY_SQL = (
    "UPDATE workout_library SET payload=?, sync_dirty=1, sync_state='local', "
    "sync_error=NULL, updated_at=? WHERE local_id=?"
)


class WorkoutLibraryService:
    """Own local library creation, templates, and reads."""

    def __init__(
        self,
        database_manager: Any,
        now: Callable[[], str],
        id_factory: Callable[[], Any],
        publish_change: Callable[[], None],
    ) -> None:
        self._database_manager = database_manager
        self._now = now
        self._id_factory = id_factory
        self._publish_change = publish_change

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Restore a history snapshot using the caller's transaction."""
        if target is None:
            db.execute("DELETE FROM workout_library WHERE local_id=?", (entity_id,))
            return None

        if current is None:
            restored = library.normalize_library_workout(
                target,
                local_id=entity_id,
                external_id=None,
                sync_status="local",
            )
            db.execute(
                INSERT_LIBRARY_SQL,
                (
                    entity_id,
                    entity_id,
                    json.dumps(restored, ensure_ascii=False),
                    self._now(),
                ),
            )
            return restored

        try:
            current_payload = json.loads(current["payload"])
            if not isinstance(current_payload, dict):
                raise TypeError("Current workout payload is not an object")
        except (TypeError, ValueError) as exc:
            raise AppError(
                409, "Die Bibliothekseinheit kann nicht wiederhergestellt werden."
            ) from exc

        restored = library.normalize_library_workout(
            {**current_payload, **target},
            local_id=entity_id,
            external_id=current.get("external_id"),
            sync_status="local",
        )
        db.execute(
            UPDATE_LIBRARY_SQL,
            (json.dumps(restored, ensure_ascii=False), self._now(), entity_id),
        )
        return {**restored, "sync_status": "local"}

    def update(self, local_id: Any, values: Any) -> dict[str, Any]:
        """Edit, archive, restore, or remove a local library template."""
        normalized_id = library.workout_library_entry_id(local_id)
        if not isinstance(values, dict):
            raise AppError(
                400, "Die Bibliothekseinheit muss als Objekt gesendet werden."
            )
        action = str(values.get("action") or "update").strip().casefold()
        with self._database_manager.unit_of_work() as db:
            row, current = self._stored_workout_library_entry(db, normalized_id)
            before = {
                **current,
                "sync_status": row.get("sync_state") or current.get("sync_status"),
            }
            if action == "delete":
                result = self._delete_local_workout_library_entry(
                    db, normalized_id, row, before
                )
            else:
                normalized = library.updated_workout_library_entry(
                    current, row, normalized_id, action, values
                )
                db.execute(
                    UPDATE_LIBRARY_SQL,
                    (
                        json.dumps(normalized, ensure_ascii=False),
                        self._now(),
                        normalized_id,
                    ),
                )
                change_history.record_change(
                    db,
                    "workout_library",
                    normalized_id,
                    "update",
                    before,
                    {**normalized, "sync_status": "local"},
                )
                result = {
                    "status": "local",
                    "local_id": normalized_id,
                    "library_entry": normalized,
                }
        self._publish_change()
        return result

    @staticmethod
    def _stored_workout_library_entry(
        db: Any, local_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        row = db.execute(
            "SELECT payload, external_id, sync_state FROM workout_library WHERE local_id=?",
            (local_id,),
        ).fetchone()
        if not row:
            raise AppError(404, "Bibliothekseinheit nicht gefunden.")
        try:
            current = json.loads(row["payload"])
        except (TypeError, ValueError) as exc:
            raise AppError(500, CORRUPT_LIBRARY_ERROR) from exc
        if not isinstance(current, dict):
            raise AppError(500, CORRUPT_LIBRARY_ERROR)
        if current.get("date"):
            raise AppError(
                409, "Geplante lokale Einheiten werden im Kalender bearbeitet."
            )
        return dict(row), current

    @staticmethod
    def _delete_local_workout_library_entry(
        db: Any,
        local_id: str,
        row: dict[str, Any],
        before: dict[str, Any],
    ) -> dict[str, Any]:
        if row.get("external_id"):
            raise AppError(
                409,
                "Synchronisierte Bibliothekseinheiten können nicht lokal gelöscht werden. Archiviere sie stattdessen.",
            )
        db.execute("DELETE FROM workout_library WHERE local_id=?", (local_id,))
        change_history.record_change(
            db, "workout_library", local_id, "delete", before, None
        )
        return {"status": "deleted", "local_id": local_id}

    def create_local_entry(
        self, workout: dict[str, Any], db: Any | None = None
    ) -> dict[str, Any]:
        if workout.get("date"):
            raise AppError(400, "Eine Vorlage darf kein Planungsdatum enthalten.")
        local_id = str(self._id_factory())
        library_workout = {
            **workout,
            "type": workout.get("sport") or "Ride",
            "moving_time": int(workout.get("duration_minutes") or 0) * 60,
        }
        entry = library.normalize_library_workout(
            library_workout,
            local_id=local_id,
            external_id=None,
            sync_status="local",
        )
        workouts.validate_workout_description(entry)
        updated_at = self._now()
        if db is not None:
            self._insert_local_entry(db, entry, local_id, updated_at)
        else:
            with self._database_manager.unit_of_work() as own_db:
                self._insert_local_entry(own_db, entry, local_id, updated_at)
        return entry

    @staticmethod
    def _insert_local_entry(
        db: Any, entry: dict[str, Any], local_id: str, updated_at: str
    ) -> None:
        db.execute(
            INSERT_LIBRARY_SQL,
            (local_id, local_id, json.dumps(entry, ensure_ascii=False), updated_at),
        )
        change_history.record_change(
            db, "workout_library", local_id, "create", None, entry
        )

    def create_template(self, workout: Any) -> dict[str, Any]:
        """Create a reusable local template, explicitly separate from the plan."""
        if not isinstance(workout, dict) or workout.get("date"):
            raise AppError(
                400, "Eine Bibliotheksvorlage darf kein Planungsdatum enthalten."
            )
        try:
            duration = int(workout.get("duration_minutes", 30))
        except (ValueError, TypeError) as exc:
            raise AppError(400, "Die Vorlagendauer muss eine ganze Zahl sein.") from exc
        if not 5 <= duration <= 1440:
            raise AppError(
                400, "Die Vorlagendauer muss zwischen 5 und 1440 Minuten liegen."
            )
        sport = str(workout.get("sport") or "Ride")
        if sport not in {"Ride", "VirtualRide", "Run", "Swim", "WeightTraining"}:
            raise AppError(400, "Ungueltige Sportart der Vorlage.")
        return self.create_local_entry(
            {
                "sport": sport,
                "name": workout.get("name") or "Coach-Vorlage",
                "description": workout.get("description") or "",
                "duration_minutes": duration,
                "target": workout.get("target") or "AUTO",
                "source": "coach",
            }
        )

    def list(
        self,
        limit: int = 500,
        include_archived: bool = False,
        *,
        db: Any | None = None,
    ) -> list[dict[str, Any]]:
        if db is not None:
            return self._list_in_db(db, limit, include_archived)
        with self._database_manager.unit_of_work() as own_db:
            return self._list_in_db(own_db, limit, include_archived)

    @staticmethod
    def _list_in_db(
        db: Any, limit: int, include_archived: bool
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT payload FROM workout_library WHERE json_extract(payload, '$.date') IS NULL "
            "ORDER BY lower(json_extract(payload, '$.type')), lower(json_extract(payload, '$.name')) LIMIT ?",
            (max(1, min(int(limit) * (2 if include_archived else 1), 1000)),),
        ).fetchall()
        result = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                if isinstance(payload, dict) and (
                    include_archived or not payload.get("archived")
                ):
                    result.append(payload)
            except (TypeError, ValueError):
                continue
        return result
