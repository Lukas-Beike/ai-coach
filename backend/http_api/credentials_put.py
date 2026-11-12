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
        """Save or clear provider credentials in the encrypted database.

        Request: JSON object whose keys are credential fields and whose values are
        strings (stored after trimming, at most 4096 characters, no control
        characters) or `null` / a blank string (clears the value stored in the app,
        so the environment value applies again). Fields: `openai_api_key`,
        `anthropic_api_key`, `intervals_api_key`, `garmin_personal_api_key`,
        `wahoo_client_secret`, `yazio_password`, `openai_base_url`,
        `anthropic_base_url` (HTTPS, or HTTP on loopback), `intervals_athlete_id`,
        `wahoo_client_id`, `garmin_personal_api_key_expires` (`YYYY-MM-DD`; changing
        the key without it clears the stored date), `garmin_email`, `yazio_email`.
        Fields not sent keep their value; the whole submission is validated before
        anything is written. Setting (not clearing) `openai_base_url`,
        `anthropic_base_url`, `wahoo_client_id` or `wahoo_client_secret` also needs
        `app_password`, the APP_PASSWORD entered again; it is checked in constant
        time before anything is written, rate limited to 10 attempts per 15 minutes
        and client address, and never stored. Saving or clearing
        `garmin_personal_api_key` or `garmin_email` also resets a paused Garmin
        capability.

        Response: 200 with the credential status, never a secret value: `fields`
        (per field `source` `db`, `env` or `none`, `configured`, and `value` for
        `openai_base_url`, `anthropic_base_url`, `intervals_athlete_id`,
        `wahoo_client_id` and `garmin_personal_api_key_expires` only),
        `garmin_connected`, `garmin_connection_source`, `openai_configured`,
        `anthropic_configured`, `intervals_configured`, `wahoo_configured`,
        `yazio_configured` and `garmin_connection` (`connected`, `source`,
        `mfa_pending`). `garmin_email` and `yazio_email` are reported as configured
        only.

        Errors: 403 "Das App-Passwort fehlt oder ist falsch. Es wurde nichts
        geändert." when `app_password` is missing or wrong for a field above; 400
        "Unbekanntes Zugangsdatenfeld."; 400 "Ungültiger Wert für {field}." for a
        non-string value, an over-long one or one with control characters; 400
        "Ungültiges Ablaufdatum."; 400 "OPENAI_BASE_URL muss HTTPS oder HTTP auf
        Loopback verwenden." (`ANTHROPIC_BASE_URL` for the other field).
        """
        values = handler.read_json()
        if isinstance(values, dict):
            # Never part of the credential submission itself.
            password = values.pop(PASSWORD_FIELD, None)
            if requires_password(values):
                self._session_auth_service().require_password(handler, password)
        result = self._credentials.update(values)
        handler.send_json(200, result)
