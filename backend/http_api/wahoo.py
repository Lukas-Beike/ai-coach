"""Wahoo connection routes: authenticated start/disconnect and the OAuth callback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
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

    def routes(self) -> list[Route]:
        return [Route("GET", CALLBACK_PATH, Access.PUBLIC, self._callback)]

    def _callback(self, handler: Any, request: RouteRequest) -> None:
        """Wahoo OAuth redirect target; answers 302 to the app.

        Request: no session; query `code` (authorization code), `state` and
        `error`, each at most 2048 characters. The only accepted credential is
        the single-use `state` stored on the server by `POST /api/wahoo/connect`
        (valid 10 minutes, consumed by the first callback that matches or finds
        it expired): the SameSite=Strict session cookies are not sent on Wahoo's
        cross-site redirect. The call enters the maintenance operation gate.

        Response: 302 with an empty `text/plain` body and `Location`
        `/?wahoo=connected` after the code was exchanged and the tokens stored,
        else `/?wahoo=error`.

        Errors: none; an unknown, expired or reused `state`, a missing `code`, an
        `error` parameter, a failed code exchange, an unconfigured Wahoo or a
        disconnect during the exchange all redirect to `/?wahoo=error`.
        """

        def first(name: str) -> str | None:
            values = request.query.get(name)
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


class WahooPostRoutes:
    """Authenticated connect and disconnect commands (session and CSRF checked)."""

    def __init__(self, wahoo_service: Callable[[], WahooConnectionService]) -> None:
        self._wahoo_service = wahoo_service

    def routes(self) -> list[Route]:
        return [
            Route("POST", path, Access.SESSION_CSRF, self._command)
            for path in (CONNECT_PATH, DISCONNECT_PATH)
        ]

    def _command(self, handler: Any, request: RouteRequest) -> None:
        """Start the Wahoo OAuth connection or disconnect Wahoo.

        Request: JSON object body, which is ignored (send `{}`). Registered for
        `/api/wahoo/connect` and `/api/wahoo/disconnect`.

        Response: for `/api/wahoo/connect` 200 with `authorize_url`, the Wahoo
        authorization URL carrying a new one-time `state` that replaces any
        pending one. For `/api/wahoo/disconnect` 200 with `status` (`"ok"`),
        `connected` (`false`), `remote_revoke_attempted` and `remote_revoked`
        (the revocation at Wahoo is best effort; the local tokens are always
        deleted).

        Errors: for `/api/wahoo/connect`: 503 `not_configured` "Wahoo ist nicht
        konfiguriert. Bitte WAHOO_CLIENT_ID, WAHOO_CLIENT_SECRET und
        WAHOO_REDIRECT_URI in der Serverkonfiguration hinterlegen."; 400
        `invalid_redirect_uri` "WAHOO_REDIRECT_URI muss eine vollständige
        HTTPS-URL ohne Zugangsdaten sein." when the configured redirect is not an
        HTTPS URL with host, without credentials or fragment. Disconnect has no
        route-specific errors.
        """
        # Drain and validate the (empty) JSON command body like other commands.
        handler.read_json()
        service = self._wahoo_service()
        result = (
            service.start_authorization()
            if request.path == CONNECT_PATH
            else service.disconnect()
        )
        handler.send_json(200, result)
