"""Transactional local planned-unit creation and listing use cases."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend import change_history
from backend.calendar.canonical import canonical_planned_workouts
from backend.errors import CORRUPT_PLANNING_ERROR, AppError
from backend.planning import planned_units, workouts
from backend.planning.repository import planned_unit_payload, planned_unit_rows

UPDATE_SQL = (
    "UPDATE planned_units SET payload=?, sync_dirty=1, sync_state='local', "
    "sync_error=NULL, sync_conflict='', updated_at=? WHERE local_id=?"
)


class PlannedUnitService:
    """Own local planned-unit persistence, mutation, and transaction orchestration."""

    def __init__(
        self,
        database_manager: Any,
        planning_revision_service: Any,
        now: Callable[[], str],
        today: Callable[[], date],
        id_factory: Callable[[], Any],
        redact: Callable[[str], str],
        calendar_conflict_service: Any,
        publish_change: Callable[[], None],
    ):
        self._database_manager = database_manager
        self._planning_revision_service = planning_revision_service
        self._now = now
        self._today = today
        self._id_factory = id_factory
        self._redact = redact
        self._calendar_conflict_service = calendar_conflict_service
        self._publish_change = publish_change

    def insert(
        self,
        db: Any,
        entry: dict[str, Any],
        *,
        sync_dirty: int = 1,
        sync_state: str = "local",
        sync_error: str | None = None,
        baseline_hash: str | None = None,
        last_synced_at: str | None = None,
    ) -> dict[str, Any]:
        """Insert one planned unit on the caller-owned transaction."""
        now = self._now()
        stored = {**entry, "sync_status": sync_state}
        db.execute(
            "INSERT INTO planned_units(id, local_id, external_id, payload, sync_dirty, sync_state, sync_error, sync_conflict, baseline_hash, last_synced_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stored["id"],
                stored["id"],
                stored.get("external_id"),
                json.dumps(stored, ensure_ascii=False),
                int(sync_dirty),
                sync_state,
                self._redact(str(sync_error))[:1000] if sync_error else None,
                json.dumps(stored.get("sync_conflict"), ensure_ascii=False)
                if stored.get("sync_conflict")
                else "",
                baseline_hash,
                last_synced_at,
                now,
                now,
            ),
        )
        return stored

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
        history_action: str,
    ) -> dict[str, Any] | None:
        """Restore one audited local state inside the caller-owned transaction."""
        if target is None:
            db.execute("DELETE FROM planned_units WHERE local_id=?", (entity_id,))
            return None
        if current is None:
            restore_date = str(target.get("date") or "")[:10]
            self._reject_restore_conflict(entity_id, restore_date)
            restored = planned_units.normalize_planned_unit(
                target, local_id=entity_id, sync_status="local"
            )
            return self.insert(db, restored)
        return self._restore_existing_in_transaction(
            db, entity_id, current, target, history_action
        )

    def _restore_existing_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any],
        target: dict[str, Any],
        history_action: str,
    ) -> dict[str, Any]:
        try:
            current_payload = json.loads(current.get("payload") or "{}")
        except (TypeError, ValueError) as exc:
            raise AppError(
                409, "Die lokale Planung kann nicht wiederhergestellt werden."
            ) from exc
        if not isinstance(current_payload, dict):
            raise AppError(
                409, "Die lokale Planung kann nicht wiederhergestellt werden."
            )

        restore_date = str(target.get("date") or current_payload.get("date") or "")[:10]
        current_date = str(current_payload.get("date") or "")[:10]
        archived, local_deleted, restored_from_hidden = (
            self._restore_visibility_state(current_payload, target, history_action)
        )
        if restore_date != current_date or restored_from_hidden:
            self._reject_restore_conflict(entity_id, restore_date)

        restored_target = dict(target)
        if restore_date:
            previous_start = str(current_payload.get("start_date_local") or "")
            suffix = (
                previous_start[10:]
                if len(previous_start) > 10 and previous_start[10] == "T"
                else "T00:00:00"
            )
            restored_target["start_date_local"] = restore_date + suffix
        restored = planned_units.normalize_planned_unit(
            {
                **current_payload,
                **restored_target,
                "archived": archived,
                "local_deleted": local_deleted,
            },
            local_id=entity_id,
            external_id=str(
                current.get("external_id") or current_payload.get("external_id") or ""
            )
            or None,
            sync_status="local",
        )
        db.execute(
            UPDATE_SQL,
            (json.dumps(restored, ensure_ascii=False), self._now(), entity_id),
        )
        return restored

    @staticmethod
    def _restore_visibility_state(
        current_payload: dict[str, Any],
        target: dict[str, Any],
        history_action: str,
    ) -> tuple[bool, bool, bool]:
        restoring_deletion = history_action == "delete"
        archived = (
            bool(target["archived"])
            if "archived" in target
            else not restoring_deletion and bool(current_payload.get("archived"))
        )
        local_deleted = (
            bool(target["local_deleted"])
            if "local_deleted" in target
            else not restoring_deletion and bool(current_payload.get("local_deleted"))
        )
        restored_from_hidden = (
            (
                bool(current_payload.get("archived"))
                or bool(current_payload.get("local_deleted"))
            )
            and not archived
            and not local_deleted
        )
        return archived, local_deleted, restored_from_hidden

    def _reject_restore_conflict(self, entity_id: str, restore_date: str) -> None:
        if restore_date and self._calendar_conflict_service.conflicts(
            {"date": restore_date}, {entity_id}
        ):
            raise AppError(
                409,
                "Die lokale Einheit kann wegen einer bestehenden Kalendereinheit nicht wiederhergestellt werden.",
                reason="plan_date_conflict",
            )

    def create(
        self,
        workout: dict[str, Any],
        db: Any = None,
        *,
        bump_planning_revision: bool = True,
        change_source: str = "local",
    ) -> dict[str, Any]:
        local_id = str(self._id_factory())
        entry = planned_units.normalize_planned_unit(
            workout, local_id=local_id, external_id=None, sync_status="local"
        )
        workouts.validate_workout_description(entry)

        def persist(connection: Any) -> None:
            self.insert(connection, entry)
            change_history.record_change(
                connection,
                "planned_unit",
                local_id,
                "create",
                None,
                entry,
                source=change_source,
            )
            if bump_planning_revision:
                self._planning_revision_service.bump(connection)

        if db is not None:
            persist(db)
        else:
            with self._database_manager.unit_of_work() as own_db:
                persist(own_db)
        return entry

    def list(
        self,
        limit: int = 500,
        include_archived: bool = False,
        *,
        future_only: bool = False,
    ) -> list[dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
            rows = planned_unit_rows(
                db,
                limit,
                include_archived,
                future_only,
                today=self._today(),
            )
        return [
            payload
            for row in rows
            if (payload := planned_unit_payload(row, include_archived)) is not None
        ]

    def list_for_coach(self, limit: int = 250) -> dict[str, Any]:
        """Return the future local planned units in the Coach calendar shape."""
        local = self.list(limit, future_only=True)
        return {
            "local": local,
            "intervals": [],
            "canonical": canonical_planned_workouts([], local, limit),
            "source": "local",
        }

    def resolve_conflict(self, local_id: Any, strategy: Any) -> dict[str, Any]:
        """Resolve a stored planned-unit sync conflict using only local state."""
        normalized_id, selected = planned_units.planned_conflict_resolution_request(
            local_id, strategy
        )
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (normalized_id,)
            ).fetchone()
            if (
                not row
                or str(row.get("sync_state") or "") != "conflict"
                or not row.get("sync_conflict")
            ):
                raise AppError(
                    409,
                    "Für diese Planung liegt kein offener Synchronisierungskonflikt vor.",
                )
            try:
                conflict = json.loads(row["sync_conflict"] or "{}")
            except (TypeError, ValueError) as exc:
                raise AppError(
                    409,
                    "Der gespeicherte Synchronisierungskonflikt ist nicht mehr gültig.",
                ) from exc
            if not isinstance(conflict, dict):
                conflict = {}

            if selected == "keep_local":
                payload = planned_units.planned_conflict_payload(row)
                payload["sync_status"] = "local"
                db.execute(
                    UPDATE_SQL,
                    (json.dumps(payload, ensure_ascii=False), now, normalized_id),
                )
            else:
                remote = conflict.get("remote")
                if not isinstance(remote, dict):
                    # An accepted provider deletion remains as a tombstone so a
                    # later sync cannot recreate the explicitly deleted unit.
                    payload = planned_units.planned_conflict_payload(row)
                    payload.update(
                        local_deleted=True,
                        archived=True,
                        sync_status="remote_deleted",
                    )
                    db.execute(
                        "UPDATE planned_units SET payload=?, sync_dirty=0, "
                        "sync_state='remote_deleted', sync_error=NULL, "
                        "sync_conflict='', updated_at=? WHERE local_id=?",
                        (json.dumps(payload, ensure_ascii=False), now, normalized_id),
                    )
                else:
                    prepared = planned_units.remote_planned_unit_payload(
                        remote, today=self._today()
                    )
                    if not prepared:
                        raise AppError(
                            409, "Das Remote-Event kann nicht übernommen werden."
                        )
                    incoming, _, identity = prepared
                    incoming.update(id=normalized_id, sync_status="synced")
                    baseline_hash = planned_units.planned_unit_payload_hash(incoming)
                    db.execute(
                        "UPDATE planned_units SET external_id=?, payload=?, "
                        "sync_dirty=0, sync_state='synced', sync_error=NULL, "
                        "sync_conflict='', baseline_hash=?, last_synced_at=?, "
                        "updated_at=? WHERE local_id=?",
                        (
                            identity,
                            json.dumps(incoming, ensure_ascii=False),
                            baseline_hash,
                            now,
                            now,
                            normalized_id,
                        ),
                    )
            self._planning_revision_service.bump(db)

        saved = next(
            (
                item
                for item in self.list(1000, include_archived=True)
                if item.get("id") == normalized_id
            ),
            None,
        )
        return {"status": "resolved", "strategy": selected, "planned_unit": saved}

    def _load_for_update(
        self, db: Any, normalized_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        row = db.execute(
            "SELECT payload, external_id, sync_state FROM planned_units WHERE local_id = ?",
            (normalized_id,),
        ).fetchone()
        if not row:
            raise AppError(404, "Lokale Planung nicht gefunden.")
        try:
            current = json.loads(row["payload"])
        except (TypeError, ValueError) as exc:
            raise AppError(500, CORRUPT_PLANNING_ERROR) from exc
        if not isinstance(current, dict) or not current.get("date"):
            raise AppError(
                403, "Nur lokale geplante Einheiten können bearbeitet werden."
            )
        before = {
            **current,
            "sync_status": row.get("sync_state") or current.get("sync_status"),
        }
        return row, current, before

    def _save_update(
        self,
        db: Any,
        normalized_id: str,
        normalized: dict[str, Any],
        before: dict[str, Any],
        *,
        bump_planning_revision: bool,
    ) -> None:
        db.execute(
            UPDATE_SQL,
            (json.dumps(normalized, ensure_ascii=False), self._now(), normalized_id),
        )
        change_history.record_change(
            db,
            "planned_unit",
            normalized_id,
            "update",
            before,
            {**normalized, "sync_status": "local"},
        )
        if bump_planning_revision:
            self._planning_revision_service.bump(db)

    def _update_in_db(
        self,
        db: Any,
        local_id: str,
        values: Any,
        *,
        skip_calendar_conflict: bool,
        bump_planning_revision: bool,
    ) -> dict[str, Any]:
        normalized_id, values, action = planned_units.planned_workout_update_request(
            local_id, values
        )
        row, current, before = self._load_for_update(db, normalized_id)
        if action == "delete":
            deleted = {
                **current,
                "local_deleted": True,
                "archived": True,
                "sync_status": "local",
            }
            db.execute(
                "UPDATE planned_units SET payload=?, sync_state='local', sync_dirty=1, "
                "sync_conflict='', updated_at=? WHERE local_id = ?",
                (json.dumps(deleted, ensure_ascii=False), self._now(), normalized_id),
            )
            change_history.record_change(
                db, "planned_unit", normalized_id, "delete", before, deleted
            )
            if bump_planning_revision:
                self._planning_revision_service.bump(db)
            return {"status": "deleted", "local_id": normalized_id}

        candidate = planned_units.planned_workout_update_candidate(
            current, action, values
        )
        date_changed = planned_units.prepare_planned_workout_date(candidate, current)
        if not skip_calendar_conflict and date_changed:
            conflicts = self._calendar_conflict_service.conflicts(
                {"date": candidate["date"][:10]}, {normalized_id}
            )
            if conflicts:
                raise AppError(
                    409,
                    "Die lokale Einheit kann wegen einer bestehenden Kalendereinheit nicht verschoben werden.",
                )
        updated = planned_units.normalized_planned_workout_update(
            candidate, current, row, normalized_id, action, values
        )
        self._save_update(
            db,
            normalized_id,
            updated,
            before,
            bump_planning_revision=bump_planning_revision,
        )
        return {
            "status": "local",
            "local_id": normalized_id,
            "library_entry": updated,
        }

    def update(
        self,
        local_id: str,
        values: Any,
        *,
        skip_calendar_conflict: bool = False,
        bump_planning_revision: bool = True,
        db: Any = None,
    ) -> dict[str, Any]:
        """Edit or tombstone a dated local plan without writing to a provider."""
        if db is not None:
            return self._update_in_db(
                db,
                local_id,
                values,
                skip_calendar_conflict=skip_calendar_conflict,
                bump_planning_revision=bump_planning_revision,
            )
        with self._database_manager.unit_of_work() as own_db:
            result = self._update_in_db(
                own_db,
                local_id,
                values,
                skip_calendar_conflict=skip_calendar_conflict,
                bump_planning_revision=bump_planning_revision,
            )
        self._publish_change()
        return result
