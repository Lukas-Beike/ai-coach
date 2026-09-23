"""Synchronize explicitly selected workout library and planned entries."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.planning import library as planning_library
from backend.sync.gates import INTERVALS_RESYNC_GATE, ProviderResyncGate
from backend.sync.intervals_lock import INTERVALS_SYNC_LOCK
from backend.sync.library import WorkoutLibrarySyncService
from backend.sync.planned_calendar import (
    PlannedCalendarRepairBatch,
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)

INTERVALS_SYNC_WAIT_SECONDS = 120
_REPAIR_LOCK_ERROR = (
    "Der Hintergrund-Sync ist noch aktiv. Reparatur wird erneut versucht."
)
_RETRY_SCOPE = "Nur fehlgeschlagene Objekte erneut auswählen."


class SelectedWorkoutSyncService:
    """Own the selected library/planned-unit batch synchronization workflow."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        workout_library_sync_service: WorkoutLibrarySyncService,
        planned_calendar_sync_service: PlannedCalendarSyncService,
        planned_calendar_repair_service: PlannedCalendarRepairService,
        redactor: Callable[[str], str],
        lock: Any = INTERVALS_SYNC_LOCK,
        wait_seconds: float = INTERVALS_SYNC_WAIT_SECONDS,
        provider_resync_gate: ProviderResyncGate = INTERVALS_RESYNC_GATE,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._workout_library_sync_service = workout_library_sync_service
        self._planned_calendar_sync_service = planned_calendar_sync_service
        self._planned_calendar_repair_service = planned_calendar_repair_service
        self._redact = redactor
        self._lock = lock
        self._wait_seconds = wait_seconds
        self._provider_resync_gate = provider_resync_gate

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("repair"):
            if not self._lock.acquire(timeout=self._wait_seconds):
                raise AppError(503, _REPAIR_LOCK_ERROR, reason="temporary_error")
            try:
                return self._sync_unlocked(payload)
            finally:
                self._lock.release()
        return self._sync_unlocked(payload)

    def _sync_unlocked(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)
        requested = planning_library.library_bulk_request_entries(
            payload.get("entries"), require_hash=True
        )
        repair = bool(payload.get("repair"))
        repair_service = self._planned_calendar_repair_service if repair else None
        repair_batch = (
            repair_service.create_batch(requested) if repair_service else None
        )
        results = [
            self._sync_entry(item, payload, repair_service, repair_batch)
            for item in requested
        ]
        self._verify_repair(results, repair_service, repair_batch)
        failed = [
            item["library_workout_id"]
            for item in results
            if item["status"] in {"error", "conflict"}
        ]
        if not failed:
            status = "ok"
        elif len(failed) < len(results):
            status = "partial"
        else:
            status = "error"
        return {
            "ok": not failed,
            "status": status,
            "results": results,
            "failed_object_ids": failed,
            "retry_scope": _RETRY_SCOPE if failed else None,
        }

    def _selected_row(self, local_id: str) -> tuple[dict[str, Any] | None, bool]:
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT payload, sync_state FROM workout_library WHERE local_id=?",
                (local_id,),
            ).fetchone()
            if row:
                return row, False
            row = db.execute(
                "SELECT payload, sync_state FROM planned_units WHERE local_id=?",
                (local_id,),
            ).fetchone()
        return row, bool(row)

    def _error(self, local_id: str, error: Exception) -> dict[str, Any]:
        return {
            "library_workout_id": local_id,
            "status": "error",
            "error": self._redact(str(error))[:500],
        }

    def _sync_planned_entry(
        self,
        item: dict[str, Any],
        payload: dict[str, Any],
        repair_service: PlannedCalendarRepairService | None,
        repair_batch: PlannedCalendarRepairBatch | None,
    ) -> dict[str, Any]:
        local_id = item["library_workout_id"]
        try:
            if payload.get("repair"):
                event = repair_service.repair_entry(
                    local_id, item["expected_payload_hash"], batch=repair_batch
                )
            else:
                event = self._planned_calendar_sync_service.sync_entry(local_id)
        except Exception as exc:  # noqa: BLE001 - isolate each selected entry
            if repair_service is not None:
                repair_service.record_error(local_id, str(exc))
            return self._error(local_id, exc)
        return {
            "library_workout_id": local_id,
            "status": "synced",
            "calendar_synced": event is not None
            or bool(payload.get("repair") and repair_batch),
        }

    def _sync_existing_library_calendar_entry(
        self, item: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any]:
        local_id = item["library_workout_id"]
        try:
            synced = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            synced = {}
        if (
            not isinstance(synced, dict)
            or not synced.get("date")
            or synced.get("remote_event_id")
        ):
            return {"library_workout_id": local_id, "status": "already_synced"}
        try:
            with self._provider_resync_gate.operation():
                self._workout_library_sync_service.sync_calendar_entry(local_id, synced)
        except Exception as exc:  # noqa: BLE001 - isolate each selected entry
            return self._error(local_id, exc)
        return {
            "library_workout_id": local_id,
            "status": "synced",
            "calendar_synced": True,
        }

    def _sync_pending_library_entry(self, item: dict[str, Any]) -> dict[str, Any]:
        local_id = item["library_workout_id"]
        try:
            with self._provider_resync_gate.operation():
                synced = self._workout_library_sync_service.sync_entry(local_id)
            with self._provider_resync_gate.operation():
                calendar_event = self._workout_library_sync_service.sync_calendar_entry(
                    local_id, synced
                )
        except Exception as exc:  # noqa: BLE001 - isolate each selected entry
            return self._error(local_id, exc)
        return {
            "library_workout_id": local_id,
            "status": "synced",
            "external_id": bool(synced.get("external_id")),
            "calendar_synced": calendar_event is not None,
        }

    def _sync_entry(
        self,
        item: dict[str, Any],
        payload: dict[str, Any],
        repair_service: PlannedCalendarRepairService | None,
        repair_batch: PlannedCalendarRepairBatch | None,
    ) -> dict[str, Any]:
        local_id = item["library_workout_id"]
        row, is_planned = self._selected_row(local_id)
        if not row:
            return {
                "library_workout_id": local_id,
                "status": "conflict",
                "error": "Einheit nicht gefunden",
            }
        if (
            planning_library.library_payload_hash(row["payload"])
            != item["expected_payload_hash"]
        ):
            return {
                "library_workout_id": local_id,
                "status": "conflict",
                "error": "Seit der Vorschau geändert",
            }
        if is_planned:
            return self._sync_planned_entry(item, payload, repair_service, repair_batch)
        if row.get("sync_state") == "synced":
            return self._sync_existing_library_calendar_entry(item, row)
        return self._sync_pending_library_entry(item)

    def _verify_repair(
        self,
        results: list[dict[str, Any]],
        repair_service: PlannedCalendarRepairService | None,
        repair_batch: PlannedCalendarRepairBatch | None,
    ) -> None:
        if not repair_batch:
            return
        verification = repair_batch.verify()
        for item in results:
            error = verification.get(item["library_workout_id"])
            if error is not None:
                repair_service.record_error(item["library_workout_id"], str(error))
                item.update(
                    status="error",
                    error=self._redact(str(error))[:500],
                    calendar_synced=False,
                )
