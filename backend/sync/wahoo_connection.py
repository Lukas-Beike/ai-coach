"""Wahoo connection use case: OAuth login state, token storage and refresh.

The provider adapter (``backend.providers.wahoo_oauth``) only speaks the Wahoo
protocol. This module owns the local policy around it: the one-time login
``state``, the encrypted-at-rest token record in the SQLCipher key/value table,
rotation-safe refresh and disconnect. Tokens, the authorization code and the
state are never returned from or logged by this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from backend.canonical.vocabulary import ProviderId
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.wahoo_oauth import WahooOAuthClient, WahooTokenGrant

WAHOO_TOKENS_KEY = f"{ProviderId.WAHOO.value}_oauth_tokens"
WAHOO_STATE_KEY = f"{ProviderId.WAHOO.value}_oauth_state"
# Keys that must never leave the database through export, diagnostics or context.
WAHOO_SECRET_KEYS = frozenset({WAHOO_TOKENS_KEY, WAHOO_STATE_KEY})

STATE_TTL = timedelta(minutes=10)
REFRESH_MARGIN = timedelta(minutes=5)
MAX_CALLBACK_VALUE_LENGTH = 2048
# Statuses Wahoo uses when a refresh token is no longer valid.
_REFRESH_REJECTED_STATUSES = frozenset({400, 401, 422})

NOT_CONFIGURED_MESSAGE = (
    "Wahoo ist nicht konfiguriert. Bitte WAHOO_CLIENT_ID, WAHOO_CLIENT_SECRET "
    "und WAHOO_REDIRECT_URI in der Serverkonfiguration hinterlegen."
)
INVALID_REDIRECT_MESSAGE = (
    "WAHOO_REDIRECT_URI muss eine vollständige HTTPS-URL ohne Zugangsdaten sein."
)
NOT_CONNECTED_MESSAGE = "Wahoo ist nicht verbunden."
RECONNECT_MESSAGE = "Die Wahoo-Verbindung ist abgelaufen. Bitte Wahoo neu verbinden."

CALLBACK_CONNECTED = "connected"
CALLBACK_ERROR = "error"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except TypeError, ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _decode_object(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except TypeError, ValueError:
        return None
    return value if isinstance(value, dict) else None


def connection_status(config: Config, raw_tokens: str | None) -> dict[str, Any]:
    """Project the safe, token-free connection status for the PWA."""
    tokens = _decode_object(raw_tokens)
    connected = bool(
        tokens and tokens.get("access_token") and tokens.get("refresh_token")
    )
    return {
        "configured": config.wahoo_configured,
        "connected": connected,
        "scope": str(tokens.get("scope") or "") if connected and tokens else None,
        "connected_at": tokens.get("connected_at") if connected and tokens else None,
    }


class WahooConnectionService:
    """Own the Wahoo OAuth connection lifecycle and its persisted tokens."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        oauth: Callable[[], WahooOAuthClient],
        database_manager: Callable[[], DatabaseManager],
        database_lock: Callable[[], AbstractContextManager[Any]],
        key_values: KeyValueRepository,
        utc_now: Callable[[], str],
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self._config = config
        self._oauth = oauth
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._utc_now = utc_now
        self._token_factory = token_factory
        # Wahoo rotates refresh tokens: two concurrent refreshes would spend the
        # same refresh token twice, so refreshing is serialized per process.
        self._refresh_lock = threading.Lock()

    def _now(self) -> datetime:
        return _parse_time(self._utc_now()) or datetime.now(UTC)

    def _read(self, key: str) -> str | None:
        with self._database_lock(), self._database_manager().unit_of_work() as db:
            return self._key_values.get(db, key)

    def _write(self, key: str, value: dict[str, Any]) -> None:
        with self._database_lock(), self._database_manager().unit_of_work() as db:
            self._key_values.set(db, key, json.dumps(value, separators=(",", ":")))

    def _delete(self, *keys: str) -> None:
        with self._database_lock(), self._database_manager().unit_of_work() as db:
            for key in keys:
                self._key_values.delete(db, key)

    def status(self) -> dict[str, Any]:
        return connection_status(self._config(), self._read(WAHOO_TOKENS_KEY))

    # Authorization -------------------------------------------------------

    def start_authorization(self) -> dict[str, str]:
        """Create a one-time login state and return the Wahoo authorize URL."""
        config = self._config()
        if not config.wahoo_configured:
            raise AppError(503, NOT_CONFIGURED_MESSAGE, reason="not_configured")
        redirect = urlsplit(config.wahoo_redirect_uri)
        if (
            redirect.scheme != "https"
            or not redirect.hostname
            or redirect.username
            or redirect.password
            or redirect.fragment
        ):
            raise AppError(400, INVALID_REDIRECT_MESSAGE, reason="invalid_redirect_uri")
        state = self._token_factory()
        expires_at = self._now() + STATE_TTL
        # Only the digest is stored; a newer login replaces any pending one.
        self._write(
            WAHOO_STATE_KEY,
            {
                "state_sha256": _state_digest(state),
                "expires_at": expires_at.isoformat(),
            },
        )
        return {"authorize_url": self._oauth().authorize_url(state)}

    def _consume_state(self, state: str) -> bool:
        """Atomically validate and delete the pending state (single use)."""
        if not state or len(state) > MAX_CALLBACK_VALUE_LENGTH:
            return False
        digest = _state_digest(state)
        with self._database_lock(), self._database_manager().unit_of_work() as db:
            pending = _decode_object(self._key_values.get(db, WAHOO_STATE_KEY))
            if pending is None:
                return False
            expires_at = _parse_time(pending.get("expires_at"))
            expired = expires_at is None or expires_at <= self._now()
            matches = hmac.compare_digest(str(pending.get("state_sha256")), digest)
            # A foreign state must not be able to cancel the athlete's login.
            if matches or expired:
                self._key_values.delete(db, WAHOO_STATE_KEY)
            return matches and not expired

    def complete_authorization(
        self, code: str | None, state: str | None, error: str | None = None
    ) -> str:
        """Finish the login from the callback; returns a redirect outcome word.

        The callback carries no session (SameSite=Strict cookies are not sent
        on the cross-site redirect), so the server-stored state is the only
        proof that this login was started by the authenticated athlete.
        """
        if not self._consume_state(str(state or "")):
            return CALLBACK_ERROR
        code = str(code or "")
        if error or not code or len(code) > MAX_CALLBACK_VALUE_LENGTH:
            return CALLBACK_ERROR
        if not self._config().wahoo_configured:
            return CALLBACK_ERROR
        try:
            grant = self._oauth().exchange_code(code)
        except Exception:  # noqa: BLE001 - the callback must always redirect
            return CALLBACK_ERROR
        now = self._now()
        self._store_grant(grant, now, connected_at=now)
        return CALLBACK_CONNECTED

    # Tokens --------------------------------------------------------------

    def _store_grant(
        self, grant: WahooTokenGrant, now: datetime, *, connected_at: datetime | str
    ) -> dict[str, Any]:
        record = {
            "access_token": grant.access_token,
            "refresh_token": grant.refresh_token,
            "expires_at": (now + timedelta(seconds=grant.expires_in)).isoformat(),
            "scope": grant.scope,
            "connected_at": connected_at.isoformat()
            if isinstance(connected_at, datetime)
            else connected_at,
        }
        # One INSERT..ON CONFLICT: the rotated refresh token replaces the old
        # one in the same transaction as the new access token.
        self._write(WAHOO_TOKENS_KEY, record)
        return record

    def _stored_tokens(self) -> dict[str, Any] | None:
        tokens = _decode_object(self._read(WAHOO_TOKENS_KEY))
        if tokens and tokens.get("access_token") and tokens.get("refresh_token"):
            return tokens
        return None

    def _is_fresh(self, tokens: dict[str, Any]) -> bool:
        expires_at = _parse_time(tokens.get("expires_at"))
        return expires_at is not None and expires_at - REFRESH_MARGIN > self._now()

    def access_token(self) -> str:
        """Return a valid access token, refreshing and rotating when needed."""
        tokens = self._stored_tokens()
        if tokens is None:
            raise AppError(409, NOT_CONNECTED_MESSAGE, reason="wahoo_not_connected")
        if self._is_fresh(tokens):
            return str(tokens["access_token"])
        with self._refresh_lock:
            return self._access_token_locked()

    def _access_token_locked(self) -> str:
        # Another thread may have refreshed while this one waited.
        tokens = self._stored_tokens()
        if tokens is None:
            raise AppError(409, NOT_CONNECTED_MESSAGE, reason="wahoo_not_connected")
        if self._is_fresh(tokens):
            return str(tokens["access_token"])
        return str(self._refresh(tokens)["access_token"])

    def _refresh(self, tokens: dict[str, Any]) -> dict[str, Any]:
        try:
            grant = self._oauth().refresh(str(tokens["refresh_token"]))
        except AppError as exc:
            if exc.upstream_status in _REFRESH_REJECTED_STATUSES:
                # The refresh token is dead; keeping it would only retry forever.
                self._delete(WAHOO_TOKENS_KEY)
                raise AppError(
                    409, RECONNECT_MESSAGE, reason="wahoo_reconnect_required"
                ) from exc
            raise
        return self._store_grant(
            grant, self._now(), connected_at=str(tokens.get("connected_at") or "")
        )

    # Disconnect ----------------------------------------------------------

    def disconnect(self) -> dict[str, Any]:
        """Revoke access at Wahoo on a best-effort basis and drop local tokens."""
        remote_revoked = False
        # Holding the refresh lock keeps an in-flight refresh from writing
        # fresh tokens back after the athlete disconnected.
        with self._refresh_lock:
            if self._stored_tokens() is not None:
                try:
                    self._oauth().deauthorize(self._access_token_locked())
                    remote_revoked = True
                except Exception:  # noqa: BLE001 - local disconnect must succeed
                    remote_revoked = False
            self._delete(WAHOO_TOKENS_KEY, WAHOO_STATE_KEY)
        return {
            "status": "ok",
            "connected": False,
            "remote_revoked": remote_revoked,
        }
