"""Wahoo connection routes: authenticated start/disconnect and the OAuth callback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.runtime.maintenance import MaintenanceGate
from backend.sync.wahoo_connection import (
    CALLBACK_CONNECTED,
    WahooConnectionService,
)

CONNECT_PATH = "/api/wahoo/connect"
DISCONNECT_PATH = "/api/wahoo/disconnect"
CALLBACK_PATH = "/api/wahoo/callback"
# Same-site targets without any secret; the PWA reads the outcome word only.
REDIRECT_CONNECTED = "/?wahoo=connected"
REDIRECT_ERROR = "/?wahoo=error"


class WahooGetRoutes:
    """Handle the OAuth redirect from Wahoo.

    This route deliberately requires no session: the session cookies are
    SameSite=Strict and are not sent on the cross-site redirect from Wahoo. The
    server-stored, single-use, expiring ``state`` created by an authenticated
    ``POST /api/wahoo/connect`` is the only credential accepted here.
    """

    def __init__(
        self,
        wahoo_service: Callable[[], WahooConnectionService],
        maintenance_gate: MaintenanceGate,
    ) -> None:
        self._wahoo_service = wahoo_service
        self._maintenance_gate = maintenance_gate

    def handle(self, handler: Any, path: str) -> bool:
        if path != CALLBACK_PATH:
            return False
        query = parse_qs(urlparse(handler.path).query)

        def first(name: str) -> str | None:
            values = query.get(name)
            return values[0] if values else None

        with self._maintenance_gate.operation():
            outcome = self._wahoo_service().complete_authorization(
                first("code"), first("state"), first("error")
            )
        location = (
            REDIRECT_CONNECTED if outcome == CALLBACK_CONNECTED else REDIRECT_ERROR
        )
        handler.send_bytes(
            302, b"", "text/plain; charset=utf-8", {"Location": location}
        )
        return True


class WahooPostRoutes:
    """Authenticated connect and disconnect commands (session and CSRF checked)."""

    def __init__(self, wahoo_service: Callable[[], WahooConnectionService]) -> None:
        self._wahoo_service = wahoo_service

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {CONNECT_PATH, DISCONNECT_PATH}:
            return False
        # Drain and validate the (empty) JSON command body like other commands.
        handler.read_json()
        service = self._wahoo_service()
        result = (
            service.start_authorization()
            if path == CONNECT_PATH
            else service.disconnect()
        )
        handler.send_json(200, result)
        return True
