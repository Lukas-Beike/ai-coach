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
        """Create a session.

        Request: JSON body `{"password": string}`; no session or CSRF token. A
        missing `password` counts as empty. Runs outside the maintenance gate.

        Response: 200 with `status` (`"ok"`), `authenticated` (`true`) and `csrf`
        (the CSRF token for the `X-CSRF-Token` header). `Set-Cookie` sets the
        `ic_session` (HttpOnly) and `ic_csrf` cookies, both `SameSite=Strict` and
        valid for 30 days.

        Errors: 401 "Ungültiges Passwort." for a wrong password; 429 `rate_limited`
        "Zu viele Anmeldeversuche. Erneut versuchen in etwa N Sekunden." after 5
        failed attempts within 15 minutes from one client address (only failed
        attempts count); 503 "Die sichere App-Konfiguration ist unvollständig."
        when the secure configuration is incomplete.
        """
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
        """End the current session.

        Request: no body.

        Response: 200 with `status` (`"ok"`); `Set-Cookie` clears the `ic_session`
        and `ic_csrf` cookies. The stored session is deleted.

        Errors: none beyond the common ones.
        """
        auth = self._session_auth_service()
        with self._maintenance_gate.operation():
            auth.logout_user(handler)
        clear_headers = auth.session_cookie_headers(clear=True)
        handler.send_json(
            200,
            {"status": "ok"},
            {"Set-Cookie": [clear_headers[0], clear_headers[1]]},
        )
