"""Transactional local planned-unit creation and listing use cases."""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend import change_history
from backend.activities.hr_cap import stored_cap
from backend.athlete.local_date import LocalDate
from backend.calendar.canonical import canonical_planned_workouts
from backend.canonical.planning_fields import (
    FOCUS_ONLY_KEYS,
    HR_CAP,
    STRENGTH_STRUCTURE,
)
from backend.canonical.planning_fields import SESSION_FOCUS_KEYS as FOCUS_KEYS
from backend.canonical.vocabulary import ProviderId, RemoteEntityKind
from backend.db.remote_links import RemoteLinkRepository
from backend.errors import CORRUPT_PLANNING_ERROR, AppError
from backend.planning import calendar as planning_calendar
from backend.planning import planned_units, workouts
from backend.planning.conflicts import calendar_item_window
from backend.planning.exercise_mappings import remembered_exercises
from backend.planning.garmin_orphans import find_orphans
from backend.planning.intervals_orphans import find_intervals_orphans
from backend.planning.push_state import attach_push_state, garmin_baselines
from backend.planning.repository import (
    planned_unit_payload,
    planned_unit_rows,
    planned_unit_rows_between,
)
from backend.planning.wahoo_orphans import find_wahoo_orphans

_REMOTE_LINKS = RemoteLinkRepository()
UPDATE_SQL = (
    "UPDATE planned_units SET payload=?, sync_dirty=1, sync_state='local', "
    "sync_error=NULL, sync_conflict='', updated_at=? WHERE local_id=?"
)


# A focus-only edit changes nothing the provider holds, so sync state stays.
FOCUS_UPDATE_SQL = "UPDATE planned_units SET payload=?, updated_at=? WHERE local_id=?"


def _is_focus_only(values: dict[str, Any]) -> bool:
    return set(values) - {"action"} <= set(FOCUS_ONLY_KEYS) and bool(
        set(values) & set(FOCUS_ONLY_KEYS)
    )


def _without_unset_focus(
    current: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    """Current payload minus focus keys the audited target does not name."""
    return {
        key: value
        for key, value in current.items()
        if key not in FOCUS_KEYS or key in target
    }


def _differs_only_in_focus(restored: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether an undo changes nothing but the local focus (sync state stays).

    A focus that changes the effective heart-rate cap changes the exported text.
    """
    if stored_cap(restored) != stored_cap(current):
        return False
    ignored = {*(key for key in FOCUS_KEYS if key != HR_CAP), "sync_status"}

    def comparable(payload: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in payload.items() if key not in ignored}
        # An unset start reads as local midnight of the date.
        if result.get("starts_at_local") in (None, f"{result.get('date')}T00:00:00"):
            result.pop("starts_at_local", None)
        return result

    return comparable(restored) == comparable(current)


def _start_time_suffix(start: str) -> str | None:
    """Return the time part of a local start such as 2026-09-21T07:15:00."""
    return start[10:] if len(start) > 10 and start[10] == "T" else None


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
        hr_cap_resync: Callable[[Any, list[dict[str, Any]]], set[str]] = (
            lambda _db, _payloads: set()
        ),
    ):
        self._database_manager = database_manager
        self._planning_revision_service = planning_revision_service
        self._now = now
        self._today = today
        self._id_factory = id_factory
        self._redact = redact
        self._calendar_conflict_service = calendar_conflict_service
        self._publish_change = publish_change
        self._hr_cap_resync = hr_cap_resync

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
        _REMOTE_LINKS.refresh_from_slots(
            db, RemoteEntityKind.PLANNED_UNIT, str(stored["id"])
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
            if hidden := self._hide_intervals_linked(db, entity_id, current):
                return hidden
            db.execute("DELETE FROM planned_units WHERE local_id=?", (entity_id,))
            # A pushed Garmin workout stays removable by its link.
            _REMOTE_LINKS.delete_for_entity(
                db,
                RemoteEntityKind.PLANNED_UNIT,
                entity_id,
                keep=(ProviderId.GARMIN.value,),
            )
            return None
        if current is None:
            self._reject_restore_conflict(entity_id, target)
            restored = planned_units.normalize_planned_unit(
                target, local_id=entity_id, sync_status="local"
            )
            return self.insert(db, restored)
        return self._restore_existing_in_transaction(
            db, entity_id, current, target, history_action
        )

    def _hide_intervals_linked(
        self, db: Any, entity_id: str, current: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Hide an undone creation that already has an Intervals.icu event.

        The hidden unit keeps its links, so the leftover listing and the next
        "Woche synchronisieren" remove the event by its id (#2135, D-533).
        """
        if current is None:
            return None
        try:
            payload = json.loads(current.get("payload") or "{}")
        except TypeError, ValueError:
            return None
        remote_id = _REMOTE_LINKS.resolve_remote_id(
            db,
            RemoteEntityKind.PLANNED_UNIT,
            entity_id,
            payload.get("remote_event_id") if isinstance(payload, dict) else None,
        )
        if not isinstance(payload, dict) or not remote_id:
            return None
        hidden = {
            **payload,
            "remote_event_id": remote_id,
            "local_deleted": True,
            "archived": True,
            "sync_status": "local",
        }
        db.execute(
            "UPDATE planned_units SET payload=?, sync_state='local', sync_dirty=1, "
            "sync_conflict='', updated_at=? WHERE local_id = ?",
            (json.dumps(hidden, ensure_ascii=False), self._now(), entity_id),
        )
        return hidden

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

        restore_date = LocalDate.parse(
            target.get("date") or current_payload.get("date")
        ).isoformat()
        current_date = LocalDate.parse(current_payload.get("date")).isoformat()
        archived, local_deleted, restored_from_hidden = self._restore_visibility_state(
            current_payload, target, history_action
        )
        restored_target = dict(target)
        if restore_date:
            suffix = (
                _start_time_suffix(str(target.get("starts_at_local") or ""))
                or _start_time_suffix(str(current_payload.get("starts_at_local") or ""))
                or "T00:00:00"
            )
            restored_target["starts_at_local"] = restore_date + suffix
        window_changed = any(
            key in restored_target and restored_target[key] != current_payload.get(key)
            for key in ("starts_at_local", "duration_minutes", "planned_duration_s")
        )
        if restore_date != current_date or window_changed or restored_from_hidden:
            self._reject_restore_conflict(
                entity_id, {**current_payload, **restored_target}
            )
        kept = _without_unset_focus(current_payload, target)
        restored = planned_units.normalize_planned_unit(
            {
                **kept,
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
        focus_only = _differs_only_in_focus(restored, current_payload)
        if focus_only:
            restored["sync_status"] = current_payload.get("sync_status")
        db.execute(
            FOCUS_UPDATE_SQL if focus_only else UPDATE_SQL,
            (json.dumps(restored, ensure_ascii=False), self._now(), entity_id),
        )
        _REMOTE_LINKS.refresh_from_slots(db, RemoteEntityKind.PLANNED_UNIT, entity_id)
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

    def _reject_restore_conflict(self, entity_id: str, workout_or_date: Any) -> None:
        workout = (
            workout_or_date
            if isinstance(workout_or_date, dict)
            else {"date": str(workout_or_date or "")}
        )
        try:
            restore_date = LocalDate.parse(workout.get("date")).isoformat()
        except TypeError, ValueError:
            restore_date = ""
        if (
            restore_date
            and not workout.get("archived")
            and not workout.get("local_deleted")
            and hasattr(self._calendar_conflict_service, "constraints")
            and self._calendar_conflict_service.constraints(workout)
        ):
            raise AppError(
                409,
                "Die lokale Einheit kann wegen einer aktuellen Kalenderbeschränkung nicht wiederhergestellt werden.",
                reason="plan_date_conflict",
            )
        if restore_date and self._calendar_conflict_service.conflicts(
            workout, {entity_id}
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
            if (
                not entry.get("archived")
                and not entry.get("local_deleted")
                and hasattr(self._calendar_conflict_service, "constraints")
            ):
                conflicts = self._calendar_conflict_service.constraints(entry)
                if conflicts:
                    raise AppError(
                        409,
                        planning_calendar.marker_conflict_message(
                            entry.get("date"), conflicts
                        ),
                        reason="plan_date_conflict",
                    )
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
        since: date | None = None,
        push_state: bool = False,
    ) -> list[dict[str, Any]]:
        """Return planned units; ``push_state`` adds the calendar sync-button state."""
        with self._database_manager.reader() as db:
            rows = planned_unit_rows(
                db,
                limit,
                include_archived,
                future_only,
                today=self._today(),
                since=since,
            )
            baselines = garmin_baselines(db) if push_state else {}
            remembered = remembered_exercises(db) if push_state else {}
            orphans = find_orphans(db, self._today())[0] if push_state else []
            intervals_orphans = (
                find_intervals_orphans(db, self._today())[0] if push_state else []
            )
            wahoo_orphans = find_wahoo_orphans(db)[0] if push_state else []
            pairs = [
                (row, payload)
                for row in rows
                if (payload := planned_unit_payload(row, include_archived)) is not None
            ]
            resync = (
                self._hr_cap_resync(db, [payload for _row, payload in pairs])
                if push_state
                else set()
            )
        if push_state:
            attach_push_state(
                pairs,
                baselines,
                remembered,
                resync,
                orphans,
                intervals_orphans,
                self._today(),
                wahoo_orphans,
            )
        return [payload for _row, payload in pairs]

    def list_between(self, start: date, end: date) -> builtins.list[dict[str, Any]]:
        """Return the unarchived planned units from ``start`` to ``end`` inclusive."""
        with self._database_manager.reader() as db:
            rows = planned_unit_rows_between(db, start, end)
        return [
            payload for row in rows if (payload := planned_unit_payload(row, False))
        ]

    def list_for_coach(self, limit: int = 250) -> dict[str, Any]:
        """Return the future local planned units in the Coach calendar shape."""
        local = self.list(limit, future_only=True)
        return {
            "local": local,
            ProviderId.INTERVALS.value: [],
            "canonical": canonical_planned_workouts(local, limit),
            "source": "local",
        }

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
        focus_only: bool = False,
    ) -> None:
        if focus_only:
            normalized["sync_status"] = before.get("sync_status")
        db.execute(
            FOCUS_UPDATE_SQL if focus_only else UPDATE_SQL,
            (json.dumps(normalized, ensure_ascii=False), self._now(), normalized_id),
        )
        _REMOTE_LINKS.refresh_from_slots(
            db, RemoteEntityKind.PLANNED_UNIT, normalized_id
        )
        change_history.record_change(
            db,
            "planned_unit",
            normalized_id,
            "update",
            before,
            {**normalized, "sync_status": "local"}
            if not focus_only
            else dict(normalized),
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
        remote_neutral: bool = False,
    ) -> dict[str, Any]:
        """Apply one update; ``remote_neutral`` keeps the provider sync state.

        A remote-neutral change (focus only, or a Garmin exercise pick that the
        Intervals.icu description never carries) leaves the sync state as is.
        """
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
        date_changed = planned_units.prepare_planned_workout_date(
            candidate, current, today=self._today()
        )
        window_changed = calendar_item_window(candidate) != calendar_item_window(
            current
        )
        is_active = not candidate.get("archived") and not candidate.get("local_deleted")
        marker_conflicts = (
            self._calendar_conflict_service.constraints(candidate)
            if is_active and hasattr(self._calendar_conflict_service, "constraints")
            else []
        )
        if marker_conflicts:
            raise AppError(
                409,
                planning_calendar.marker_conflict_message(
                    candidate.get("date"), marker_conflicts
                ),
                reason="plan_date_conflict",
            )
        if (
            is_active
            and not skip_calendar_conflict
            and (date_changed or window_changed)
        ):
            conflicts = self._calendar_conflict_service.conflicts(
                candidate, {normalized_id}
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
            focus_only=action == "update"
            and (remote_neutral or _is_focus_only(values))
            # A focus that turns the exported heart-rate cap on or off, or
            # changes it, is a content change the provider must be offered.
            and stored_cap(updated) == stored_cap(current),
        )
        return {
            "status": "local",
            "local_id": normalized_id,
            "library_entry": updated,
        }

    def assign_garmin_exercise(
        self, local_id: str, index: Any, garmin_exercise: Any, expected_hash: Any
    ) -> dict[str, Any]:
        """Name the Garmin catalogue exercise of one structure exercise.

        The athlete's pick is stored like a Coach ``garmin_exercise`` (checked
        against the catalogue, pair derived), so it is remembered for the same
        exercise name in other units. It keeps the Intervals.icu sync state,
        whose content it does not change. A unit changed since the browser read
        it is refused.
        """
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT payload, sync_state FROM planned_units "
                "WHERE local_id=? AND tombstone=0",
                (str(local_id),),
            ).fetchone()
            if row is None:
                raise AppError(404, "Einheit nicht gefunden.")
            if not planned_units.plan_push_hash_matches(row["payload"], expected_hash):
                raise AppError(
                    409,
                    "Die Einheit wurde inzwischen geändert.",
                    reason="planning_revision_conflict",
                )
            structure = json.loads(row["payload"] or "{}").get(STRENGTH_STRUCTURE)
            if (
                not isinstance(structure, list)
                or not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(structure)
            ):
                raise AppError(
                    400, "Unbekannte Übung.", reason="invalid_exercise_index"
                )
            exercises = [dict(item) for item in structure]
            exercises[index].pop("garmin_pair", None)
            exercises[index]["garmin_exercise"] = garmin_exercise
            result = self._update_in_db(
                db,
                local_id,
                {STRENGTH_STRUCTURE: exercises},
                skip_calendar_conflict=True,
                bump_planning_revision=True,
                remote_neutral=True,
            )
        self._publish_change()
        return result

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
