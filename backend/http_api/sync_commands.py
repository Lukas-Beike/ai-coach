"""Map authenticated synchronization POST requests to concrete sync use cases."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from backend.errors import AppError
from backend.sync.full_resync import FullProviderResyncService
from backend.sync.performance import PerformanceRefreshService
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository

SYNC_JOB_RESOLVE_RE = re.compile(r"^/api/sync/jobs/([0-9a-f-]+)/resolve$")
SYNC_POST_PATHS = frozenset({
    "/api/sync/jobs", "/api/sync", "/api/intervals/full-resync",
    "/api/performance/refresh", "/api/garmin/sync",
    "/api/external-calendar/sync", "/api/weather/sync",
    "/api/garmin/full-resync",
})
SYNC_BODY_PATHS = frozenset({
    "/api/sync/jobs", "/api/sync", "/api/garmin/sync",
    "/api/intervals/full-resync", "/api/garmin/full-resync",
})


class SyncCommandEndpoint:
    """Own validation and command execution behind the HTTP sync routes."""

    def __init__(
        self,
        queue: SyncJobQueueService,
        state: SyncStateRepository,
        performance: PerformanceRefreshService,
        full_resync: FullProviderResyncService,
        operation_id_factory: Callable[[], str],
        period_defaults: Mapping[str, int],
        all_sync_days: int,
    ) -> None:
        self._queue = queue
        self._state = state
        self._performance = performance
        self._full_resync = full_resync
        self._operation_id_factory = operation_id_factory
        self._period_defaults = period_defaults
        self._all_sync_days = all_sync_days

    @staticmethod
    def handles(path: str) -> bool:
        return path in SYNC_POST_PATHS or SYNC_JOB_RESOLVE_RE.match(path) is not None

    @staticmethod
    def needs_body(path: str) -> bool:
        return path in SYNC_BODY_PATHS or SYNC_JOB_RESOLVE_RE.match(path) is not None

    def execute(self, path: str, payload: Any = None) -> tuple[int, dict[str, Any]]:
        if path == "/api/sync/jobs":
            if not isinstance(payload, dict):
                raise AppError(400, "Ein Synchronisationsjob muss als Objekt gesendet werden.", reason="invalid_job_request")
            envelope = payload.get("payload")
            if envelope is None:
                envelope = {key: payload[key] for key in ("days", "force", "reason") if key in payload}
            return 202, self._queue.enqueue(
                payload.get("provider"), payload.get("type", "refresh"), envelope,
                requested_by="user",
            )
        if match := SYNC_JOB_RESOLVE_RE.match(path):
            return 200, self._queue.resolve(match.group(1), payload)
        if path == "/api/sync":
            return self._enqueue_manual_refresh("intervals", payload)
        if path == "/api/garmin/sync":
            return self._enqueue_manual_refresh("garmin", payload)
        if path == "/api/intervals/full-resync":
            return self._full_resync_command("intervals", payload)
        if path == "/api/garmin/full-resync":
            return self._full_resync_command("garmin", payload)
        if path == "/api/performance/refresh":
            return 200, self._performance.refresh()
        if path == "/api/external-calendar/sync":
            return 202, self._queue.enqueue(
                "calendar", "refresh", {"reason": "manuell"}, requested_by="user"
            )
        if path == "/api/weather/sync":
            return 202, self._queue.enqueue(
                "weather", "refresh", {"reason": "manuell", "force": True},
                requested_by="user",
            )
        raise ValueError(f"Unsupported sync path: {path}")

    def _enqueue_manual_refresh(self, provider: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        requested_days = payload.get(
            "days",
            self._state.sync_period(provider, self._period_defaults, self._all_sync_days),
        )
        try:
            days = self._state.set_sync_period(provider, requested_days, self._all_sync_days)
        except ValueError as exc:
            try:
                int(requested_days)
            except (TypeError, ValueError):
                message = "Der Synchronisationszeitraum muss eine ganze Zahl sein."
            else:
                message = (
                    "Der Zeitraum für intervals muss -1 oder zwischen 1 und 365 Tagen liegen."
                    if provider == "intervals"
                    else "Der Zeitraum für garmin muss -1 oder zwischen 1 und 90 Tagen liegen."
                )
            raise AppError(400, message) from exc
        return 202, self._queue.enqueue(
            provider, "refresh", {"days": days, "reason": "manual"}, requested_by="user"
        )

    def _full_resync_command(self, provider: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if payload.get("confirm") != "FULL_RESYNC":
            raise AppError(400, "Zum vollständigen Resync muss FULL_RESYNC bestätigt werden.")
        return 200, self._full_resync.resync(
            provider, operation_id=self._operation_id_factory()
        )
