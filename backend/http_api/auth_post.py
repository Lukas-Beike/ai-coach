"""Public login and authenticated logout POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
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

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/login":
            auth = self._session_auth_service()
            payload = handler.read_json()
            password = str(payload.get("password") or "") if isinstance(payload, dict) else ""
            result = auth.login_user(handler, password)
            token = result.pop("session_token")
            csrf = result["csrf"]
            handler.send_json(
                200,
                result,
                {"Set-Cookie": auth.session_cookie_headers(token, csrf)},
            )
            return True
        if path == "/api/logout":
            auth = self._session_auth_service()
            session = auth.require_auth(handler)
            auth.require_csrf(handler, session)
            with self._maintenance_gate.operation():
                auth.logout_user(handler)
            clear_headers = auth.session_cookie_headers(clear=True)
            handler.send_json(
                200,
                {"status": "ok"},
                {"Set-Cookie": [clear_headers[0], clear_headers[1]]},
            )
            return True
        return False
