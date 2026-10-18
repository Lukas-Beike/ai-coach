"""Garmin login routes: credentials, MFA code and disconnect (session and CSRF checked)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.sync.garmin_login import GarminLoginService

LOGIN_PATH = "/api/garmin/login"
MFA_PATH = "/api/garmin/login/mfa"
DISCONNECT_PATH = "/api/garmin/disconnect"


class GarminPostRoutes:
    """Authenticated Garmin commands. Request bodies are never echoed back."""

    def __init__(self, garmin_login: Callable[[], GarminLoginService]) -> None:
        self._garmin_login = garmin_login

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {LOGIN_PATH, MFA_PATH, DISCONNECT_PATH}:
            return False
        body = handler.read_json()
        service = self._garmin_login()
        if path == LOGIN_PATH:
            result = service.login(body)
        elif path == MFA_PATH:
            result = service.submit_mfa(body)
        else:
            result = service.disconnect()
        handler.send_json(200, result)
        return True
