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
from urllib.parse import quote

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
from backend.planning import workouts as planning_workouts
from backend.sync.reconcile import PlannedUnitSyncStateWriter

_PLANNED_UNIT_SYNCS: set[str] = set()
_PLANNED_UNIT_SYNC_LOCK = threading.Lock()


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
        provider_client_factory: Callable[[], Any],
        state_writer: PlannedUnitSyncStateWriter,
        now: Callable[[], str],
        today: Callable[[], date],
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._provider_client_factory = provider_client_factory
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
                "SELECT payload FROM planned_units WHERE local_id=?", (normalized_id,)
            ).fetchone()
        self._require_unchanged(current, original_payload)

    @staticmethod
    def _require_unchanged(current: Any, original_payload: str) -> None:
        if not current or planning_library.library_payload_hash(
            current["payload"]
        ) != planning_library.library_payload_hash(original_payload):
            raise AppError(
                409,
                "Die Planung wurde waehrend der Synchronisation geaendert.",
                reason="planning_revision_conflict",
            )

    def _persist(
        self,
        local_id: str,
        state: str,
        *,
        error: str | None = None,
        remote_event: dict[str, Any] | None = None,
    ) -> None:
        with self._database_manager.unit_of_work() as db:
            self._state_writer.persist(
                db, local_id, state, error, remote_event, now=self._now()
            )

    def _remote_event_is_invalid(self, remote_id: str, event: Any) -> bool:
        return (
            not isinstance(event, dict)
            or str(event.get("id") or "") != remote_id
            or event.get("category") != "WORKOUT"
            or str(event.get("start_date_local") or "")[:10] < self._today().isoformat()
            or event.get("paired_activity_id")
            or event.get("paired_event_id")
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
        client = self._provider_client_factory()
        athlete = quote(self._config.intervals_athlete_id, safe="")
        try:
            event = client.get(f"/athlete/{athlete}/events/{quote(remote_id, safe='')}")
        except AppError as exc:
            if self._is_not_found(exc):
                return
            raise
        if self._remote_event_is_invalid(remote_id, event):
            raise AppError(
                409,
                "Die zugeordnete Einheit ist keine freie zukuenftige Planung mehr.",
                reason="intervals_workout_identity_conflict",
            )
        self._recheck(normalized_id, original_payload)
        client.delete_event(remote_id)

    def _mark_removed(self, normalized_id: str, original_payload: str) -> None:
        with self._database_manager.unit_of_work() as db:
            current = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (normalized_id,)
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
            raise AppError(503, INTERVALS_API_KEY_ERROR)

    def _event_payload(
        self, normalized_id: str, workout: dict[str, Any]
    ) -> dict[str, Any]:
        event_payload = planning_workouts.workout_event_payload(
            normalized_id, workout, today=self._today()
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
    ) -> None:
        self._persist(
            normalized_id,
            "sync_error",
            error=str(error),
            remote_event={
                **event,
                "external_id": event.get("external_id")
                or event_payload.get("external_id"),
            },
        )

    def _remote_event(
        self,
        normalized_id: str,
        workout: dict[str, Any],
        event_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_calendar_access()
        result = self._provider_client_factory().upsert_calendar_events([event_payload])
        event = result[0] if isinstance(result, list) and result else None
        if not isinstance(event, dict) or not str(event.get("id") or "").strip():
            raise AppError(
                502, "Intervals.icu hat keine geplante Einheit zurückgegeben."
            )
        try:
            planning_workouts.validate_intervals_workout_result(workout, event)
        except AppError as exc:
            self._persist_sync_error(normalized_id, event, event_payload, exc)
            raise
        return event

    def _sync_entry_unlocked(self, local_id: str) -> dict[str, Any] | None:
        normalized_id, row, workout = self._load_entry(local_id)
        if workout.get("local_deleted") or workout.get("archived"):
            self._remove_event(normalized_id, row, workout)
            return None
        event_payload = self._event_payload(normalized_id, workout)
        event = self._remote_event(normalized_id, workout, event_payload)
        self._persist(
            normalized_id,
            "synced",
            remote_event={
                **event,
                "external_id": event.get("external_id")
                or event_payload.get("external_id"),
            },
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
    client: Any
    athlete: str
    remote_id: str
    identities: set[str]
    other_remote_ids: set[str]
    other_external_ids: set[str]
    newest: str


class PlannedCalendarRepairBatch:
    """Share the before and after calendar snapshots for selected repairs."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        client: Any,
        requested: list[dict[str, Any]],
        *,
        today: date,
        future_days: int,
    ) -> None:
        self.client = client
        self.athlete = quote(config.intervals_athlete_id, safe="")
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
        self.params = {
            "oldest": today.isoformat(),
            "newest": max(newest, (today + timedelta(days=future_days)).isoformat()),
            "category": "WORKOUT",
        }
        self.events: dict[str, dict[str, Any]] | None = None
        self.read_error: Exception | None = None
        self.completions: list[
            tuple[str, Callable[[list[dict[str, Any]] | None], dict[str, Any] | None]]
        ] = []

    def _read(self) -> list[dict[str, Any]]:
        return self.client.get_paged_collection(
            f"/athlete/{self.athlete}/events", self.params, "repair_workouts"
        )

    def snapshot(self) -> list[dict[str, Any]]:
        if self.read_error is not None:
            raise self.read_error
        if self.events is None:
            try:
                self.events = {
                    str(event["id"]): event
                    for event in self._read()
                    if event.get("id") not in (None, "")
                }
            except Exception as exc:
                self.read_error = exc
                raise
        return list(self.events.values())

    def remember(self, event: dict[str, Any]) -> None:
        self.events[str(event["id"])] = event

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
        config: Config,
        database_manager: DatabaseManager,
        provider_client_factory: Callable[[], Any],
        state_writer: PlannedUnitSyncStateWriter,
        now: Callable[[], str],
        today: Callable[[], date],
        future_days: int,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._provider_client_factory = provider_client_factory
        self._state_writer = state_writer
        self._now = now
        self._today = today
        self._future_days = int(future_days)

    def create_batch(
        self, requested: list[dict[str, Any]]
    ) -> PlannedCalendarRepairBatch:
        return PlannedCalendarRepairBatch(
            self._config,
            self._database_manager,
            self._provider_client_factory(),
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
                    if str(event.get("id")) == context.remote_id
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
                "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
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
                "Die Planung hat sich seit dem Reparaturauftrag geaendert.",
                reason="planning_revision_conflict",
            )
        workout = json.loads(row["payload"])
        today = self._today()
        planned_date = date.fromisoformat(str(workout.get("date") or ""))
        if planned_date < today:
            raise AppError(
                400,
                "Reparatur-Sync ist nur fuer zukuenftige geplante Einheiten erlaubt.",
                reason="invalid_plan",
            )
        client = batch.client if batch is not None else self._provider_client_factory()
        return _PlannedCalendarRepairContext(
            local_id=local_id,
            expected_hash=expected_hash,
            batch=batch,
            workout=workout,
            planned_date=planned_date,
            today=today,
            removing=bool(workout.get("local_deleted") or workout.get("archived")),
            client=client,
            athlete=quote(self._config.intervals_athlete_id, safe=""),
            remote_id=str(workout.get("remote_event_id") or ""),
            identities={
                f"{planning_workouts.COACH_EVENT_EXTERNAL_PREFIX}{local_id}",
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
                *{
                    f"{planning_workouts.COACH_EVENT_EXTERNAL_PREFIX}{item['local_id']}"
                    for item in others
                },
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
                "SELECT payload FROM planned_units WHERE local_id=?",
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
        return (
            belongs_elsewhere
            or event.get("category") != "WORKOUT"
            or str(event.get("start_date_local") or "")[:10] < context.today.isoformat()
            or event.get("paired_activity_id")
            or event.get("paired_event_id")
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
            and event.get("category") == "WORKOUT"
            and str(event.get("start_date_local") or "").startswith(
                context.planned_date.isoformat()
            )
            and str(event.get("name") or "").strip().casefold()
            == str(context.workout.get("name") or "").strip().casefold()
        )

    def _related_event(
        self, context: _PlannedCalendarRepairContext, event: dict[str, Any]
    ) -> bool:
        event_id = str(event.get("id") or "")
        external_id = str(event.get("external_id") or "")
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
                    "Eine zugeordnete Einheit ist keine freie zukuenftige Planung mehr.",
                    reason="intervals_workout_identity_conflict",
                )
            return True
        if self._event_is_ambiguous(context, event, belongs_elsewhere):
            raise AppError(
                409,
                "Eine gleichnamige Remote-Einheit am selben Tag ist nicht eindeutig "
                "zugeordnet. Keine automatische Kopie oder Loeschung durchgefuehrt.",
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
                events = context.client.get_paged_collection(
                    f"/athlete/{context.athlete}/events",
                    {
                        "oldest": context.today.isoformat(),
                        "newest": context.newest,
                        "category": "WORKOUT",
                    },
                    "repair_workouts",
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
            str(event.get("id")) == context.remote_id for event in related
        ):
            return
        try:
            context.client.get(
                f"/athlete/{context.athlete}/events/{quote(context.remote_id, safe='')}"
            )
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
        payload = planning_workouts.workout_event_payload(
            context.local_id, context.workout, today=context.today
        )
        if keeper:
            payload["id"] = str(keeper["id"])
            payload["external_id"] = str(
                keeper.get("external_id") or payload["external_id"]
            )
        context.identities.add(payload["external_id"])
        self._recheck(context, PLANNED_CALENDAR_RECHECK_ERROR)
        response = context.client.upsert_calendar_events([payload])
        result = (
            response[0] if isinstance(response, list) and len(response) == 1 else None
        )
        if not isinstance(result, dict) or not str(result.get("id") or "").strip():
            raise AppError(
                502,
                "Intervals.icu hat keine eindeutige reparierte Einheit zurueckgegeben.",
                reason="intervals_workout_verification_failed",
            )
        context.remote_id = str(result["id"])
        saved_event = {
            **result,
            "external_id": payload["external_id"],
        }
        if context.batch is not None:
            context.batch.remember(saved_event)
        conflict = None
        with self._database_manager.unit_of_work() as db:
            current = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?",
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
                    "Planung waehrend der Reparatur geaendert.",
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
                    "SELECT payload FROM planned_units WHERE local_id=?",
                    (context.local_id,),
                ).fetchone()
                context.expected_hash = planning_library.library_payload_hash(
                    current["payload"]
                )
        if conflict is not None:
            raise conflict
        if not str(result.get("start_date_local") or "").startswith(
            context.planned_date.isoformat()
        ) or result.get("name") != context.workout.get("name"):
            raise AppError(
                502,
                "Intervals.icu hat Datum oder Namen der reparierten Einheit nicht bestaetigt.",
                reason="intervals_workout_verification_failed",
            )
        planning_workouts.validate_intervals_workout_result(context.workout, result)

    def _delete_duplicates(
        self,
        context: _PlannedCalendarRepairContext,
        related: list[dict[str, Any]],
    ) -> None:
        for event in related:
            if not context.removing and str(event.get("id")) == context.remote_id:
                continue
            event_id = str(event["id"])
            self._recheck(context, PLANNED_CALENDAR_RECHECK_ERROR)
            context.client.delete_event(event_id)
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
                len(remaining) != 1 or str(remaining[0].get("id")) != context.remote_id
            ):
                raise AppError(
                    502,
                    "Der Kalender bestaetigt keine eindeutige reparierte Einheit.",
                    reason="intervals_workout_verification_failed",
                )
            else:
                event = remaining[0]
                if not str(event.get("start_date_local") or "").startswith(
                    context.planned_date.isoformat()
                ) or event.get("name") != context.workout.get("name"):
                    raise AppError(
                        502,
                        "Der Kalender bestaetigt Datum oder Namen der reparierten Einheit nicht.",
                        reason="intervals_workout_verification_failed",
                    )
                planning_workouts.validate_intervals_workout_result(
                    context.workout, event
                )
                verified = event
            with self._database_manager.unit_of_work() as db:
                current = db.execute(
                    "SELECT payload FROM planned_units WHERE local_id=?",
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
