"""Local synchronization state for library and planned workouts."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import RemoteEntityKind
from backend.config import Config
from backend.db import DatabaseManager, planning_store
from backend.db.remote_links import RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import (
    CORRUPT_LIBRARY_ERROR,
    INTERVALS_API_KEY_ERROR,
    INVALID_LIBRARY_ID_ERROR,
    AppError,
)
from backend.observability import Redactor
from backend.planning import library as planning_library
from backend.planning import planned_units
from backend.planning import workouts as planning_workouts
from backend.providers.http import ProviderHTTPError
from backend.sync.workout_export import WorkoutLibraryExportPort

_REMOTE_LINKS = RemoteLinkRepository()
_OPEN_SYNC_STATES = ("local", "sync_error", "remote_missing", "conflict")
_WORKOUT_LIBRARY_SYNC_LOCK = threading.Lock()
_REMOTE_LIBRARY_METADATA_FIELDS = (
    "date",
    "rationale",
    "plan_id",
    "plan_name",
    "source",
    "private_calendar_adjustment",
    "archived",
    "local_marked",
    "local_deleted",
)


@contextmanager
def workout_library_sync_guard() -> Iterator[None]:
    """Serialize operations that share the workout-library sync lock."""
    with _WORKOUT_LIBRARY_SYNC_LOCK:
        yield


def workout_library_sync_running() -> bool:
    """Return whether the shared workout-library lock is held."""
    return _WORKOUT_LIBRARY_SYNC_LOCK.locked()


class WorkoutLibrarySyncStateService:
    """Read and persist local workout-library synchronization state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        redactor: Redactor,
        key_value_repository: KeyValueRepository,
        now: Callable[[], str],
        hr_cap_resync: Callable[[Any, list[dict[str, Any]]], set[str]] = (
            lambda _db, _payloads: set()
        ),
    ):
        self._database_manager = database_manager
        self._redactor = redactor
        self._key_value_repository = key_value_repository
        self._now = now
        # Synced capped units whose bpm range moved with the threshold HR.
        self._hr_cap_resync = hr_cap_resync

    def reset_interrupted(self) -> int:
        """Offer again the units a crash left "syncing"; run before any worker.

        "syncing" is written before the remote call and is no open state, so a
        unit stranded in it would never be offered for a push again.
        """
        with self._database_manager.unit_of_work() as db:
            return planning_store.reset_interrupted_syncs(
                db, self._now(), "Die Übertragung wurde unterbrochen."
            )

    def preview(self) -> tuple[dict[str, int], list[dict[str, Any]], str]:
        with self._database_manager.unit_of_work() as db:
            rows = planning_store.library_rows_in_states(db, _OPEN_SYNC_STATES)
            planned_rows = planning_store.planned_unit_rows_in_states(
                db, _OPEN_SYNC_STATES
            )
            planned_rows = sorted(
                [*planned_rows, *self._resync_planned_rows(db)],
                key=lambda row: str(row.get("local_id") or ""),
            )
            rows = self._with_linked_external_ids(
                db, rows, RemoteEntityKind.LIBRARY_WORKOUT
            )
            planned_rows = self._with_linked_external_ids(
                db, planned_rows, RemoteEntityKind.PLANNED_UNIT
            )
        return self._snapshot(rows, planned_rows)

    def _resync_planned_rows(self, db: Any) -> list[Any]:
        """Synced capped units the calendar offers again after a threshold move."""
        rows = planning_store.synced_capped_planned_unit_rows(db)
        payloads = [
            {**payload, "local_id": row["local_id"], "sync_status": row["sync_state"]}
            for row in rows
            if isinstance(payload := self._parse_payload(row["payload"]), dict)
            # Like the calendar: archived or deleted units are never offered.
            and not payload.get("archived")
            and not payload.get("local_deleted")
        ]
        active = {str(payload["local_id"]) for payload in payloads}
        moved = self._hr_cap_resync(db, payloads) if payloads else set()
        return [
            row
            for row in rows
            if str(row["local_id"]) in moved and str(row["local_id"]) in active
        ]

    @staticmethod
    def _with_linked_external_ids(
        db: Any, rows: list[Any], entity_kind: RemoteEntityKind
    ) -> list[Any]:
        """Resolve each row's external id through its remote link, slot as fallback."""
        return [
            {
                **row,
                "external_id": _REMOTE_LINKS.resolve_remote_external_id(
                    db,
                    entity_kind,
                    str(row.get("local_id") or ""),
                    row.get("external_id"),
                ),
            }
            for row in rows
        ]

    def update(self, local_id: str, state: str, error: str | None = None) -> bool:
        with self._database_manager.unit_of_work() as db:
            row = planning_store.library_row(db, local_id)
            if row is None:
                return False
            payload = self._object_payload(row["payload"])
            payload["sync_status"] = state
            planning_store.set_library_sync_state(
                db,
                local_id,
                payload,
                self._now(),
                state=state,
                dirty=0 if state in {"synced", "remote_missing"} else 1,
                error=self._redactor.redact_text(str(error))[:1000] if error else None,
            )
        return True

    def mark_remote_missing(self, local_id: str) -> None:
        """Record a remote deletion found mid-sync; the local edit stays dirty."""
        with self._database_manager.unit_of_work() as db:
            row = planning_store.library_row(db, local_id)
            if row is None:
                return
            payload = self._object_payload(row["payload"])
            payload["sync_status"] = "remote_missing"
            planning_store.set_library_sync_state(
                db, local_id, payload, self._now(), state="remote_missing", dirty=1
            )

    def summary(self) -> dict[str, int]:
        with self._database_manager.unit_of_work() as db:
            rows, planned_rows = planning_store.sync_state_counts(db)
        summary = {
            "local": 0,
            "syncing": 0,
            "synced": 0,
            "sync_error": 0,
            "remote_missing": 0,
        }
        for row in rows:
            state = str(row.get("sync_state") or "local")
            summary[state] = int(row.get("count") or 0)
        for row in planned_rows:
            state = str(row.get("sync_state") or "local")
            summary[f"planned_{state}"] = int(row.get("count") or 0)
        summary["planned_pending"] = sum(
            summary.get(f"planned_{state}", 0)
            for state in ("local", "sync_error", "remote_missing")
        )
        summary["planned_conflicts"] = summary.get("planned_conflict", 0)
        return summary

    def load_for_sync(
        self, local_id: str
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        try:
            normalized_id = str(uuid.UUID(str(local_id)))
        except (ValueError, AttributeError) as exc:
            raise AppError(400, INVALID_LIBRARY_ID_ERROR) from exc
        with self._database_manager.unit_of_work() as db:
            row = planning_store.library_row(db, normalized_id)
            if row:
                # Prefer the remote link; the legacy slot is the fallback.
                row = {
                    **row,
                    "external_id": _REMOTE_LINKS.resolve_remote_external_id(
                        db,
                        RemoteEntityKind.LIBRARY_WORKOUT,
                        normalized_id,
                        row.get("external_id"),
                    ),
                }
        if not row:
            raise AppError(404, "Lokale Bibliothekseinheit nicht gefunden.")
        try:
            local_workout = json.loads(row["payload"])
        except (TypeError, ValueError) as exc:
            raise AppError(500, CORRUPT_LIBRARY_ERROR) from exc
        return normalized_id, row, local_workout

    @staticmethod
    def _uploaded_payload_is_current(
        current: dict[str, Any] | None, uploaded: dict[str, Any]
    ) -> bool:
        """Return whether the stored row still holds the uploaded payload.

        Keys the sync itself writes (external_id, sync_status) are ignored; any
        other difference means a local edit was committed during the remote call.
        """
        if current is None or not isinstance(uploaded, dict):
            return False
        sync_owned = {"external_id", "sync_status"}
        return {k: v for k, v in current.items() if k not in sync_owned} == {
            k: v for k, v in uploaded.items() if k not in sync_owned
        }

    @staticmethod
    def _persist_remote_identity(
        db: Any,
        local_id: str,
        current: dict[str, Any] | None,
        external_id: str,
    ) -> None:
        """Store only the remote identity on top of the current payload."""
        planning_store.set_library_external_id(
            db, local_id, external_id, {**(current or {}), "external_id": external_id}
        )
        _REMOTE_LINKS.refresh_from_slots(db, RemoteEntityKind.LIBRARY_WORKOUT, local_id)

    def store_remote_identity(
        self,
        local_id: str,
        local_workout: dict[str, Any],
        remote_workout: dict[str, Any],
    ) -> str:
        external_id = str(remote_workout.get("id") or "").strip()
        if not external_id:
            raise AppError(
                502,
                "Die Bibliothekseinheit konnte nicht zu Intervals.icu übertragen werden.",
            )
        with self._database_manager.unit_of_work() as db:
            row = planning_store.library_row(db, local_id)
            current = self._object_payload(row["payload"]) if row else None
            if self._uploaded_payload_is_current(current, local_workout):
                planning_store.set_library_external_id(
                    db,
                    local_id,
                    external_id,
                    {**local_workout, "external_id": external_id},
                )
                _REMOTE_LINKS.refresh_from_slots(
                    db, RemoteEntityKind.LIBRARY_WORKOUT, local_id
                )
            else:
                self._persist_remote_identity(db, local_id, current, external_id)
        return external_id

    def finish(
        self,
        local_id: str,
        external_id: str,
        local_workout: dict[str, Any],
        remote_workout: dict[str, Any],
        *,
        verify_readback: Callable[[dict[str, Any], dict[str, Any]], None],
    ) -> dict[str, Any]:
        verify_readback(local_workout, remote_workout)
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            row = planning_store.library_row(db, local_id)
            if row is None:
                raise AppError(404, "Lokale Bibliothekseinheit nicht gefunden.")
            current = self._object_payload(row["payload"])
            if not self._uploaded_payload_is_current(current, local_workout):
                # A local edit was committed during the remote call. Keep the
                # athlete's newer payload dirty so the next explicit sync uploads it.
                self._persist_remote_identity(db, local_id, current, external_id)
                return planning_library.normalize_library_workout(
                    {**current, "external_id": external_id},
                    local_id=local_id,
                    external_id=external_id,
                    sync_status=str(row["sync_state"] or "local"),
                )
            synced = planning_library.normalize_library_workout(
                {**local_workout, **remote_workout},
                local_id=local_id,
                external_id=external_id,
                sync_status="synced",
            )
            planning_store.mark_library_synced(db, local_id, external_id, synced, now)
            _REMOTE_LINKS.refresh_from_slots(
                db, RemoteEntityKind.LIBRARY_WORKOUT, local_id
            )
            self._key_value_repository.set(db, "last_library_push_at", now)
            self._key_value_repository.set(db, "last_library_sync_error", "")
        return synced

    def persist_calendar_identity(self, local_id: str, event: dict[str, Any]) -> bool:
        with self._database_manager.unit_of_work() as db:
            row = planning_store.library_row(db, local_id)
            if row is None:
                return False
            payload = self._parse_payload(row["payload"])
            if not isinstance(payload, dict):
                return False
            payload["remote_event_id"] = str(event["id"])
            external_id = str(event.get("external_id") or "").strip()
            if external_id:
                payload["remote_event_external_id"] = external_id
            planning_store.set_library_payload(db, local_id, payload, self._now())
            _REMOTE_LINKS.refresh_from_slots(
                db, RemoteEntityKind.LIBRARY_WORKOUT, local_id
            )
        return True

    @staticmethod
    def _parse_payload(raw_payload: Any) -> Any:
        try:
            return json.loads(raw_payload or "{}")
        except TypeError, ValueError:
            return {}

    @classmethod
    def _object_payload(cls, raw_payload: Any) -> dict[str, Any]:
        payload = cls._parse_payload(raw_payload)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _category(state: str, is_planned: bool, has_remote_id: bool) -> str:
        if state == "conflict":
            return "conflict"
        if state == "remote_missing":
            return "missing"
        if is_planned:
            return "planned"
        if state == "sync_error":
            return "error_retry"
        return "changed" if has_remote_id else "new"

    @classmethod
    def _entry(
        cls, row: Any, planned_local_ids: set[str]
    ) -> tuple[str, bool, dict[str, Any]]:
        state = str(row.get("sync_state") or "local")
        raw_payload = str(row.get("payload") or "")
        payload_data = cls._parse_payload(raw_payload)
        planned_date = (
            iso_date_prefix(str(payload_data.get("date") or "").strip())
            if isinstance(payload_data, dict)
            else ""
        )
        local_id = str(row.get("local_id") or "")
        is_planned = local_id in planned_local_ids
        has_remote_id = bool(row.get("external_id"))
        category = cls._category(state, is_planned, has_remote_id)
        return (
            category,
            is_planned,
            {
                "local_id": local_id,
                "status": state,
                "category": category,
                "has_remote_id": has_remote_id,
                "planned_date": planned_date or None,
                "syncs_calendar": is_planned,
                "entity": "planned_unit" if is_planned else "workout_library",
                "payload_hash": planned_units.plan_push_payload_hash(raw_payload),
            },
        )

    @classmethod
    def _snapshot(
        cls, rows: list[Any], planned_rows: list[Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]], str]:
        summary = {
            "new": 0,
            "changed": 0,
            "missing": 0,
            "error_retry": 0,
            "planned": 0,
            "conflict": 0,
        }
        entries: list[dict[str, Any]] = []
        planned_local_ids = {str(row.get("local_id") or "") for row in planned_rows}
        for row in [*rows, *planned_rows]:
            category, is_planned, entry = cls._entry(row, planned_local_ids)
            if is_planned:
                summary["planned"] += 1
            if category != "planned":
                summary[category] += 1
            entries.append(entry)
        fingerprint = hashlib.sha256(
            json.dumps(
                {"summary": summary, "entries": entries},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return summary, entries, fingerprint


class WorkoutLibrarySyncService:
    """Explicitly sync one local workout-library entry with Intervals.icu."""

    def __init__(
        self,
        config: Config,
        export: WorkoutLibraryExportPort,
        state_service: WorkoutLibrarySyncStateService,
        calendar_conflict_service: Any | None = None,
        *,
        local_today: Callable[[], date] | None = None,
        _lock: Any | None = None,
    ):
        self._config = config
        self._export = export
        self._local_today = local_today
        self._state_service = state_service
        self._calendar_conflict_service = calendar_conflict_service
        self._lock = _lock if _lock is not None else _WORKOUT_LIBRARY_SYNC_LOCK

    def plan_remote(
        self, workout_id: str, workout: dict[str, Any], plan_date: str
    ) -> dict[str, Any]:
        event = self._export.library_plan(
            workout_id,
            workout,
            plan_date,
            today=self._local_today() if self._local_today is not None else None,
        )
        self._export.verify_library_readback(workout, event)
        return event

    def sync_calendar_entry(
        self, local_id: str, synced: dict[str, Any]
    ) -> dict[str, Any] | None:
        planned_date = iso_date_prefix(str(synced.get("date") or "").strip())
        if not planned_date:
            return None
        if self._calendar_conflict_service is not None:
            blockers = self._calendar_conflict_service.constraints(synced)
            if blockers:
                marker = str(blockers[0].get("constraint") or "calendar constraint")
                raise AppError(
                    409,
                    f"Die Einheit kann wegen {marker} nicht mit Intervals.icu synchronisiert werden.",
                    reason="plan_date_conflict",
                )
        external_id = str(synced.get("external_id") or "").strip()
        if not external_id:
            raise AppError(502, "Die geplante Bibliothekseinheit hat keine externe ID.")
        event = self.plan_remote(external_id, synced, planned_date)
        if not isinstance(event, dict) or not str(event.get("id") or "").strip():
            raise AppError(
                502,
                "Intervals.icu hat keine geplante Bibliothekseinheit zurückgegeben.",
            )
        self._state_service.persist_calendar_identity(local_id, event)
        return event

    def sync_entry(self, local_id: str) -> dict[str, Any]:
        try:
            normalized_id = str(uuid.UUID(str(local_id)))
        except (ValueError, AttributeError) as exc:
            raise AppError(400, INVALID_LIBRARY_ID_ERROR) from exc
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR, reason="not_configured")
        with self._lock:
            try:
                return self._sync_entry_unlocked(normalized_id)
            except Exception as exc:
                self._state_service.update(normalized_id, "sync_error", str(exc))
                raise

    def _sync_entry_unlocked(self, local_id: str) -> dict[str, Any]:
        normalized_id, row, local_workout = self._state_service.load_for_sync(local_id)
        if row.get("external_id") and row.get("sync_state") == "synced":
            return local_workout
        planning_workouts.validate_workout_description(local_workout)
        self._state_service.update(normalized_id, "syncing")
        remote_workout = self._upsert_remote(row, local_workout)
        external_id = self._state_service.store_remote_identity(
            normalized_id, local_workout, remote_workout or {}
        )
        return self._state_service.finish(
            normalized_id,
            external_id,
            local_workout,
            remote_workout or {},
            verify_readback=self._export.verify_library_readback,
        )

    def _upsert_remote(
        self, row: dict[str, Any], local_workout: dict[str, Any]
    ) -> dict[str, Any] | None:
        external_id = str(row.get("external_id") or "")
        payload = self._export.serialize_library(local_workout)
        if external_id and row.get("sync_state") != "remote_missing":
            try:
                updated = self._export.library_update(external_id, payload)
            except (AppError, ProviderHTTPError) as exc:
                status = (
                    exc.upstream_status if isinstance(exc, AppError) else exc.status
                )
                if status != 404:
                    raise
                # Deleted in Intervals.icu: this athlete-named sync re-creates it.
                self._state_service.mark_remote_missing(str(row["local_id"]))
            else:
                return {**updated, "id": external_id}
        remote_workouts = self._export.library_list()
        recovered = next(
            (
                item
                for item in remote_workouts
                if planning_library.library_workout_matches(local_workout, item)
            ),
            None,
        )
        if recovered is not None:
            return recovered
        created = self._export.library_create([payload])
        return created[0] if created and isinstance(created[0], dict) else None
