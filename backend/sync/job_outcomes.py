"""Outcome and retry handling for claimed synchronization jobs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any

from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.sync.jobs import SyncJobInvalidOperationError, SyncJobStore, retry_delay
from backend.sync.refresh import sync_job_error_class

# A job that meets a busy provider lock retries soon and keeps its attempts. A
# lock held for longer than the age limit fails the job as before.
CONTENTION_RETRY_SECONDS = 30
CONTENTION_MAX_AGE = timedelta(minutes=30)
CONTENDED_STATUS = "queued"


# First collision per job id; the outcome service is built per request, so the
# map lives at module level for the single sync worker of this process.
_CONTENDED_SINCE: dict[str, datetime] = {}
_CONTENTION_LOCK = threading.Lock()


def _clear_contention(job_id: str) -> None:
    with _CONTENTION_LOCK:
        _CONTENDED_SINCE.pop(job_id, None)


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

    def complete(
        self, job_id: str, result: Any, *, job: Mapping[str, Any] | None = None
    ) -> str:
        """Persist the result and return its legacy fallback status.

        A result that met a busy provider lock requeues the claimed ``job`` after
        a short delay without consuming an attempt and returns ``"queued"``.
        Without a claimed job, or once the job has been contended longer than the
        age limit, it raises a temporary conflict for the normal retry path.
        """
        result_status = result.get("status") if isinstance(result, dict) else "ok"
        if result_status != "already_running":
            _clear_contention(str((job or {}).get("id") or job_id))
        if result_status == "already_running":
            if job is not None and self._defer_contended(job):
                return CONTENDED_STATUS
            raise AppError(
                409, "Der Provider ist noch beschäftigt.", reason="temporary_error"
            )
        if result_status == "partial":
            fallback_status = "partial"
        elif result_status in {"error", "failed"}:
            fallback_status = "failed"
        else:
            fallback_status = "completed"
        snapshot = self._job_store.update_from_result(
            job_id, result, fallback_status, self._redactor
        )
        self._publish(snapshot)
        return fallback_status

    def _defer_contended(self, job: Mapping[str, Any]) -> bool:
        current_time = self._utc(self._current_time())
        job_id = str(job.get("id") or "")
        # The bound counts from the first collision of this job, not from its
        # creation: a job that waited in the queue or retried earlier still
        # gets the short defers. Kept per process; a restart starts afresh.
        with _CONTENTION_LOCK:
            since = _CONTENDED_SINCE.setdefault(job_id, current_time)
        if current_time - since > CONTENTION_MAX_AGE:
            _clear_contention(job_id)
            return False
        available_at = (
            current_time + timedelta(seconds=CONTENTION_RETRY_SECONDS)
        ).isoformat()
        if not self._job_store.defer(job, available_at):
            return False
        self._wake_event.set()
        return True

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

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
        retry_after = getattr(exc, "retry_after_seconds", None)
        if type(retry_after) is int and retry_after > 0:
            # The provider named a wait: not earlier, and never past the cap.
            delay = max(delay, min(retry_after, self._retry_max_seconds))
        current_time = self._current_time()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            current_time = current_time.replace(tzinfo=UTC)
        available_at = (
            current_time.astimezone(UTC) + timedelta(seconds=delay)
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
