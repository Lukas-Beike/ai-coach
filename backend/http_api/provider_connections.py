"""Authenticated provider connection status and explicit check routes.

Status reads local state only. A check is a CSRF-protected POST (enforced by
the handler before dispatch) that performs one bounded read-only provider
request through the check service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest

STATUS_PATH = "/api/providers/connections"
CHECK_PREFIX = "/api/providers/"
CHECK_SUFFIX = "/check"


class ProviderConnectionGetRoutes:
    def __init__(self, checks: Callable[[], Any]) -> None:
        self._checks = checks

    def routes(self) -> list[Route]:
        return [Route("GET", STATUS_PATH, Access.SESSION, self._statuses)]

    def _statuses(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(200, {"providers": self._checks().statuses()})


class ProviderConnectionPostRoutes:
    def __init__(self, checks: Callable[[], Any]) -> None:
        self._checks = checks

    def handle(self, handler: Any, path: str) -> bool:
        if not (path.startswith(CHECK_PREFIX) and path.endswith(CHECK_SUFFIX)):
            return False
        provider = path[len(CHECK_PREFIX) : -len(CHECK_SUFFIX)]
        checks = self._checks()
        # Drain the body first, like the other command routes.
        handler.read_json()
        if provider not in checks.providers():
            raise AppError(404, "Unbekannter Anbieter.", reason="unknown_provider")
        handler.send_json(200, checks.check(provider))
        return True
