"""Garmin login routes: credentials, MFA code and disconnect (session and CSRF checked)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.sync.garmin_login import GarminLoginService

LOGIN_PATH = "/api/garmin/login"
MFA_PATH = "/api/garmin/login/mfa"
DISCONNECT_PATH = "/api/garmin/disconnect"


class GarminPostRoutes:
    """Authenticated Garmin commands. Request bodies are never echoed back."""

    def __init__(self, garmin_login: Callable[[], GarminLoginService]) -> None:
        self._garmin_login = garmin_login

    def routes(self) -> list[Route]:
        return [
            Route("POST", path, Access.SESSION_CSRF, self._handle)
            for path in (LOGIN_PATH, MFA_PATH, DISCONNECT_PATH)
        ]

    def _handle(self, handler: Any, request: RouteRequest) -> None:
        body = handler.read_json()
        service = self._garmin_login()
        if request.path == LOGIN_PATH:
            result = service.login(body)
        elif request.path == MFA_PATH:
            result = service.submit_mfa(body)
        else:
            result = service.disconnect()
        handler.send_json(200, result)
