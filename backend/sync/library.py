"""Local synchronization state for library and planned workouts."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import (
    COACH_ABORTED_ERROR,
    CORRUPT_LIBRARY_ERROR,
    INTERVALS_API_KEY_ERROR,
    INVALID_LIBRARY_ID_ERROR,
    AppError,
)
from backend.observability import Redactor
from backend.planning import library as planning_library
from backend.planning import workouts as planning_workouts
from backend.planning.library_service import WorkoutLibraryService
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import maintenance_operation
from backend.sync.gates import intervals_operation

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


class WorkoutLibraryRemoteReconciler:
    """Merge an already-read remote workout library into local storage."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        now: Callable[[], str],
        new_id: Callable[[], uuid.UUID | str],
    ):
        self._database_manager = database_manager
        self._now = now
        self._new_id = new_id

    def reconcile(
        self, workouts: list[dict[str, Any]], remove_missing: bool = False
    ) -> list[dict[str, Any]]:
        """Atomically merge remote entries and optionally mark absent remote rows."""
        normalized: list[dict[str, Any]] = []
        seen_external_ids: set[str] = set()
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            for workout in workouts:
                external_id = str(
                    workout.get("id") or workout.get("external_id") or ""
                ).strip()
                if not external_id:
                    continue
                seen_external_ids.add(external_id)
                existing = db.execute(
                    "SELECT id, local_id, sync_dirty, sync_state, payload "
                    "FROM workout_library WHERE external_id = ?",
                    (external_id,),
                ).fetchone()
                local_id = (
                    str(
                        existing.get("local_id") or existing.get("id") or self._new_id()
                    )
                    if existing
                    else str(self._new_id())
                )
                preserved = self._preserved_dirty_library_workout(
                    existing, local_id, external_id
                )
                normalized.append(
                    preserved
                    or self._persist_remote_library_workout_entry(
                        db, workout, existing, local_id, external_id, now
                    )
                )
            if remove_missing:
                self._mark_missing_remote_library_workouts(db, seen_external_ids, now)
        return normalized

    @staticmethod
    def _object_payload(raw_payload: Any) -> dict[str, Any]:
        try:
            payload = json.loads(raw_payload or "{}")
        except (TypeError, ValueError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _preserved_dirty_library_workout(
        cls, existing: dict[str, Any] | None, local_id: str, external_id: str
    ) -> dict[str, Any] | None:
        if (
            not existing
            or not int(existing.get("sync_dirty") or 0)
            or existing.get("sync_state") not in {"local", "sync_error"}
        ):
            return None
        try:
            local_payload = json.loads(existing.get("payload") or "{}")
        except (TypeError, ValueError):
            local_payload = {}
        if not isinstance(local_payload, dict):
            return None
        return planning_library.normalize_library_workout(
            local_payload,
            local_id=local_id,
            external_id=external_id,
            sync_status=str(existing.get("sync_state") or "local"),
        )

    @classmethod
    def _preserve_remote_library_metadata(
        cls, entry: dict[str, Any], existing: dict[str, Any] | None
    ) -> None:
        if not existing:
            return
        existing_payload = cls._object_payload(existing.get("payload"))
        for metadata_key in _REMOTE_LIBRARY_METADATA_FIELDS:
            if existing_payload.get(metadata_key) is not None:
                entry[metadata_key] = existing_payload[metadata_key]

    @classmethod
    def _persist_remote_library_workout_entry(
        cls,
        db: Any,
        workout: dict[str, Any],
        existing: dict[str, Any] | None,
        local_id: str,
        external_id: str,
        now: str,
    ) -> dict[str, Any]:
        entry = planning_library.normalize_library_workout(
            workout,
            local_id=local_id,
            external_id=external_id,
            sync_status="synced",
        )
        cls._preserve_remote_library_metadata(entry, existing)
        storage_id = existing["id"] if existing else local_id
        db.execute(
            "INSERT INTO workout_library(id, local_id, external_id, payload, sync_dirty, sync_state, sync_error, last_synced_at, updated_at) VALUES (?, ?, ?, ?, 0, 'synced', NULL, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET local_id=excluded.local_id, external_id=excluded.external_id, payload=excluded.payload, sync_dirty=0, sync_state='synced', sync_error=NULL, last_synced_at=excluded.last_synced_at, updated_at=excluded.updated_at",
            (
                storage_id,
                local_id,
                external_id,
                json.dumps(entry, ensure_ascii=False),
                now,
                now,
            ),
        )
        return entry

    @classmethod
    def _mark_missing_remote_library_workouts(
        cls, db: Any, seen_external_ids: set[str], now: str
    ) -> None:
        remote_rows = db.execute(
            "SELECT id, external_id, sync_dirty, sync_state, payload "
            "FROM workout_library WHERE external_id IS NOT NULL"
        ).fetchall()
        for row in remote_rows:
            external_id = str(row.get("external_id") or "")
            if not external_id or external_id in seen_external_ids:
                continue
            if int(row.get("sync_dirty") or 0) or str(row.get("sync_state") or "") in {
                "local",
                "sync_error",
            }:
                continue
            payload = cls._object_payload(row.get("payload"))
            payload["sync_status"] = "remote_missing"
            db.execute(
                "UPDATE workout_library SET payload=?, sync_dirty=0, "
                "sync_state='remote_missing', sync_error=NULL, updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), now, row["id"]),
            )


@contextmanager
def workout_library_sync_guard() -> Iterator[None]:
    """Serialize operations that share the workout-library sync lock."""
    with _WORKOUT_LIBRARY_SYNC_LOCK:
        yield


def workout_library_sync_running() -> bool:
    """Return whether the shared workout-library lock is held."""
    return _WORKOUT_LIBRARY_SYNC_LOCK.locked()


class WorkoutLibraryRefreshService:
    """Import the remote workout library once without performing remote writes."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        provider_client_factory: Callable[[], Any],
        remote_reconciler: WorkoutLibraryRemoteReconciler,
        workout_library_service: WorkoutLibraryService,
        sync_state_service: WorkoutLibrarySyncStateService,
        key_value_repository: KeyValueRepository,
        event_buffer: StateEventBuffer,
        now: Callable[[], str],
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._provider_client_factory = provider_client_factory
        self._remote_reconciler = remote_reconciler
        self._workout_library_service = workout_library_service
        self._sync_state_service = sync_state_service
        self._key_value_repository = key_value_repository
        self._event_buffer = event_buffer
        self._now = now

    @maintenance_operation
    @intervals_operation
    def refresh(
        self,
        reason: str = "manual",
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Refresh local library from Intervals, preserving cancellation semantics."""
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)
        self._raise_chat_cancelled(cancel_event)
        synced_at = self._get_sync_timestamp()
        if synced_at:
            return {
                "status": "skipped",
                "reason": "local_authoritative",
                "workouts": len(
                    self._workout_library_service.list(include_archived=True)
                ),
                "local_synced": 0,
                "local_errors": [],
                "synced_at": synced_at,
                "library_state": self._sync_state_service.summary(),
            }

        with workout_library_sync_guard():
            self._raise_chat_cancelled(cancel_event)
            client = self._provider_client_factory()
            if cancel_event is None:
                workouts = client.get_workout_library()
            else:
                workouts = client.get_workout_library(cancel_event=cancel_event)
            self._raise_chat_cancelled(cancel_event)
            normalized = self._remote_reconciler.reconcile(
                workouts, remove_missing=True
            )

        synced_at = self._now()
        self._set_sync_markers(synced_at)
        self._event_buffer.publish("coach", {"status": "changed"})
        return {
            "status": "ok",
            "workouts": len(normalized),
            "local_synced": 0,
            "local_errors": [],
            "synced_at": synced_at,
            "library_state": self._sync_state_service.summary(),
        }

    def _get_sync_timestamp(self) -> str | None:
        with self._database_manager.unit_of_work() as db:
            return self._key_value_repository.get(db, "last_library_sync_at")

    def _set_sync_markers(self, synced_at: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, "last_library_sync_at", synced_at)
            self._key_value_repository.set(db, "last_library_sync_error", "")

    @staticmethod
    def _raise_chat_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


class WorkoutLibrarySyncStateService:
    """Read and persist local workout-library synchronization state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        redactor: Redactor,
        key_value_repository: KeyValueRepository,
        now: Callable[[], str],
    ):
        self._database_manager = database_manager
        self._redactor = redactor
        self._key_value_repository = key_value_repository
        self._now = now

    def preview(self) -> tuple[dict[str, int], list[dict[str, Any]], str]:
        with self._database_manager.unit_of_work() as db:
            rows = db.execute(
                "SELECT local_id, external_id, sync_state, payload FROM workout_library "
                "WHERE sync_state IN (?, ?, ?, ?) ORDER BY local_id",
                _OPEN_SYNC_STATES,
            ).fetchall()
            planned_rows = db.execute(
                "SELECT local_id, external_id, sync_state, payload FROM planned_units "
                "WHERE sync_state IN (?, ?, ?, ?) ORDER BY local_id",
                _OPEN_SYNC_STATES,
            ).fetchall()
        return self._snapshot(rows, planned_rows)

    def update(self, local_id: str, state: str, error: str | None = None) -> bool:
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT payload FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()
            if row is None:
                return False
            payload = self._object_payload(row["payload"])
            payload["sync_status"] = state
            db.execute(
                "UPDATE workout_library SET payload=?, sync_dirty=?, sync_state=?, "
                "sync_error=?, updated_at=? WHERE local_id=?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    0 if state in {"synced", "remote_missing"} else 1,
                    state,
                    self._redactor.redact_text(str(error))[:1000] if error else None,
                    self._now(),
                    local_id,
                ),
            )
        return True

    def summary(self) -> dict[str, int]:
        with self._database_manager.unit_of_work() as db:
            rows = db.execute(
                "SELECT sync_state, COUNT(*) AS count FROM workout_library GROUP BY sync_state"
            ).fetchall()
            planned_rows = db.execute(
                "SELECT sync_state, COUNT(*) AS count FROM planned_units GROUP BY sync_state"
            ).fetchall()
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
            row = db.execute(
                "SELECT id, local_id, external_id, sync_state, payload "
                "FROM workout_library WHERE local_id = ?",
                (normalized_id,),
            ).fetchone()
        if not row:
            raise AppError(404, "Lokale Bibliothekseinheit nicht gefunden.")
        try:
            local_workout = json.loads(row["payload"])
        except (TypeError, ValueError) as exc:
            raise AppError(500, CORRUPT_LIBRARY_ERROR) from exc
        return normalized_id, row, local_workout

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
            db.execute(
                "UPDATE workout_library SET external_id=?, payload=? WHERE local_id=?",
                (
                    external_id,
                    json.dumps(
                        {**local_workout, "external_id": external_id},
                        ensure_ascii=False,
                    ),
                    local_id,
                ),
            )
        return external_id

    def finish(
        self,
        local_id: str,
        external_id: str,
        local_workout: dict[str, Any],
        remote_workout: dict[str, Any],
    ) -> dict[str, Any]:
        planning_workouts.validate_intervals_workout_result(
            local_workout, remote_workout
        )
        synced = planning_library.normalize_library_workout(
            {**local_workout, **remote_workout},
            local_id=local_id,
            external_id=external_id,
            sync_status="synced",
        )
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET external_id=?, payload=?, sync_dirty=0, "
                "sync_state='synced', sync_error=NULL, last_synced_at=?, updated_at=? "
                "WHERE local_id=?",
                (
                    external_id,
                    json.dumps(synced, ensure_ascii=False),
                    now,
                    now,
                    local_id,
                ),
            )
            self._key_value_repository.set(db, "last_library_sync_at", now)
            self._key_value_repository.set(db, "last_library_sync_error", "")
        return synced

    def persist_calendar_identity(self, local_id: str, event: dict[str, Any]) -> bool:
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT payload FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()
            if row is None:
                return False
            payload = self._parse_payload(row["payload"])
            if not isinstance(payload, dict):
                return False
            payload["remote_event_id"] = str(event["id"])
            external_id = str(event.get("external_id") or "").strip()
            if external_id:
                payload["remote_event_external_id"] = external_id
            db.execute(
                "UPDATE workout_library SET payload=?, updated_at=? WHERE local_id=?",
                (json.dumps(payload, ensure_ascii=False), self._now(), local_id),
            )
        return True

    @staticmethod
    def _parse_payload(raw_payload: Any) -> Any:
        try:
            return json.loads(raw_payload or "{}")
        except (TypeError, ValueError):
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
            str(payload_data.get("date") or "").strip()[:10]
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
                "payload_hash": hashlib.sha256(raw_payload.encode("utf-8")).hexdigest(),
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
        provider_client_factory: Callable[[], Any],
        state_service: WorkoutLibrarySyncStateService,
        *,
        _lock: Any | None = None,
    ):
        self._config = config
        self._provider_client_factory = provider_client_factory
        self._state_service = state_service
        self._lock = _lock if _lock is not None else _WORKOUT_LIBRARY_SYNC_LOCK

    def plan_remote(
        self, workout_id: str, workout: dict[str, Any], plan_date: str
    ) -> dict[str, Any]:
        return self._provider_client_factory().plan_library_workout(
            workout_id, workout, plan_date
        )

    def sync_calendar_entry(
        self, local_id: str, synced: dict[str, Any]
    ) -> dict[str, Any] | None:
        planned_date = str(synced.get("date") or "").strip()[:10]
        if not planned_date:
            return None
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
            raise AppError(503, INTERVALS_API_KEY_ERROR)
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
            normalized_id, external_id, local_workout, remote_workout or {}
        )

    def _upsert_remote(
        self, row: dict[str, Any], local_workout: dict[str, Any]
    ) -> dict[str, Any] | None:
        external_id = str(row.get("external_id") or "")
        if external_id and row.get("sync_state") != "remote_missing":
            updated = self._provider_client_factory().update_library_workout(
                external_id, local_workout
            )
            return {**updated, "id": external_id}
        remote_workouts = self._provider_client_factory().get_workout_library()
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
        created = self._provider_client_factory().create_library_workouts(
            [local_workout]
        )
        return created[0] if created and isinstance(created[0], dict) else None
