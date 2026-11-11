"""Authenticated provider credential PUT route.

CSRF and session checks run in ``handler._do_PUT`` before dispatch. The
response carries status only and never echoes submitted values. The write is
deliberately not recorded in change history. Setting the OpenAI base URL or the
Wahoo client settings also needs the APP_PASSWORD (``app_password``) again; it is
checked before anything is written and never stored.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.provider_credentials import ProviderCredentialService, requires_password

CREDENTIALS_PATH = "/api/settings/credentials"
PASSWORD_FIELD = "app_password"


class CredentialsPutRoutes:
    """Dispatch provider credential writes through the credential service."""

    def __init__(
        self,
        credentials: ProviderCredentialService,
        session_auth_service: Callable[[], SessionAuthService],
    ) -> None:
        self._credentials = credentials
        self._session_auth_service = session_auth_service

    def routes(self) -> list[Route]:
        return [Route("PUT", CREDENTIALS_PATH, Access.SESSION_CSRF, self._update)]

    def _update(self, handler: Any, _request: RouteRequest) -> None:
        """Save or clear provider credentials in the encrypted database (see below)."""
        values = handler.read_json()
        if isinstance(values, dict):
            # Never part of the credential submission itself.
            password = values.pop(PASSWORD_FIELD, None)
            if requires_password(values):
                self._session_auth_service().require_password(handler, password)
        result = self._credentials.update(values)
        handler.send_json(200, result)
