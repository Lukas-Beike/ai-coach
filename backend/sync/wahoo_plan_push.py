"""Explicit export of selected local library workouts to Wahoo plans.

Runs only from a ``plan_push`` job that names Wahoo as its provider, which the
athlete starts through the library synchronization action. Every selected
workout is validated and mapped locally before the first remote write, so a
Wahoo that is not connected, or a request that is stale, writes nothing. The
Wahoo plan id lives in ``remote_links`` (provider ``wahoo``); the Intervals.icu
slots of the library row are never touched. A second run updates the plan it
created instead of uploading a duplicate.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState
from backend.db import DatabaseManager
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.providers.descriptors import WAHOO_ID, WAHOO_NOT_CONFIGURED_MESSAGE
from backend.providers.wahoo_client import WahooReconnectRequiredError
from backend.sync.gates import ProviderResyncGate
from backend.sync.wahoo_workout_export import WahooWorkoutExport

_RETRY_SCOPE = "Nur fehlgeschlagene Objekte erneut auswählen."
_REMOTE_LINKS = RemoteLinkRepository()


class WahooPlanPushService:
    """Export the selected library workouts as Wahoo plans, create or update."""

    def __init__(
        self,
        *,
        configured: Callable[[], bool],
        database_manager: Callable[[], DatabaseManager],
        export: Callable[[], WahooWorkoutExport],
        now: Callable[[], datetime],
        redactor: Callable[[str], str],
        gate: ProviderResyncGate | None = None,
    ) -> None:
        self._configured = configured
        self._database_manager = database_manager
        self._export = export
        self._now = now
        self._redact = redactor
        self._gate = gate
        self._lock = threading.Lock()

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("repair"):
            raise AppError(
                400,
                "Die Reparatur ist für Wahoo nicht verfügbar.",
                reason="invalid_job_request",
            )
        if not self._configured():
            raise AppError(409, WAHOO_NOT_CONFIGURED_MESSAGE, reason="not_configured")
        requested = planning_library.library_bulk_request_entries(
            payload.get("entries"), require_hash=True
        )
        # The gate rejects remote writes while a Wahoo resync reset holds it.
        operation = self._gate.operation() if self._gate is not None else nullcontext()
        with operation, self._lock:
            results = self._run(requested)
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

    def _run(self, requested: list[dict[str, Any]]) -> list[dict[str, Any]]:
        export = self._export()
        results: dict[str, dict[str, Any]] = {}
        prepared: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for item in requested:
            local_id = item["library_workout_id"]
            outcome = self._prepare(export, item)
            if isinstance(outcome, tuple):
                workout, envelope = outcome
                prepared.append((item, workout, envelope))
            else:
                results[local_id] = outcome
        remote_plans: list[dict[str, Any]] | None = None
        for item, workout, envelope in prepared:
            local_id = item["library_workout_id"]
            try:
                if remote_plans is None and self._needs_lookup(local_id):
                    remote_plans = export.library_list()
                results[local_id] = self._write(
                    export, local_id, item, workout, envelope, remote_plans or []
                )
            except WahooReconnectRequiredError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate each selected entry
                results[local_id] = self._error(local_id, exc)
        return [results[item["library_workout_id"]] for item in requested]

    def _prepare(
        self, export: WahooWorkoutExport, item: dict[str, Any]
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        local_id = item["library_workout_id"]
        with self._database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT payload FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()
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
        try:
            stored = json.loads(row["payload"] or "{}")
            workout = {**stored, "local_id": local_id}
            return workout, export.serialize_library(workout)
        except Exception as exc:  # noqa: BLE001 - isolate each selected entry
            return self._error(local_id, exc)

    def _needs_lookup(self, local_id: str) -> bool:
        """Return whether a create must first look for an earlier upload."""
        with self._database_manager().unit_of_work() as db:
            link = _REMOTE_LINKS.get(
                db, RemoteEntityKind.LIBRARY_WORKOUT, local_id, WAHOO_ID
            )
        return link is None or not link.remote_id

    def _write(
        self,
        export: WahooWorkoutExport,
        local_id: str,
        item: dict[str, Any],
        workout: dict[str, Any],
        envelope: dict[str, Any],
        remote_plans: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._database_manager().unit_of_work() as db:
            link = _REMOTE_LINKS.get(
                db, RemoteEntityKind.LIBRARY_WORKOUT, local_id, WAHOO_ID
            )
        remote_id = link.remote_id if link else None
        if not remote_id:
            remote_id = _earlier_upload(remote_plans, envelope["external_id"])
        saved: dict[str, Any] | None = None
        if remote_id:
            try:
                saved = export.library_update(remote_id, envelope)
            except AppError as exc:
                if exc.upstream_status != 404:
                    raise
        if saved is None:
            created = export.library_create([envelope])
            saved = created[0] if created else {}
        export.verify_library_readback(workout, saved)
        stored_id = str(saved["id"])
        with self._database_manager().unit_of_work() as db:
            _REMOTE_LINKS.upsert(
                db,
                RemoteLink(
                    entity_kind=RemoteEntityKind.LIBRARY_WORKOUT,
                    local_id=local_id,
                    provider=WAHOO_ID,
                    sync_state=RemoteLinkState.SYNCED,
                    remote_id=stored_id,
                    remote_external_id=envelope["external_id"],
                    baseline_hash=item["expected_payload_hash"],
                    last_synced_at=self._now().astimezone(UTC).isoformat(),
                ),
            )
        return {
            "library_workout_id": local_id,
            "status": "synced",
            "remote_id": stored_id,
        }

    def _error(self, local_id: str, error: Exception) -> dict[str, Any]:
        return {
            "library_workout_id": local_id,
            "status": "error",
            "error": self._redact(str(error))[:500],
        }


def _earlier_upload(plans: list[dict[str, Any]], external_id: str) -> str | None:
    for plan in plans:
        if str(plan.get("external_id") or "") == external_id and plan.get("id"):
            return str(plan["id"])
    return None
