"""Synchronize explicitly selected workout library and planned entries."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager, planning_store
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.planning import library as planning_library
from backend.planning import planned_units
from backend.planning.push_state import INTERVALS_INDOOR_RIDES_ONLY, skips_intervals
from backend.sync.gates import ProviderResyncGate
from backend.sync.library import WorkoutLibrarySyncService
from backend.sync.planned_calendar import (
    PlannedCalendarRepairBatch,
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
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
        provider_resync_gate: ProviderResyncGate,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._workout_library_sync_service = workout_library_sync_service
        self._planned_calendar_sync_service = planned_calendar_sync_service
        self._planned_calendar_repair_service = planned_calendar_repair_service
        self._redact = redactor
        self._provider_resync_gate = provider_resync_gate

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR, reason="not_configured")
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
            row = planning_store.library_row(db, local_id)
            if row:
                return row, False
            row = planning_store.planned_unit_row(db, local_id)
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
        unit_payload: str,
        repair_service: PlannedCalendarRepairService | None,
        repair_batch: PlannedCalendarRepairBatch | None,
    ) -> dict[str, Any]:
        local_id = item["library_workout_id"]
        try:
            if skips_intervals(json.loads(unit_payload)):
                # The one gate for every Intervals.icu write of a planned unit (#2419).
                return {
                    "library_workout_id": local_id,
                    "status": "skipped",
                    "error": INTERVALS_INDOOR_RIDES_ONLY,
                }
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
        except TypeError, ValueError:
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
            if str(synced.get("sync_status") or "synced") != "synced":
                # A local edit landed during the remote call; the remote copy is
                # stale, so do not write the calendar from the newer local payload.
                return {
                    "library_workout_id": local_id,
                    "status": "conflict",
                    "error": "Seit der Vorschau geändert",
                }
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
        if not planned_units.plan_push_hash_matches(
            row["payload"], item["expected_payload_hash"]
        ):
            return {
                "library_workout_id": local_id,
                "status": "conflict",
                "error": "Seit der Vorschau geändert",
            }
        if is_planned:
            return self._sync_planned_entry(
                item, payload, row["payload"], repair_service, repair_batch
            )
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
