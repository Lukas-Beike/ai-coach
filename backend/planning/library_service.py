"""Local workout-library persistence use cases."""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from typing import Any

from backend import change_history
from backend.canonical.planning_fields import SESSION_FOCUS_KEYS as FOCUS_KEYS
from backend.canonical.vocabulary import WAHOO_ID, RemoteEntityKind, Sport
from backend.db import planning_store
from backend.db.remote_links import RemoteLinkRepository
from backend.errors import CORRUPT_LIBRARY_ERROR, AppError
from backend.planning import library, workouts
from backend.planning.sport import with_activity_type
from backend.providers.intervals_workouts import (
    INTERVALS_DEFAULT_WORKOUT_TYPE,
    INTERVALS_TEMPLATE_WORKOUT_TYPES,
    intervals_record_type,
)

_REMOTE_LINKS = RemoteLinkRepository()
_CANONICAL_SPORT_VALUES = frozenset(item.value for item in Sport)


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
            planning_store.delete_library_workout(db, entity_id)
            # A Wahoo plan stays removable by its link.
            _REMOTE_LINKS.delete_for_entity(
                db, RemoteEntityKind.LIBRARY_WORKOUT, entity_id, keep=(WAHOO_ID,)
            )
            return None

        if current is None:
            restored = library.normalize_library_workout(
                target,
                local_id=entity_id,
                external_id=None,
                sync_status="local",
            )
            planning_store.insert_library_workout(db, entity_id, restored, self._now())
            _REMOTE_LINKS.refresh_from_slots(
                db, RemoteEntityKind.LIBRARY_WORKOUT, entity_id
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
        planning_store.set_library_sync_state(
            db, entity_id, restored, self._now(), state="local", dirty=1
        )
        _REMOTE_LINKS.refresh_from_slots(
            db, RemoteEntityKind.LIBRARY_WORKOUT, entity_id
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
                planning_store.set_library_sync_state(
                    db, normalized_id, normalized, self._now(), state="local", dirty=1
                )
                _REMOTE_LINKS.refresh_from_slots(
                    db, RemoteEntityKind.LIBRARY_WORKOUT, normalized_id
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
        row = planning_store.library_row(db, local_id)
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
        planning_store.delete_library_workout(db, local_id)
        # A Wahoo plan stays removable by its link until the athlete's Wahoo sync.
        _REMOTE_LINKS.delete_for_entity(
            db, RemoteEntityKind.LIBRARY_WORKOUT, local_id, keep=(WAHOO_ID,)
        )
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
            **{key: value for key, value in workout.items() if key != "type"},
            "sport": workout.get("sport") or INTERVALS_DEFAULT_WORKOUT_TYPE,
            "planned_duration_s": int(workout.get("duration_minutes") or 0) * 60,
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
        planning_store.insert_library_workout(db, local_id, entry, updated_at)
        _REMOTE_LINKS.refresh_from_slots(db, RemoteEntityKind.LIBRARY_WORKOUT, local_id)
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
        sport = str(workout.get("sport") or INTERVALS_DEFAULT_WORKOUT_TYPE)
        sport_fields = {"sport": sport, "environment": workout.get("environment")}
        if sport not in INTERVALS_TEMPLATE_WORKOUT_TYPES and not (
            sport in _CANONICAL_SPORT_VALUES
            and intervals_record_type(sport_fields) in INTERVALS_TEMPLATE_WORKOUT_TYPES
        ):
            raise AppError(400, "Ungültige Sportart der Vorlage.")
        return self.create_local_entry(
            {
                **sport_fields,
                "name": workout.get("name") or "Coach-Vorlage",
                "description": workout.get("description") or "",
                "duration_minutes": duration,
                "target": workout.get("target") or "AUTO",
                # The focus and structure the Coach wrote stay with the template.
                **{
                    key: workout[key]
                    for key in FOCUS_KEYS
                    if workout.get(key) is not None
                },
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
        with self._database_manager.reader() as own_db:
            return self._list_in_db(own_db, limit, include_archived)

    @staticmethod
    def page_in_transaction(
        db: Any, cursor: builtins.list[str] | None, limit: int
    ) -> builtins.list[Any]:
        return planning_store.library_template_page(db, cursor, limit)

    @staticmethod
    def _list_in_db(
        db: Any, limit: int, include_archived: bool
    ) -> builtins.list[dict[str, Any]]:
        rows = planning_store.library_templates(
            db,
            include_archived,
            max(1, min(int(limit) * (2 if include_archived else 1), 1000)),
        )
        result = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                if isinstance(payload, dict):
                    result.append(with_activity_type(payload))
            except TypeError, ValueError:
                continue
        return result
