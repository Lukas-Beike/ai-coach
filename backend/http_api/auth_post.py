"""Public login and authenticated logout POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.runtime.maintenance import MaintenanceGate


class AuthPostRoutes:
    """Dispatch login and logout requests with cookie management."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        maintenance_gate: MaintenanceGate,
    ) -> None:
        self._session_auth_service = session_auth_service
        self._maintenance_gate = maintenance_gate

    def routes(self) -> list[Route]:
        return [
            Route("POST", "/api/login", Access.PUBLIC, self._login, gated=False),
            Route(
                "POST", "/api/logout", Access.SESSION_CSRF, self._logout, gated=False
            ),
        ]

    def _login(self, handler: Any, _request: RouteRequest) -> None:
        auth = self._session_auth_service()
        result = auth.login_user(handler)
        token = result.pop("session_token")
        csrf = result["csrf"]
        handler.send_json(
            200,
            result,
            {"Set-Cookie": auth.session_cookie_headers(token, csrf)},
        )

    def _logout(self, handler: Any, _request: RouteRequest) -> None:
        auth = self._session_auth_service()
        with self._maintenance_gate.operation():
            auth.logout_user(handler)
        clear_headers = auth.session_cookie_headers(clear=True)
        handler.send_json(
            200,
            {"status": "ok"},
            {"Set-Cookie": [clear_headers[0], clear_headers[1]]},
        )
