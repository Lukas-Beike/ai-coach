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
        """Last local connection check per provider, without contacting any provider.

        Request: no body.

        Response: 200 with `providers`, an object keyed by provider id (`openai`,
        `anthropic`, `intervals`, `garmin`, `wahoo`, `weather`) whose values hold
        `status`, `checked_at` and `guidance`. `status` is `not_configured`,
        `unchecked`, `checking`, `unknown` or the result of the last check in
        this process (`success`, `auth_failed`, `rate_limited`, `unavailable`,
        `scope_missing`, `unsupported`, `misconfigured`, `busy`); `guidance` is
        a German recovery hint only for `auth_failed`, else an empty string.

        Errors: none beyond the common ones.
        """
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
        """Explicitly run one bounded read-only connection check for an OpenAI, Claude, Intervals.icu, Garmin, Wahoo or Open-Meteo provider and record an in-memory result.

        Request: path `provider` (`openai`, `anthropic`, `intervals`, `garmin`,
        `wahoo` or `weather`); JSON object body, which is ignored (send `{}`).

        Response: 200 with `status`, `checked_at` and `guidance` as in
        `GET /api/providers/connections`. The check waits at most 45 seconds and
        then answers `checking` while it finishes in the background; repeating a
        settled check for the same credentials within 10 seconds returns the
        stored result without a new provider request.

        Errors: 404 `unknown_provider` "Unbekannter Anbieter." for any other
        provider id.
        """
        provider = request.params["provider"]
        checks = self._checks()
        # Drain the body first, like the other command routes.
        handler.read_json()
        if provider not in checks.providers():
            raise AppError(404, "Unbekannter Anbieter.", reason="unknown_provider")
        handler.send_json(200, checks.check(provider))
