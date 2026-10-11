"""Map authenticated synchronization POST requests to concrete sync use cases.

Provider routes, their not-configured messages and their period rules come from
the provider registry. The registry is read once per registry into a single
route table (``SyncRouteSurface``), so a request only looks its path up. The
performance refresh, the job queue and job resolution are not provider routes
and stay explicit in this module.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
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


@dataclass(frozen=True, slots=True)
class _ManualRoute:
    """A registry manual route: its provider, period rule and fixed job fields."""

    provider_id: str
    uses_sync_period: bool
    fixed_payload: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class _PathRoute:
    """Everything the registry routes one sync POST path to.

    ``fixed_body`` marks the job endpoint, which always reads a body.
    """

    fixed_body: bool = False
    manual: _ManualRoute | None = None
    full_resync_provider: str | None = None

    @property
    def reads_body(self) -> bool:
        if self.fixed_body or self.full_resync_provider is not None:
            return True
        return self.manual is not None and self.manual.uses_sync_period


def _not_configured_messages(registry: ProviderRegistry) -> dict[str, str]:
    messages: dict[str, str] = {}
    for descriptor in registry.all():
        if descriptor.not_configured_message is not None:
            key = descriptor.provider_id.strip().casefold()
            messages[key] = descriptor.not_configured_message
    return messages


def _build_path_routes(registry: ProviderRegistry) -> dict[str, _PathRoute]:
    routes: dict[str, _PathRoute] = {
        SYNC_JOBS_PATH: _PathRoute(fixed_body=True),
        PERFORMANCE_REFRESH_PATH: _PathRoute(),
    }
    for descriptor in registry.all():
        manual = descriptor.manual_sync
        if manual is not None:
            current = routes.get(manual.path, _PathRoute())
            routes[manual.path] = replace(
                current,
                manual=_ManualRoute(
                    descriptor.provider_id, manual.uses_sync_period, manual.payload
                ),
            )
        if descriptor.full_resync_path is not None:
            current = routes.get(descriptor.full_resync_path, _PathRoute())
            routes[descriptor.full_resync_path] = replace(
                current, full_resync_provider=descriptor.provider_id
            )
    return routes


class SyncRouteSurface:
    """The sync POST surface one registry defines, as a single route table."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self._routes = _build_path_routes(registry)
        self._not_configured = _not_configured_messages(registry)

    def route(self, path: str) -> _PathRoute | None:
        return self._routes.get(path)

    def paths(self) -> frozenset[str]:
        return frozenset(self._routes)

    def body_paths(self) -> frozenset[str]:
        return frozenset(
            path for path, route in self._routes.items() if route.reads_body
        )

    def accepts(self, path: str) -> bool:
        return path in self._routes or SYNC_JOB_RESOLVE_RE.match(path) is not None

    def requires_body(self, path: str) -> bool:
        route = self._routes.get(path)
        reads_body = route is not None and route.reads_body
        return reads_body or SYNC_JOB_RESOLVE_RE.match(path) is not None

    def not_configured_message(self, provider: str) -> str | None:
        """Return the rejection text for a provider id, matched case-insensitively."""
        return self._not_configured.get(provider.strip().casefold())

    def not_configured_messages(self) -> Mapping[str, str]:
        return dict(self._not_configured)


@lru_cache(maxsize=32)
def _surface_for(registry: ProviderRegistry) -> SyncRouteSurface:
    """Derive the surface once per registry; registries are immutable."""
    return SyncRouteSurface(registry)


def handles_sync_path(registry: ProviderRegistry, path: str) -> bool:
    """Return whether ``registry`` routes ``path`` to the sync endpoint."""
    return _surface_for(registry).accepts(path)


def needs_sync_body(registry: ProviderRegistry, path: str) -> bool:
    """Return whether ``registry`` reads a JSON body for the sync path ``path``."""
    return _surface_for(registry).requires_body(path)


_DEFAULT_SURFACE = _surface_for(DEFAULT_PROVIDER_REGISTRY)
SYNC_POST_PATHS = _DEFAULT_SURFACE.paths()
SYNC_BODY_PATHS = _DEFAULT_SURFACE.body_paths()
PROVIDER_NOT_CONFIGURED_MESSAGES = _DEFAULT_SURFACE.not_configured_messages()
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
        self._surface = _surface_for(registry)

    @staticmethod
    def handles(path: str) -> bool:
        return handles_sync_path(DEFAULT_PROVIDER_REGISTRY, path)

    @staticmethod
    def needs_body(path: str) -> bool:
        return needs_sync_body(DEFAULT_PROVIDER_REGISTRY, path)

    def accepts(self, path: str) -> bool:
        """Return whether this endpoint's registry accepts the sync POST path."""
        return self._surface.accepts(path)

    def requires_body(self, path: str) -> bool:
        """Return whether this endpoint's registry reads a JSON body for the path."""
        return self._surface.requires_body(path)

    def execute(self, path: str, payload: Any = None) -> tuple[int, dict[str, Any]]:
        if path == SYNC_JOBS_PATH:
            return self._enqueue_job(payload)
        if match := SYNC_JOB_RESOLVE_RE.match(path):
            return 200, self._queue.resolve(match.group(1), payload)
        if path == PERFORMANCE_REFRESH_PATH:
            return 200, self._performance.refresh()
        route = self._surface.route(path)
        if route is not None and route.manual is not None:
            manual = route.manual
            return self._manual_refresh(
                manual.provider_id,
                manual.uses_sync_period,
                manual.fixed_payload,
                payload,
            )
        if route is not None and route.full_resync_provider is not None:
            return self._full_resync_command(route.full_resync_provider, payload)
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
        provider: Any = payload.get("provider")
        self._require_provider_configured(provider)
        return 202, self._queue.enqueue(
            provider,
            payload.get("type", "refresh"),
            envelope,
            requested_by="user",
        )

    def _require_provider_configured(self, provider: Any) -> None:
        """Reject unconfigured provider work before any job or period is stored."""
        if not isinstance(provider, str):
            return
        message = self._surface.not_configured_message(provider)
        if message is None:
            return
        normalized = provider.strip().casefold()
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
