"""HTTP transport for explicit synchronization commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.sync_commands import (
    SyncCommandEndpoint,
    SyncRouteSurface,
    needs_sync_body,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


class SyncCommandPostRoute:
    """Read the request body and write the result for a sync command."""

    def __init__(
        self,
        endpoint: Callable[[], SyncCommandEndpoint],
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._endpoint = endpoint
        self._registry = registry

    def routes(self) -> list[Route]:
        return [
            Route("POST", path, Access.SESSION_CSRF, self._execute)
            for path in sorted(SyncRouteSurface(self._registry).paths())
        ]

    def _execute(self, handler: Any, request: RouteRequest) -> None:
        payload = (
            handler.read_json()
            if needs_sync_body(self._registry, request.path)
            else None
        )
        status, result = self._endpoint().execute(request.path, payload)
        handler.send_json(status, result)
