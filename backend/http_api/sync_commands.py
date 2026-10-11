"""Map authenticated synchronization POST requests to concrete sync use cases.

Provider routes, their not-configured messages and their period rules come from
the provider registry. The performance refresh, the job queue and job resolution
are not provider routes and stay explicit in this module.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.sync.full_resync import FullProviderResyncService
from backend.sync.performance import PerformanceRefreshService
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository

SYNC_JOB_RESOLVE_RE = re.compile(r"^/api/sync/jobs/([0-9a-f-]+)/resolve$")
SYNC_JOBS_PATH = "/api/sync/jobs"
PERFORMANCE_REFRESH_PATH = "/api/performance/refresh"


def _uses_sync_period(registry: ProviderRegistry, provider_id: str) -> bool:
    route = registry.get(provider_id).manual_sync
    return route is not None and route.uses_sync_period


def sync_post_paths(registry: ProviderRegistry) -> frozenset[str]:
    """Return every sync POST path that ``registry`` routes to the endpoint."""
    manual = (path for path, _ in registry.manual_routes())
    full_resync = (path for path, _ in registry.full_resync_routes())
    return frozenset({SYNC_JOBS_PATH, PERFORMANCE_REFRESH_PATH, *manual, *full_resync})


def sync_body_paths(registry: ProviderRegistry) -> frozenset[str]:
    """Return the sync POST paths that ``registry`` reads a JSON body for."""
    # Only period-based manual routes and full resyncs read a request body.
    period_routes = (
        path
        for path, provider_id in registry.manual_routes()
        if _uses_sync_period(registry, provider_id)
    )
    full_resync = (path for path, _ in registry.full_resync_routes())
    return frozenset({SYNC_JOBS_PATH, *period_routes, *full_resync})


def handles_sync_path(registry: ProviderRegistry, path: str) -> bool:
    """Return whether ``registry`` routes ``path`` to the sync endpoint."""
    return (
        path in sync_post_paths(registry) or SYNC_JOB_RESOLVE_RE.match(path) is not None
    )


def needs_sync_body(registry: ProviderRegistry, path: str) -> bool:
    """Return whether ``registry`` reads a JSON body for the sync path ``path``."""
    return (
        path in sync_body_paths(registry) or SYNC_JOB_RESOLVE_RE.match(path) is not None
    )


def _not_configured_messages(registry: ProviderRegistry) -> dict[str, str]:
    messages: dict[str, str] = {}
    for descriptor in registry.all():
        if descriptor.not_configured_message is not None:
            key = descriptor.provider_id.strip().casefold()
            messages[key] = descriptor.not_configured_message
    return messages


SYNC_POST_PATHS = sync_post_paths(DEFAULT_PROVIDER_REGISTRY)
SYNC_BODY_PATHS = sync_body_paths(DEFAULT_PROVIDER_REGISTRY)
PROVIDER_NOT_CONFIGURED_MESSAGES = _not_configured_messages(DEFAULT_PROVIDER_REGISTRY)
_MANUAL_PATHS = {
    provider_id: path for path, provider_id in DEFAULT_PROVIDER_REGISTRY.manual_routes()
}
_FULL_RESYNC_PATHS = {
    provider_id: path
    for path, provider_id in DEFAULT_PROVIDER_REGISTRY.full_resync_routes()
}
SYNC_PATH = _MANUAL_PATHS[ProviderId.INTERVALS]
GARMIN_SYNC_PATH = _MANUAL_PATHS[ProviderId.GARMIN]
INTERVALS_FULL_RESYNC_PATH = _FULL_RESYNC_PATHS[ProviderId.INTERVALS]
GARMIN_FULL_RESYNC_PATH = _FULL_RESYNC_PATHS[ProviderId.GARMIN]


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
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._queue = queue
        self._state = state
        self._performance = performance
        self._full_resync = full_resync
        self._operation_id_factory = operation_id_factory
        self._period_defaults = period_defaults
        self._all_sync_days = all_sync_days
        self._registry = registry
        self._manual_routes = {
            descriptor.manual_sync.path: (
                descriptor.provider_id,
                descriptor.manual_sync,
            )
            for descriptor in registry.all()
            if descriptor.manual_sync is not None
        }
        self._full_resync_providers = dict(registry.full_resync_routes())
        self._not_configured = _not_configured_messages(registry)
        self._post_paths = sync_post_paths(registry)
        self._body_paths = sync_body_paths(registry)

    @staticmethod
    def handles(path: str) -> bool:
        return handles_sync_path(DEFAULT_PROVIDER_REGISTRY, path)

    @staticmethod
    def needs_body(path: str) -> bool:
        return needs_sync_body(DEFAULT_PROVIDER_REGISTRY, path)

    def accepts(self, path: str) -> bool:
        """Return whether this endpoint's registry accepts the sync POST path."""
        return path in self._post_paths or SYNC_JOB_RESOLVE_RE.match(path) is not None

    def requires_body(self, path: str) -> bool:
        """Return whether this endpoint's registry reads a JSON body for the path."""
        return path in self._body_paths or SYNC_JOB_RESOLVE_RE.match(path) is not None

    def execute(self, path: str, payload: Any = None) -> tuple[int, dict[str, Any]]:
        if path == SYNC_JOBS_PATH:
            return self._enqueue_job(payload)
        if match := SYNC_JOB_RESOLVE_RE.match(path):
            return 200, self._queue.resolve(match.group(1), payload)
        if path == PERFORMANCE_REFRESH_PATH:
            return 200, self._performance.refresh()
        if path in self._manual_routes:
            provider_id, route = self._manual_routes[path]
            return self._manual_refresh(
                provider_id, route.uses_sync_period, route.payload, payload
            )
        if path in self._full_resync_providers:
            return self._full_resync_command(self._full_resync_providers[path], payload)
        raise ValueError(f"Unsupported sync path: {path}")

    def _enqueue_job(self, payload: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise AppError(
                400,
                "Ein Synchronisationsjob muss als Objekt gesendet werden.",
                reason="invalid_job_request",
            )
        envelope = payload.get("payload")
        if envelope is None:
            envelope = {
                key: payload[key]
                for key in ("days", "force", "reason")
                if key in payload
            }
        self._require_provider_configured(payload.get("provider"))
        return 202, self._queue.enqueue(
            payload.get("provider"),
            payload.get("type", "refresh"),
            envelope,
            requested_by="user",
        )

    def _require_provider_configured(self, provider: Any) -> None:
        """Reject unconfigured provider work before any job or period is stored."""
        if not isinstance(provider, str):
            return
        normalized = provider.strip().casefold()
        message = self._not_configured.get(normalized)
        if message is None:
            return
        if not self._full_resync.provider_configured(normalized):
            raise AppError(409, message, reason="not_configured")

    def _manual_refresh(
        self,
        provider_id: str,
        uses_sync_period: bool,
        fixed_payload: tuple[tuple[str, object], ...],
        payload: Any,
    ) -> tuple[int, dict[str, Any]]:
        self._require_provider_configured(provider_id)
        fixed = dict(fixed_payload)
        if not uses_sync_period:
            return 202, self._queue.enqueue(
                provider_id, "refresh", fixed, requested_by="user"
            )
        days = self._sync_period_days(provider_id, payload)
        return 202, self._queue.enqueue(
            provider_id, "refresh", {"days": days, **fixed}, requested_by="user"
        )

    def _sync_period_days(self, provider_id: str, payload: dict[str, Any]) -> int:
        requested_days = payload.get(
            "days",
            self._state.sync_period(
                provider_id, self._period_defaults, self._all_sync_days
            ),
        )
        try:
            return self._state.set_sync_period(
                provider_id, requested_days, self._all_sync_days
            )
        except ValueError as exc:
            raise AppError(
                400, self._period_error(provider_id, requested_days)
            ) from exc

    def _period_error(self, provider_id: str, requested_days: Any) -> str:
        try:
            int(requested_days)
        except TypeError, ValueError:
            return "Der Synchronisationszeitraum muss eine ganze Zahl sein."
        return self._registry.period_error_message(provider_id)

    def _full_resync_command(
        self, provider: str, payload: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if payload.get("confirm") != "FULL_RESYNC":
            raise AppError(
                400, "Zum vollständigen Resync muss FULL_RESYNC bestätigt werden."
            )
        return 200, self._full_resync.resync(
            provider, operation_id=self._operation_id_factory()
        )
