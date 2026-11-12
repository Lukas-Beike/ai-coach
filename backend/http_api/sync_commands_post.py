"""HTTP transport for explicit synchronization commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.sync_commands import SYNC_ROUTE_SURFACE, SyncCommandEndpoint


class SyncCommandPostRoute:
    """Read the request body and write the result for a sync command."""

    def __init__(self, endpoint: Callable[[], SyncCommandEndpoint]) -> None:
        self._endpoint = endpoint

    def routes(self) -> list[Route]:
        routes = []
        for path in sorted(SYNC_ROUTE_SURFACE.paths()):
            route = SYNC_ROUTE_SURFACE.route(path)
            if route is not None and route.full_resync_provider is not None:
                handle = self._full_resync
            elif route is not None and route.manual is not None:
                handle = self._manual_sync
            else:
                handle = self._execute
            routes.append(Route("POST", path, Access.SESSION_CSRF, handle))
        return routes

    def _full_resync(self, handler: Any, request: RouteRequest) -> None:
        """Start the confirmed full resync in the background (`202` with `operation_id`; `200` `already_running` while one runs)."""
        self._execute(handler, request)

    def _manual_sync(self, handler: Any, request: RouteRequest) -> None:
        """Queue a provider synchronization, or a targeted refresh of the external calendars or the weather."""
        self._execute(handler, request)

    def _execute(self, handler: Any, request: RouteRequest) -> None:
        """Queue a sync job."""
        payload = (
            handler.read_json()
            if SyncCommandEndpoint.needs_body(request.path)
            else None
        )
        status, result = self._endpoint().execute(request.path, payload)
        handler.send_json(status, result)
