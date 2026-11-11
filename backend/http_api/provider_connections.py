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


class ProviderConnectionGetRoutes:
    def __init__(self, checks: Callable[[], Any]) -> None:
        self._checks = checks

    def routes(self) -> list[Route]:
        return [Route("GET", STATUS_PATH, Access.SESSION, self._statuses)]

    def _statuses(self, handler: Any, _request: RouteRequest) -> None:
        """Last local connection check per provider, without contacting any provider."""
        handler.send_json(200, {"providers": self._checks().statuses()})


class ProviderConnectionPostRoutes:
    def __init__(self, checks: Callable[[], Any]) -> None:
        self._checks = checks

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/providers/{provider}/check",
                Access.SESSION_CSRF,
                self._check,
            )
        ]

    def _check(self, handler: Any, request: RouteRequest) -> None:
        """Explicitly run one bounded read-only connection check for an OpenAI, Intervals.icu, Garmin, Wahoo or Open-Meteo provider and record an in-memory result."""
        provider = request.params["provider"]
        checks = self._checks()
        # Drain the body first, like the other command routes.
        handler.read_json()
        if provider not in checks.providers():
            raise AppError(404, "Unbekannter Anbieter.", reason="unknown_provider")
        handler.send_json(200, checks.check(provider))
