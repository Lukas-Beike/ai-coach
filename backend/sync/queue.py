"""Control-plane operations for persistent sync jobs."""

from __future__ import annotations

import threading
from typing import Any

from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.jobs import (
    SYNC_JOB_LIST_LIMIT,
    JobValidationError,
    SyncJobInvalidOperationError,
    SyncJobInvalidStateError,
    SyncJobNotFoundError,
    SyncJobStore,
    normalize_sync_job_request,
)


class SyncJobQueueService:
    """Expose durable sync-job queue state and explicit queue operations."""

    def __init__(
        self,
        store: SyncJobStore,
        publisher: StateEventBuffer,
        maintenance_gate: MaintenanceGate,
        wake_event: threading.Event,
        all_sync_days: int,
        daily_sync_markers: DailySyncMarkerService,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._maintenance_gate = maintenance_gate
        self._wake_event = wake_event
        self._all_sync_days = all_sync_days
        self._daily_sync_markers = daily_sync_markers

    def state(self, job_id: str) -> dict[str, Any]:
        """Return one job or the existing localized not-found error."""
        job = self._store.state(job_id)
        if not job:
            raise AppError(
                404,
                "Synchronisationsjob nicht gefunden.",
                reason="sync_job_not_found",
            )
        return job

    def list(self, limit: int = SYNC_JOB_LIST_LIMIT) -> list[dict[str, Any]]:
        return self._store.list(limit)

    def active(self, provider: str, job_type: str = "refresh") -> bool:
        return self._store.active(provider, job_type)

    def pending_performance_job_id(self) -> str | None:
        return self._store.pending_performance_job_id()

    def enqueue(
        self,
        provider: str,
        job_type: str = "refresh",
        payload: Any = None,
        *,
        requested_by: str = "system",
        item_operations: list[dict[str, Any]] | None = None,
        available_at: str | None = None,
    ) -> dict[str, Any]:
        """Validate and persist a job while maintenance drains all side effects."""
        with self._maintenance_gate.operation():
            try:
                envelope = normalize_sync_job_request(
                    provider, job_type, payload, all_sync_days=self._all_sync_days
                )
            except JobValidationError as exc:
                raise AppError(400, str(exc), reason="invalid_job_request") from exc
            try:
                result, created = self._store.enqueue(
                    envelope, requested_by, item_operations, available_at
                )
            except SyncJobInvalidOperationError as exc:
                raise AppError(400, str(exc), reason="invalid_job_request") from exc
            if created:
                self._wake_event.set()
                self._publish_created_sync_job(result["id"], result)
            requested = str(requested_by or "system").strip().casefold()[:40] or "system"
            if (
                requested in {"startup", "scheduler"}
                and envelope["type"] == "refresh"
                and envelope["provider"] in {"intervals", "garmin", "calendar"}
            ):
                self._daily_sync_markers.mark_attempt(envelope["provider"])
            return result

    def resume_interrupted(self) -> int:
        """Make interrupted jobs eligible and wake the worker only when needed."""
        resumed = self._store.resume_interrupted()
        if resumed:
            self._wake_event.set()
        return resumed

    def resolve(self, job_id: str, payload: Any) -> dict[str, Any]:
        """Explicitly requeue a failed or partial job for another attempt."""
        if (
            not isinstance(payload, dict)
            or str(payload.get("action") or "").strip().casefold() != "retry"
        ):
            raise AppError(
                400,
                "Ein Job kann nur ausdrücklich mit action=retry erneut gestartet werden.",
                reason="invalid_job_resolution",
            )
        try:
            result = self._store.resolve(job_id)
        except SyncJobNotFoundError as exc:
            raise AppError(
                404,
                "Synchronisationsjob nicht gefunden.",
                reason="sync_job_not_found",
            ) from exc
        except SyncJobInvalidStateError as exc:
            raise AppError(
                409,
                "Nur fehlgeschlagene oder teilweise Jobs können erneut gestartet werden.",
                reason="invalid_job_resolution",
            ) from exc
        self._wake_event.set()
        return result

    def _publish_created_sync_job(self, job_id: str, result: dict[str, Any]) -> None:
        self._publisher.publish(
            "job",
            {
                "job_id": job_id,
                "provider": result["provider"],
                "type": result["type"],
                "status": result["status"],
                "progress": result["progress"],
            },
        )
