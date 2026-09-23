"""Targeted Intervals performance refresh use case."""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import COACH_ABORTED_ERROR, INTERVALS_API_KEY_ERROR, AppError
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.queue import SyncJobQueueService
from backend.sync.snapshots import merge_performance_snapshot
from backend.sync.state import SyncStateRepository

# ponytail: process-wide lock; per-account locks if multi-athlete isolation is added.
_PERFORMANCE_REFRESH_LOCK = threading.Lock()


class PerformanceRefreshService:
    """Fetch performance data outside a transaction and merge it atomically."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        sync_state_repository: SyncStateRepository,
        key_value_repository: KeyValueRepository,
        provider_client: Any,
        event_publisher: Any,
        redactor: Callable[[str], str],
        logger: logging.Logger,
        observer: SyncOperationObserver,
        provider_resync_gate: ProviderResyncGate,
        lock: Any = _PERFORMANCE_REFRESH_LOCK,
    ):
        self._config = config
        self._database_manager = database_manager
        self._sync_state_repository = sync_state_repository
        self._key_value_repository = key_value_repository
        self._provider_client = provider_client
        self._event_publisher = event_publisher
        self._redactor = redactor
        self._logger = logger
        self._observer = observer
        self._provider_resync_gate = provider_resync_gate
        self._lock = lock

    def running(self) -> bool:
        return self._lock.locked()

    def refresh(self) -> dict[str, Any]:
        with (
            self._observer.observe("intervals", "performance") as scope,
            self._provider_resync_gate.operation(),
        ):
            result = self._refresh_inner()
            scope.result = result
            return result

    def _refresh_inner(self) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)
        if not self._lock.acquire(blocking=False):
            return {"status": "already_running"}

        try:
            self._set_value("performance_refresh_running", "1")
            provider_snapshot = self._provider_client.fetch_performance_snapshot(
                self._sync_state_repository.latest_snapshot()
            )
            with self._database_manager.unit_of_work() as db:
                merged = merge_performance_snapshot(
                    self._sync_state_repository.latest_snapshot(), provider_snapshot
                )
                self._sync_state_repository.save_snapshot(
                    merged, update_full_sync=False
                )
                self._key_value_repository.set(db, "last_performance_error", "")

            self._publish_ready()
            return {"status": "ok", "refreshed_at": merged["synced_at"]}
        except Exception as exc:
            error = self._redacted_error(exc)
            try:
                self._set_value("last_performance_error", error)
            except Exception:  # noqa: BLE001
                self._log_sanitized(
                    "Unable to persist performance refresh error", error, exc
                )
            self._log_sanitized("Performance refresh failed", error, exc)
            raise
        finally:
            had_error = sys.exc_info()[0] is not None
            try:
                self._set_value("performance_refresh_running", "0")
            except Exception as cleanup_error:
                self._log_sanitized(
                    "Unable to clear performance refresh running marker",
                    self._redacted_error(cleanup_error),
                    cleanup_error,
                )
                if not had_error:
                    raise
            finally:
                self._lock.release()

    def _set_value(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)

    def _publish_ready(self) -> None:
        payload = {"provider": "intervals", "area": "performance", "status": "ready"}
        publish = getattr(self._event_publisher, "publish", None)
        if publish is not None:
            publish("provider", payload)
        else:
            self._event_publisher("provider", payload)

    def _redacted_error(self, exc: Exception) -> str:
        try:
            return str(self._redactor(str(exc)))[:1000]
        except Exception:  # noqa: BLE001
            return "Performance refresh failed"

    def _log_sanitized(self, message: str, error: str, exc: Exception) -> None:
        safe_exc = RuntimeError(error)
        self._logger.error(
            message,
            extra={"event": "performance_refresh_failed"},
            exc_info=(RuntimeError, safe_exc, exc.__traceback__),
        )


class PerformanceRefreshFollowupService:
    """Queue and observe the independent performance refresh after sync."""

    def __init__(
        self,
        config: Config,
        queue_service: SyncJobQueueService,
        performance_refresh_service: PerformanceRefreshService,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        logger: logging.Logger,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        wait_seconds: float = 120.0,
        poll_seconds: float = 1.0,
    ) -> None:
        self._config = config
        self._queue_service = queue_service
        self._performance_refresh_service = performance_refresh_service
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._logger = logger
        self._monotonic = monotonic
        self._sleep = sleep
        self._wait_seconds = wait_seconds
        self._poll_seconds = poll_seconds

    def enqueue_after_sync(self, reason: str) -> dict[str, Any] | None:
        """Queue a follow-up without changing the durable activity-sync result."""
        if (
            not self._config.intervals_api_key
            or self._performance_refresh_service.running()
        ):
            return None
        try:
            return self._queue_service.enqueue(
                "intervals",
                "performance_refresh",
                {
                    "reason": "Automatische Folgeaktualisierung nach "
                    f"{str(reason or 'Intervals-Sync')[:80]}"
                },
                requested_by="scheduler",
            )
        except Exception:  # noqa: BLE001 - follow-up failure must not fail activity sync
            self._logger.warning(
                "Automatic Intervals performance refresh could not be queued",
                extra={"event": "automatic_performance_refresh_queue_failed"},
            )
            return None

    def wait(
        self,
        job_id: str | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any] | None:
        """Wait for the active performance refresh, respecting cancellation."""
        deadline = self._monotonic() + self._wait_seconds
        active_job_id = job_id
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")

            state, value = self._poll_state(active_job_id)
            if state == "completed":
                return value
            if state == "job":
                active_job_id = str(value)
            elif state == "idle":
                return None

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise AppError(
                    503,
                    "Die aktuelle Intervals.icu-Leistungsaktualisierung ist noch nicht abgeschlossen.",
                    reason="provider_busy",
                )
            self._sleep(min(self._poll_seconds, remaining))

    def _poll_state(
        self, active_job_id: str | None
    ) -> tuple[str, dict[str, Any] | str | None]:
        if active_job_id:
            state = self._queue_service.state(active_job_id)
            if state["status"] == "completed":
                return "completed", state
            if state["status"] in {"failed", "partial"}:
                self._raise_refresh_failed()
            return "waiting", None

        pending_id = self._queue_service.pending_performance_job_id()
        if pending_id:
            return "job", pending_id
        if self._get_value("performance_refresh_running") == "1":
            return "waiting", None
        if self._get_value("last_performance_error"):
            self._raise_refresh_failed()
        return "idle", None

    def _get_value(self, key: str) -> str | None:
        with self._database_manager.unit_of_work() as db:
            return self._key_value_repository.get(db, key)

    @staticmethod
    def _raise_refresh_failed() -> None:
        raise AppError(
            503,
            "Die aktuelle Intervals.icu-Leistungsaktualisierung ist fehlgeschlagen.",
            reason="provider_refresh_failed",
        )
