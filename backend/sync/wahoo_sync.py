"""Read-only Wahoo workout synchronization into the canonical tables.

One run fetches the workouts of a bounded window, plans the canonical rows and
writes them in a single unit of work together with the coverage summary, the
daily refresh marker and the freshness state. A failure at any step rolls the
whole write back, so stored canonical rows, coverage and freshness never
disagree. Nothing is ever written to Wahoo.

A run without a Wahoo client configuration or without a connected athlete skips
with the descriptor's not-configured message. Errors that reach the stored
state, the logs or the caller carry no provider payload and no token.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Final, Protocol

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.canonical_plans import (
    WAHOO_SYNCED_AT_KEY,
    WAHOO_WORKOUTS_KEY,
    wahoo_ingest_plan,
)
from backend.providers.descriptors import WAHOO_ID, WAHOO_NOT_CONFIGURED_MESSAGE
from backend.providers.wahoo_client import WahooWorkoutFetch
from backend.sync.canonical_coverage_store import (
    CanonicalCoverageStore,
    wahoo_payload_coverage,
)
from backend.sync.canonical_ingest import ingest_plan
from backend.sync.daily import DailySyncMarkerService
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_registry import ProviderRegistry

FRESHNESS_AREA: Final = "activities"
LAST_SYNC_KEY: Final = "last_wahoo_sync_at"
LAST_ERROR_KEY: Final = "last_wahoo_sync_error"
SYNC_FAILED_MESSAGE: Final = "Die Wahoo-Synchronisierung ist fehlgeschlagen."

WAHOO_SYNC_LOCK = threading.Lock()


def shared_wahoo_sync_lock() -> threading.Lock:
    """Return the process-wide lock that serializes Wahoo synchronization."""
    return WAHOO_SYNC_LOCK


class WahooWorkoutSource(Protocol):
    """The read transport the sync needs, injected so tests use a fake."""

    def list_workouts(
        self, *, since: datetime, until: datetime | None = None
    ) -> WahooWorkoutFetch: ...


class WahooConnectionStatus(Protocol):
    """The token-free connection status the sync consults."""

    def status(self) -> Mapping[str, Any]: ...


def sync_window_days(registry: ProviderRegistry, requested: object) -> int:
    """Clamp a requested window to the descriptor's limits.

    A missing or invalid request uses the descriptor's default window.
    """
    maximum = registry.max_sync_days(WAHOO_ID)
    default = registry.sync_period_defaults().get(WAHOO_ID, maximum)
    if isinstance(requested, bool) or not isinstance(requested, int):
        return max(1, min(default, maximum))
    return max(1, min(requested, maximum))


class WahooSyncService:
    """Own the Wahoo read synchronization lifecycle."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        connection: Callable[[], WahooConnectionStatus],
        source: Callable[[], WahooWorkoutSource],
        database_manager: Callable[[], DatabaseManager],
        database_lock: AbstractContextManager[Any],
        key_values: KeyValueRepository,
        daily_markers: Callable[[], DailySyncMarkerService],
        observer: Callable[[], SyncOperationObserver],
        registry: ProviderRegistry,
        zone_provider: Callable[[], tzinfo | None],
        now: Callable[[], datetime],
        logger: logging.Logger,
        lock: Any | None = None,
    ) -> None:
        self._config = config
        self._connection = connection
        self._source = source
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._coverage = CanonicalCoverageStore(key_values)
        self._daily_markers = daily_markers
        self._observer = observer
        self._registry = registry
        self._zone_provider = zone_provider
        self._now = now
        self._logger = logger
        self._lock = lock if lock is not None else WAHOO_SYNC_LOCK

    def running(self) -> bool:
        return self._lock.locked()

    def configured(self) -> bool:
        """Return whether a Wahoo client is configured and an athlete is connected."""
        if not self._config().wahoo_configured:
            return False
        return bool(self._connection().status().get("connected"))

    def sync(
        self,
        days: object = None,
        reason: str = "manual",
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        with self._observer().observe(
            WAHOO_ID, FRESHNESS_AREA, reason, operation_id
        ) as scope:
            result = self._sync(days, reason)
            scope.result = result
            return result

    def _sync(self, days: object, reason: str) -> dict[str, Any]:
        if not self.configured():
            return {"status": "not_configured", "message": WAHOO_NOT_CONFIGURED_MESSAGE}
        if not self._lock.acquire(blocking=False):
            return {"status": "already_running"}
        try:
            try:
                return self._sync_locked(sync_window_days(self._registry, days))
            except AppError as error:
                self._record_error(error.message)
                self._log_failure(reason, error)
                raise
            except Exception as error:  # noqa: BLE001 - every failure is stored content-free
                self._record_error(SYNC_FAILED_MESSAGE)
                self._log_failure(reason, error)
                raise AppError(
                    502, SYNC_FAILED_MESSAGE, reason="wahoo_sync_failed"
                ) from None
        finally:
            self._lock.release()

    def _sync_locked(self, days: int) -> dict[str, Any]:
        zone = self._zone_provider() or UTC
        synced_at = self._now()
        fetch = self._source().list_workouts(
            since=synced_at - timedelta(days=days), until=synced_at
        )
        payload = {
            WAHOO_SYNCED_AT_KEY: synced_at.isoformat(),
            WAHOO_WORKOUTS_KEY: list(fetch.workouts),
        }
        plan = wahoo_ingest_plan(payload, zone=zone)
        with self._database_lock, self._database_manager().unit_of_work() as db:
            counters = ingest_plan(
                db, plan, retrieved_at=synced_at, deletion_window=None, zone=zone
            )
            self._coverage.persist(
                db, wahoo_payload_coverage(payload, zone=zone), zone=zone
            )
            self._key_values.set(db, LAST_SYNC_KEY, synced_at.isoformat())
            self._key_values.set(db, LAST_ERROR_KEY, "")
            self._daily_markers().mark_in_transaction(db, WAHOO_ID)
        return {
            "status": "partial" if fetch.truncated else "ok",
            "synced_at": synced_at.isoformat(),
            "activities": len(plan.activities),
            "window_days": days,
            "skipped": fetch.skipped + counters.skipped_invalid,
            "canonical": counters.as_dict(),
        }

    def _record_error(self, message: str) -> None:
        """Store the content-free error text; a failed write never hides the cause."""
        try:
            with self._database_lock, self._database_manager().unit_of_work() as db:
                self._key_values.set(db, LAST_ERROR_KEY, message)
        except Exception:  # noqa: BLE001 - a failed write must not hide the cause
            self._logger.warning(
                "Wahoo sync error could not be stored",
                extra={"event": "wahoo_sync_error_not_stored"},
            )

    def _log_failure(self, reason: str, error: BaseException) -> None:
        """Log the failure class only: no traceback, message or provider content."""
        self._logger.warning(
            "Wahoo synchronization failed",
            extra={
                "event": "wahoo_sync_failed",
                "context": {
                    "reason": reason,
                    "error_type": type(error).__name__,
                    "error_code": getattr(error, "reason", None),
                },
            },
        )
