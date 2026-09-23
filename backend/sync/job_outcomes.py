"""Outcome and retry handling for claimed synchronization jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any

from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.sync.jobs import SyncJobInvalidOperationError, SyncJobStore, retry_delay
from backend.sync.refresh import sync_job_error_class


class SyncJobOutcomeService:
    """Persist, publish, and retry outcomes for claimed sync jobs."""

    def __init__(
        self,
        job_store: SyncJobStore,
        publisher: StateEventBuffer,
        wake_event: Event,
        redactor: Callable[[str], str],
        logger: logging.Logger,
        current_time: Callable[[], datetime],
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> None:
        self._job_store = job_store
        self._publisher = publisher
        self._wake_event = wake_event
        self._redactor = redactor
        self._logger = logger
        self._current_time = current_time
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    def complete(self, job_id: str, result: Any) -> str:
        """Persist the result and return its legacy fallback status."""
        result_status = result.get("status") if isinstance(result, dict) else "ok"
        if result_status == "already_running":
            raise AppError(
                409, "Der Provider ist noch beschäftigt.", reason="temporary_error"
            )
        fallback_status = (
            "partial"
            if result_status == "partial"
            else "failed"
            if result_status in {"error", "failed"}
            else "completed"
        )
        snapshot = self._job_store.update_from_result(
            job_id, result, fallback_status, self._redactor
        )
        self._publish(snapshot)
        return fallback_status

    def update(
        self,
        job_id: str,
        item_status: str,
        *,
        error_class: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        """Update all job items and publish the resulting job snapshot."""
        try:
            snapshot = self._job_store.update(
                job_id, item_status, error_class, error_detail
            )
        except SyncJobInvalidOperationError as exc:
            raise ValueError("invalid sync item status") from exc
        self._publish(snapshot)

    def record_failure(self, job: dict[str, Any], exc: BaseException) -> None:
        """Requeue a retryable failure or persist and log its final outcome."""
        error_class = sync_job_error_class(exc)
        detail = self._redactor(str(getattr(exc, "message", "") or exc))[:500]
        attempt = int(job.get("attempts") or 1)
        delay = retry_delay(
            attempt,
            base_seconds=self._retry_base_seconds,
            max_seconds=self._retry_max_seconds,
        )
        current_time = self._current_time()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        available_at = (
            current_time.astimezone(timezone.utc) + timedelta(seconds=delay)
        ).isoformat()
        if self._job_store.requeue(job, error_class, detail, available_at):
            self._wake_event.set()
            return

        self.update(
            str(job["id"]),
            "failed",
            error_class=error_class,
            error_detail=detail,
        )
        self._logger.error(
            "Persistent synchronization job failed",
            extra={
                "event": "sync_job_failed",
                "context": {
                    "job_id": job["id"],
                    "provider": job.get("provider"),
                    "type": job.get("type"),
                    "error_class": error_class,
                },
            },
        )

    def _publish(self, snapshot: dict[str, Any] | None) -> None:
        if snapshot is not None:
            self._publisher.publish("job", snapshot)
