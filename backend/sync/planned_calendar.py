"""Push one local planned unit to the Intervals.icu calendar."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError

from backend.config import Config
from backend.db import DatabaseManager
from backend.errors import (
    CORRUPT_PLANNING_ERROR,
    INTERVALS_API_KEY_ERROR,
    INVALID_PLANNING_ID_ERROR,
    PLANNED_CALENDAR_RECHECK_ERROR,
    AppError,
)
from backend.planning import library as planning_library
from backend.planning.workout_export import build_planned_workout_export
from backend.sync.reconcile import PlannedUnitSyncStateWriter
from backend.sync.workout_export import WorkoutExportPort

_PLANNED_UNIT_SYNCS: set[str] = set()
_PLANNED_UNIT_SYNC_LOCK = threading.Lock()
_PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL = (
    "SELECT payload FROM planned_units WHERE local_id=?"
)


@contextmanager
def planned_unit_sync_guard(local_id: str) -> Iterator[None]:
    """Exclude a concurrent push of the same local unit."""
    with _PLANNED_UNIT_SYNC_LOCK:
        if local_id in _PLANNED_UNIT_SYNCS:
            raise AppError(
                409,
                "Diese Einheit wird bereits synchronisiert.",
                reason="planned_unit_sync_running",
            )
        _PLANNED_UNIT_SYNCS.add(local_id)
    try:
        yield
    finally:
        with _PLANNED_UNIT_SYNC_LOCK:
            _PLANNED_UNIT_SYNCS.remove(local_id)


class PlannedCalendarSyncService:
    """Own the normal single-unit planned-calendar push workflow."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        export: WorkoutExportPort,
        state_writer: PlannedUnitSyncStateWriter,
        now: Callable[[], str],
        today: Callable[[], date],
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._export = export
        self._state_writer = state_writer
        self._now = now
        self._today = today

    def sync_entry(self, local_id: str) -> dict[str, Any] | None:
        with planned_unit_sync_guard(local_id):
            return self._sync_entry_unlocked(local_id)

    def _load_entry(self, local_id: str) -> tuple[str, Any, dict[str, Any]]:
        try:
            normalized_id = str(uuid.UUID(str(local_id)))
        except (ValueError, AttributeError) as exc:
            raise AppError(400, INVALID_PLANNING_ID_ERROR) from exc
        with self._database_manager.reader() as db:
            row = db.execute(
                "SELECT payload, sync_state FROM planned_units WHERE local_id=?",
                (normalized_id,),
            ).fetchone()
        if not row:
            raise AppError(404, "Lokale Planung nicht gefunden.")
        try:
            workout = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError) as exc:
            raise AppError(500, CORRUPT_PLANNING_ERROR) from exc
        if not isinstance(workout, dict):
            raise AppError(500, CORRUPT_PLANNING_ERROR)
        return normalized_id, row, workout

    def _recheck(self, normalized_id: str, original_payload: str) -> None:
        with self._database_manager.reader() as db:
            current = db.execute(
                _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL, (normalized_id,)
            ).fetchone()
        self._require_unchanged(current, original_payload)

    @staticmethod
    def _require_unchanged(current: Any, original_payload: str) -> None:
        if not current or planning_library.library_payload_hash(
            current["payload"]
        ) != planning_library.library_payload_hash(original_payload):
            raise AppError(
                409,
                "Die Planung wurde während der Synchronisation geändert.",
                reason="planning_revision_conflict",
            )

    def _persist(
        self,
        local_id: str,
        state: str,
        *,
        error: str | None = None,
        remote_event: dict[str, Any] | None = None,
        expected_payload: str | None = None,
    ) -> None:
        with self._database_manager.unit_of_work() as db:
            self._state_writer.persist(
                db,
                local_id,
                state,
                error,
                remote_event,
                now=self._now(),
                expected_payload=expected_payload,
            )

    def _remote_event_is_invalid(self, remote_id: str, event: Any) -> bool:
        return (
            not isinstance(event, dict)
            or self._export.event_identity(event) != remote_id
            or not self._export.is_unpaired_future_planned(event, today=self._today())
        )

    @staticmethod
    def _is_not_found(error: AppError) -> bool:
        cause = error.__cause__
        return error.status == 404 or (
            isinstance(cause, HTTPError) and cause.code == 404
        )

    def _delete_remote_event(
        self, remote_id: str, normalized_id: str, original_payload: str
    ) -> None:
        try:
            event = self._export.read_event(remote_id)
        except AppError as exc:
            if self._is_not_found(exc):
                return
            raise
        if self._remote_event_is_invalid(remote_id, event):
            raise AppError(
                409,
                "Die zugeordnete Einheit ist keine freie zukünftige Planung mehr.",
                reason="intervals_workout_identity_conflict",
            )
        self._recheck(normalized_id, original_payload)
        self._export.delete(remote_id)

    def _mark_removed(self, normalized_id: str, original_payload: str) -> None:
        with self._database_manager.unit_of_work() as db:
            current = db.execute(
                _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL, (normalized_id,)
            ).fetchone()
            self._require_unchanged(current, original_payload)
            self._state_writer.persist(
                db, normalized_id, "synced", None, None, now=self._now()
            )

    def _remove_event(
        self, normalized_id: str, row: Any, workout: dict[str, Any]
    ) -> None:
        remote_id = str(workout.get("remote_event_id") or "").strip()
        if remote_id:
            self._require_calendar_access()
            self._delete_remote_event(remote_id, normalized_id, row["payload"])
        self._mark_removed(normalized_id, row["payload"])

    def _require_calendar_access(self) -> None:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR, reason="not_configured")

    def _event_payload(
        self, normalized_id: str, workout: dict[str, Any]
    ) -> dict[str, Any]:
        event_payload = self._export.serialize(
            normalized_id,
            build_planned_workout_export(workout, today=self._today()),
        )
        remote_external_id = str(workout.get("remote_event_external_id") or "").strip()
        if remote_external_id:
            event_payload["external_id"] = remote_external_id
        if workout.get("remote_event_id"):
            event_payload["id"] = str(workout["remote_event_id"])[:120]
        return event_payload

    def _persist_sync_error(
        self,
        normalized_id: str,
        event: dict[str, Any],
        event_payload: dict[str, Any],
        error: AppError,
        expected_payload: str,
    ) -> None:
        self._persist(
            normalized_id,
            "sync_error",
            error=str(error),
            remote_event={
                **event,
                "external_id": self._export.event_external_id(event)
                or self._export.event_external_id(event_payload),
            },
            expected_payload=expected_payload,
        )

    def _remote_event(
        self,
        normalized_id: str,
        workout: dict[str, Any],
        event_payload: dict[str, Any],
        expected_payload: str,
    ) -> dict[str, Any]:
        self._require_calendar_access()
        result = self._export.upsert([event_payload])
        event = result[0] if isinstance(result, list) and result else None
        if (
            not isinstance(event, dict)
            or not self._export.event_identity(event).strip()
        ):
            raise AppError(
                502, "Intervals.icu hat keine geplante Einheit zurückgegeben."
            )
        try:
            self._export.verify_readback(workout, event)
        except AppError as exc:
            self._persist_sync_error(
                normalized_id, event, event_payload, exc, expected_payload
            )
            raise
        return event

    def _sync_entry_unlocked(self, local_id: str) -> dict[str, Any] | None:
        normalized_id, row, workout = self._load_entry(local_id)
        if workout.get("local_deleted") or workout.get("archived"):
            self._remove_event(normalized_id, row, workout)
            return None
        event_payload = self._event_payload(normalized_id, workout)
        event = self._remote_event(
            normalized_id, workout, event_payload, row["payload"]
        )
        self._persist(
            normalized_id,
            "synced",
            remote_event={
                **event,
                "external_id": self._export.event_external_id(event)
                or self._export.event_external_id(event_payload),
            },
            expected_payload=row["payload"],
        )
        return event


@dataclass
class _PlannedCalendarRepairContext:
    local_id: str
    expected_hash: str
    batch: PlannedCalendarRepairBatch | None
    workout: dict[str, Any]
    planned_date: date
    today: date
    removing: bool
    export: WorkoutExportPort
    remote_id: str
    identities: set[str]
    other_remote_ids: set[str]
    other_external_ids: set[str]
    newest: str


class PlannedCalendarRepairBatch:
    """Share the before and after calendar snapshots for selected repairs."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        export: WorkoutExportPort,
        requested: list[dict[str, Any]],
        *,
        today: date,
        future_days: int,
    ) -> None:
        self.export = export
        local_ids = [str(item["library_workout_id"]) for item in requested]
        newest = ""
        if local_ids:
            placeholders = ",".join("?" for _ in local_ids)
            with database_manager.reader() as db:
                row = db.execute(
                    "SELECT MAX(json_extract(payload, '$.date')) AS newest "
                    f"FROM planned_units WHERE local_id IN ({placeholders})",
                    local_ids,
                ).fetchone()
            newest = str((row or {}).get("newest") or "")
        self.oldest = today.isoformat()
        self.newest = max(newest, (today + timedelta(days=future_days)).isoformat())
        self.events: dict[str, dict[str, Any]] | None = None
        self.read_error: Exception | None = None
        self.completions: list[
            tuple[str, Callable[[list[dict[str, Any]] | None], dict[str, Any] | None]]
        ] = []

    def _read(self) -> list[dict[str, Any]]:
        return self.export.list_window(oldest=self.oldest, newest=self.newest)

    def snapshot(self) -> list[dict[str, Any]]:
        if self.read_error is not None:
            raise self.read_error
        if self.events is None:
            try:
                self.events = {
                    identity: event
                    for event in self._read()
                    if (identity := self.export.event_identity(event))
                }
            except Exception as exc:
                self.read_error = exc
                raise
        return list(self.events.values())

    def remember(self, event: dict[str, Any]) -> None:
        self.events[self.export.event_identity(event)] = event

    def forget(self, event_id: str) -> None:
        self.events.pop(event_id, None)

    def verify(self) -> dict[str, Exception | None]:
        if not self.completions:
            return {}
        try:
            final_events = self._read()
        except Exception as exc:  # noqa: BLE001 - return provider failures per entry
            return {local_id: exc for local_id, _ in self.completions}
        outcomes: dict[str, Exception | None] = {}
        for local_id, complete in self.completions:
            try:
                with planned_unit_sync_guard(local_id):
                    complete(final_events)
                outcomes[local_id] = None
            except Exception as exc:  # noqa: BLE001 - report each deferred failure
                outcomes[local_id] = exc
        return outcomes


class PlannedCalendarRepairService:
    """Repair explicitly selected future planned units by exact remote identity."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        export: WorkoutExportPort,
        state_writer: PlannedUnitSyncStateWriter,
        now: Callable[[], str],
        today: Callable[[], date],
        future_days: int,
    ) -> None:
        self._database_manager = database_manager
        self._export = export
        self._state_writer = state_writer
        self._now = now
        self._today = today
        self._future_days = int(future_days)

    def create_batch(
        self, requested: list[dict[str, Any]]
    ) -> PlannedCalendarRepairBatch:
        return PlannedCalendarRepairBatch(
            self._database_manager,
            self._export,
            requested,
            today=self._today(),
            future_days=self._future_days,
        )

    def record_error(self, local_id: str, error: str) -> bool:
        """Persist a selected repair failure through the shared state writer."""
        with self._database_manager.unit_of_work() as db:
            return self._state_writer.persist(
                db,
                local_id,
                "sync_error",
                error,
                None,
                now=self._now(),
            )

    def repair_entry(
        self,
        local_id: str,
        expected_hash: str,
        batch: PlannedCalendarRepairBatch | None = None,
    ) -> dict[str, Any] | None:
        with planned_unit_sync_guard(local_id):
            context = self._context(local_id, expected_hash, batch)
            related = self._related_events(context)
            self._check_remote_identity(context, related)
            keeper = next(
                (
                    event
                    for event in related
                    if context.export.event_identity(event) == context.remote_id
                ),
                related[0] if related else None,
            )
            if not context.removing:
                self._upsert(context, keeper)
            self._delete_duplicates(context, related)
            complete = self._completion(context)
            if context.batch is not None:
                context.batch.completions.append((context.local_id, complete))
                return None
            return complete()

    def _context(
        self,
        local_id: str,
        expected_hash: str,
        batch: PlannedCalendarRepairBatch | None,
    ) -> _PlannedCalendarRepairContext:
        with self._database_manager.reader() as db:
            row = db.execute(
                _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL, (local_id,)
            ).fetchone()
            others = db.execute(
                "SELECT local_id, json_extract(payload, '$.remote_event_id') AS remote_id, "
                "json_extract(payload, '$.remote_event_external_id') AS remote_external_id "
                "FROM planned_units WHERE local_id<>?",
                (local_id,),
            ).fetchall()
        if (
            not row
            or planning_library.library_payload_hash(row["payload"]) != expected_hash
        ):
            raise AppError(
                409,
                "Die Planung hat sich seit dem Reparaturauftrag geändert.",
                reason="planning_revision_conflict",
            )
        try:
            workout = json.loads(row["payload"])
            if not isinstance(workout, dict):
                raise TypeError("planned payload is not an object")
            planned_date = date.fromisoformat(str(workout.get("date") or ""))
        except (TypeError, ValueError) as exc:
            raise AppError(
                409,
                "Die Planung ist ungültig und kann nicht repariert werden.",
                reason="planning_revision_conflict",
            ) from exc
        today = self._today()
        if planned_date < today:
            raise AppError(
                400,
                "Reparatur-Sync ist nur für zukünftige geplante Einheiten erlaubt.",
                reason="invalid_plan",
            )
        export = batch.export if batch is not None else self._export
        return _PlannedCalendarRepairContext(
            local_id=local_id,
            expected_hash=expected_hash,
            batch=batch,
            workout=workout,
            planned_date=planned_date,
            today=today,
            removing=bool(workout.get("local_deleted") or workout.get("archived")),
            export=export,
            remote_id=str(workout.get("remote_event_id") or ""),
            identities={
                export.external_id_for(local_id),
                *(
                    [str(workout["remote_event_external_id"])]
                    if workout.get("remote_event_external_id")
                    else []
                ),
            },
            other_remote_ids={
                str(item["remote_id"]) for item in others if item.get("remote_id")
            },
            other_external_ids={
                *{export.external_id_for(str(item["local_id"])) for item in others},
                *{
                    str(item["remote_external_id"])
                    for item in others
                    if item.get("remote_external_id")
                },
            },
            newest=max(
                planned_date, today + timedelta(days=self._future_days)
            ).isoformat(),
        )

    def _recheck(self, context: _PlannedCalendarRepairContext, message: str) -> None:
        with self._database_manager.reader() as db:
            current = db.execute(
                _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL,
                (context.local_id,),
            ).fetchone()
        if (
            not current
            or planning_library.library_payload_hash(current["payload"])
            != context.expected_hash
        ):
            raise AppError(409, message, reason="planning_revision_conflict")

    @staticmethod
    def _event_is_invalid(
        context: _PlannedCalendarRepairContext,
        event: dict[str, Any],
        belongs_elsewhere: bool,
    ) -> bool:
        return belongs_elsewhere or not context.export.is_unpaired_future_planned(
            event, today=context.today
        )

    @staticmethod
    def _event_is_ambiguous(
        context: _PlannedCalendarRepairContext,
        event: dict[str, Any],
        belongs_elsewhere: bool,
    ) -> bool:
        return (
            not context.removing
            and not belongs_elsewhere
            and context.export.is_namesake_on_day(
                event,
                day=context.planned_date.isoformat(),
                name=context.workout.get("name"),
            )
        )

    def _related_event(
        self, context: _PlannedCalendarRepairContext, event: dict[str, Any]
    ) -> bool:
        event_id = context.export.event_identity(event)
        external_id = context.export.event_external_id(event)
        belongs_elsewhere = (
            event_id in context.other_remote_ids
            or external_id in context.other_external_ids
        )
        identified = bool(
            event_id
            and (event_id == context.remote_id or external_id in context.identities)
        )
        if identified:
            if self._event_is_invalid(context, event, belongs_elsewhere):
                raise AppError(
                    409,
                    "Eine zugeordnete Einheit ist keine freie zukünftige Planung mehr.",
                    reason="intervals_workout_identity_conflict",
                )
            return True
        if self._event_is_ambiguous(context, event, belongs_elsewhere):
            raise AppError(
                409,
                "Eine gleichnamige Remote-Einheit am selben Tag ist nicht eindeutig "
                "zugeordnet. Keine automatische Kopie oder Löschung durchgeführt.",
                reason="intervals_workout_identity_ambiguous",
            )
        return False

    def _related_events(
        self,
        context: _PlannedCalendarRepairContext,
        events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if events is None:
            if context.batch is not None:
                events = context.batch.snapshot()
            else:
                events = context.export.list_window(
                    oldest=context.today.isoformat(), newest=context.newest
                )
        return [event for event in events if self._related_event(context, event)]

    @staticmethod
    def _is_not_found(error: AppError) -> bool:
        return error.status == 404 or (
            isinstance(error.__cause__, HTTPError) and error.__cause__.code == 404
        )

    def _check_remote_identity(
        self,
        context: _PlannedCalendarRepairContext,
        related: list[dict[str, Any]],
    ) -> None:
        if not context.remote_id or any(
            context.export.event_identity(event) == context.remote_id
            for event in related
        ):
            return
        try:
            context.export.read_event(context.remote_id)
        except AppError as exc:
            if self._is_not_found(exc):
                return
            raise
        raise AppError(
            409,
            "Die zugeordnete Remote-Einheit liegt ausserhalb des Reparaturzeitraums.",
            reason="intervals_workout_identity_conflict",
        )

    def _upsert(
        self,
        context: _PlannedCalendarRepairContext,
        keeper: dict[str, Any] | None,
    ) -> None:
        payload = context.export.serialize(
            context.local_id,
            build_planned_workout_export(context.workout, today=context.today),
        )
        if keeper:
            payload["id"] = str(keeper["id"])
            payload["external_id"] = (
                context.export.event_external_id(keeper) or payload["external_id"]
            )
        context.identities.add(payload["external_id"])
        self._recheck(context, PLANNED_CALENDAR_RECHECK_ERROR)
        response = context.export.upsert([payload])
        result = (
            response[0] if isinstance(response, list) and len(response) == 1 else None
        )
        if (
            not isinstance(result, dict)
            or not context.export.event_identity(result).strip()
        ):
            raise AppError(
                502,
                "Intervals.icu hat keine eindeutige reparierte Einheit zurückgegeben.",
                reason="intervals_workout_verification_failed",
            )
        context.remote_id = context.export.event_identity(result)
        saved_event = {
            **result,
            "external_id": payload["external_id"],
        }
        if context.batch is not None:
            context.batch.remember(saved_event)
        conflict = None
        with self._database_manager.unit_of_work() as db:
            current = db.execute(
                _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL,
                (context.local_id,),
            ).fetchone()
            if (
                not current
                or planning_library.library_payload_hash(current["payload"])
                != context.expected_hash
            ):
                self._state_writer.persist(
                    db,
                    context.local_id,
                    "sync_error",
                    "Planung während der Reparatur geändert.",
                    saved_event,
                    now=self._now(),
                )
                conflict = AppError(
                    409,
                    PLANNED_CALENDAR_RECHECK_ERROR,
                    reason="planning_revision_conflict",
                )
            else:
                self._state_writer.persist(
                    db,
                    context.local_id,
                    "syncing",
                    None,
                    saved_event,
                    now=self._now(),
                )
                current = db.execute(
                    _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL,
                    (context.local_id,),
                ).fetchone()
                context.expected_hash = planning_library.library_payload_hash(
                    current["payload"]
                )
        if conflict is not None:
            raise conflict
        if not context.export.confirms_planned_event(
            result,
            day=context.planned_date.isoformat(),
            name=context.workout.get("name"),
        ):
            raise AppError(
                502,
                "Intervals.icu hat Datum oder Namen der reparierten Einheit nicht bestätigt.",
                reason="intervals_workout_verification_failed",
            )
        context.export.verify_readback(context.workout, result)

    def _delete_duplicates(
        self,
        context: _PlannedCalendarRepairContext,
        related: list[dict[str, Any]],
    ) -> None:
        for event in related:
            event_id = context.export.event_identity(event)
            if not event_id:
                # Never issue a delete without a concrete remote identity.
                continue
            if not context.removing and event_id == context.remote_id:
                continue
            self._recheck(context, PLANNED_CALENDAR_RECHECK_ERROR)
            context.export.delete(event_id)
            if context.batch is not None:
                context.batch.forget(event_id)

    def _completion(
        self, context: _PlannedCalendarRepairContext
    ) -> Callable[[list[dict[str, Any]] | None], dict[str, Any] | None]:
        def complete(
            events: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any] | None:
            remaining = self._related_events(context, events)
            verified = None
            if context.removing:
                if remaining:
                    raise AppError(
                        502,
                        "Die entfernten Remote-Einheiten sind noch vorhanden.",
                        reason="intervals_workout_verification_failed",
                    )
            elif (
                len(remaining) != 1
                or context.export.event_identity(remaining[0]) != context.remote_id
            ):
                raise AppError(
                    502,
                    "Der Kalender bestätigt keine eindeutige reparierte Einheit.",
                    reason="intervals_workout_verification_failed",
                )
            else:
                event = remaining[0]
                if not context.export.confirms_planned_event(
                    event,
                    day=context.planned_date.isoformat(),
                    name=context.workout.get("name"),
                ):
                    raise AppError(
                        502,
                        "Der Kalender bestätigt Datum oder Namen der reparierten Einheit nicht.",
                        reason="intervals_workout_verification_failed",
                    )
                context.export.verify_readback(context.workout, event)
                verified = event
            with self._database_manager.unit_of_work() as db:
                current = db.execute(
                    _PLANNED_UNIT_PAYLOAD_BY_LOCAL_ID_SQL,
                    (context.local_id,),
                ).fetchone()
                if (
                    not current
                    or planning_library.library_payload_hash(current["payload"])
                    != context.expected_hash
                ):
                    raise AppError(
                        409,
                        PLANNED_CALENDAR_RECHECK_ERROR,
                        reason="planning_revision_conflict",
                    )
                self._state_writer.persist(
                    db,
                    context.local_id,
                    "synced",
                    None,
                    verified,
                    now=self._now(),
                )
            return verified

        return complete
