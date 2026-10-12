"""Wahoo Cloud OAuth transport.

This adapter only speaks the Wahoo authorization-code protocol. Local policy
(state handling, token storage, refresh scheduling) belongs to the caller.
Tokens and the client secret are never logged: the shared JSON client records
only request shapes, and bodies are sent form-encoded as raw bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from backend.config import Config
from backend.errors import AppError

WAHOO_API_BASE = "https://api.wahooligan.com"
WAHOO_AUTHORIZE_URL = f"{WAHOO_API_BASE}/oauth/authorize"
WAHOO_TOKEN_URL = f"{WAHOO_API_BASE}/oauth/token"
WAHOO_PERMISSIONS_URL = f"{WAHOO_API_BASE}/v1/permissions"
WAHOO_SCOPES = (
    "user_read",
    "workouts_read",
    "workouts_write",
    "plans_read",
    "plans_write",
    "power_zones_read",
    "offline_data",
)
WAHOO_SERVICE = "wahoo"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
TOKEN_TIMEOUT_SECONDS = 20

JsonRequest = Callable[..., Any]


@dataclass(frozen=True)
class WahooTokenGrant:
    """One token response; never rendered into logs or API responses."""

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str

    def __repr__(self) -> str:
        return "WahooTokenGrant(<redacted>)"


def _grant_from_payload(payload: Any, requested_scope: str) -> WahooTokenGrant:
    if not isinstance(payload, dict):
        raise _invalid_token_response()
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or expires_in <= 0
    ):
        raise _invalid_token_response()
    scope = payload.get("scope")
    return WahooTokenGrant(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(expires_in),
        scope=scope.strip()
        if isinstance(scope, str) and scope.strip()
        else requested_scope,
    )


def _invalid_token_response() -> AppError:
    return AppError(
        502,
        "Wahoo hat eine unvollständige Anmeldeantwort gesendet.",
        reason="wahoo_invalid_token_response",
    )


class WahooOAuthClient:
    """Build authorization URLs and run the Wahoo token and permission calls."""

    def __init__(self, config: Callable[[], Config], request: JsonRequest) -> None:
        self._config = config
        self._request = request

    @property
    def scope(self) -> str:
        return " ".join(WAHOO_SCOPES)

    def authorize_url(self, state: str) -> str:
        config = self._config()
        query = urlencode(
            {
                "client_id": config.wahoo_client_id,
                "redirect_uri": config.wahoo_redirect_uri,
                "response_type": "code",
                "scope": self.scope,
                "state": state,
            }
        )
        return f"{WAHOO_AUTHORIZE_URL}?{query}"

    def _token_request(self, fields: dict[str, str]) -> WahooTokenGrant:
        config = self._config()
        body = urlencode(
            {
                "client_id": config.wahoo_client_id,
                "client_secret": config.wahoo_client_secret,
                **fields,
            }
        ).encode("ascii")
        payload = self._request(
            "POST",
            WAHOO_TOKEN_URL,
            raw_body=body,
            content_type=FORM_CONTENT_TYPE,
            timeout=TOKEN_TIMEOUT_SECONDS,
            service=WAHOO_SERVICE,
        )
        return _grant_from_payload(payload, self.scope)

    def exchange_code(self, code: str) -> WahooTokenGrant:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._config().wahoo_redirect_uri,
            }
        )

    def refresh(self, refresh_token: str) -> WahooTokenGrant:
        return self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    def deauthorize(self, access_token: str) -> None:
        self._request(
            "DELETE",
            WAHOO_PERMISSIONS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TOKEN_TIMEOUT_SECONDS,
            service=WAHOO_SERVICE,
        )
