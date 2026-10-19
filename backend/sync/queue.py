"""Control-plane operations for persistent sync jobs."""

from __future__ import annotations

import threading
from typing import Any

from backend.activities.activity_reference import (
    ActivityReferenceResolver,
    NoActivityReferences,
)
from backend.errors import AppError
from backend.providers.descriptors import INTERVALS_ID
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
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


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
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
        references: ActivityReferenceResolver | None = None,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._maintenance_gate = maintenance_gate
        self._wake_event = wake_event
        self._all_sync_days = all_sync_days
        self._daily_sync_markers = daily_sync_markers
        self._registry = registry
        self._references = NoActivityReferences() if references is None else references

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

    def backfill_continued(
        self, provider: str, end_date: str, created_since: str
    ) -> bool:
        return self._store.has_backfill_continuation(provider, end_date, created_since)

    def pending_performance_job_id(self, provider: str) -> str | None:
        return self._store.pending_performance_job_id(provider)

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
            payload = self._resolve_activity_reference(provider, job_type, payload)
            try:
                envelope = normalize_sync_job_request(
                    provider,
                    job_type,
                    payload,
                    all_sync_days=self._all_sync_days,
                    registry=self._registry,
                    enforce_period_limit=True,
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
            requested = (
                str(requested_by or "system").strip().casefold()[:40] or "system"
            )
            if (
                requested in {"startup", "scheduler"}
                and envelope["type"] == "refresh"
                and envelope["provider"] in self._registry.daily_marker_ids()
            ):
                self._daily_sync_markers.mark_attempt(envelope["provider"])
            return result

    def _resolve_activity_reference(
        self, provider: str, job_type: str, payload: Any
    ) -> Any:
        """Store Intervals activity jobs under the provider id so duplicates coalesce.

        Garmin ids are already provider ids, so their payloads pass unchanged.
        """
        if (
            provider != INTERVALS_ID
            or job_type != "activity_details"
            or not isinstance(payload, dict)
            or "activity_id" not in payload
        ):
            return payload
        return {
            **payload,
            "activity_id": self._references.resolve(payload["activity_id"]),
        }

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
