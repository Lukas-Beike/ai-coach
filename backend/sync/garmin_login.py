"""Garmin login use case: credential exchange, MFA and token storage.

The Garmin SDK owns the wire protocol. This module owns the local policy: the
login and MFA flow, the OAuth token blob in the SQLCipher key/value table, the
one-time import of a legacy token file, write-back of refreshed tokens and the
explicit disconnect. The password is used for one login call and never stored.
Tokens, credentials and MFA codes are never returned from or logged by this
module; the redactor receives the live token values through
``GarminSecretRegistry``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.provider_credentials import (
    GARMIN_SOURCE_DB,
    GARMIN_SOURCE_ENV,
    GARMIN_SOURCE_FILE,
    GARMIN_SOURCE_NONE,
    GARMIN_TOKENS_KEY,
    GARMIN_TOKENSTORE_DISCONNECTED,
    GARMIN_TOKENSTORE_STATE_KEY,
)

_LOGGER = logging.getLogger(__name__)

MFA_TTL_SECONDS = 600
MAX_FIELD_LENGTH = 512
MIN_MFA_CODE_LENGTH = 4
MAX_MFA_CODE_LENGTH = 10
# Token strings shorter than this are not registered for redaction.
MIN_SECRET_LENGTH = 8
# Appended to the legacy path when no file may be read, so the SDK never falls
# back to its default token location and the path itself never exists.
ABSENT_TOKENSTORE_SUFFIX = ".disconnected"

LOGIN_FAILED_MESSAGE = (
    "Garmin-Anmeldung fehlgeschlagen. Bitte E-Mail und Passwort prüfen."
)
LOGIN_UNAVAILABLE_MESSAGE = (
    "Garmin ist derzeit nicht erreichbar. Bitte später erneut versuchen."
)
MFA_INVALID_MESSAGE = "Der MFA-Code ist ungültig. Bitte erneut eingeben."
MFA_NOT_PENDING_MESSAGE = "Keine Garmin-Anmeldung mit MFA aktiv. Bitte erneut anmelden."
MFA_EXPIRED_MESSAGE = "Die MFA-Anmeldung ist abgelaufen. Bitte erneut anmelden."
INVALID_FIELD_MESSAGE = "Ungültige Garmin-Eingabe."
TOKEN_EXPORT_MESSAGE = "Garmin-Tokens konnten nicht übernommen werden."


def _token_values(blob: str | None) -> frozenset[str]:
    """Return the secret-bearing strings of a stored token blob."""
    if not blob:
        return frozenset()
    try:
        decoded = json.loads(blob)
    except TypeError, ValueError:
        return frozenset({blob})
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and len(node.strip()) >= MIN_SECRET_LENGTH:
            found.add(node.strip())

    walk(decoded)
    return frozenset(found)


class GarminSecretRegistry:
    """Runtime-only Garmin secret values for the redactor.

    Token values are replaced whenever the stored blob changes. Credentials are
    held only for the duration of one login call.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: frozenset[str] = frozenset()
        self._transient: frozenset[str] = frozenset()

    def values(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._tokens | self._transient)

    def replace_tokens(self, blob: str | None) -> None:
        tokens = _token_values(blob)
        with self._lock:
            self._tokens = tokens

    @contextmanager
    def hold(self, *values: str) -> Iterator[None]:
        held = frozenset(value for value in values if value)
        with self._lock:
            self._transient = self._transient | held
        try:
            yield
        finally:
            with self._lock:
                self._transient = self._transient - held


class GarminTokenStore:
    """Persist the Garmin login token blob in the encrypted key/value table."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Callable[[], AbstractContextManager[Any]],
        key_values: KeyValueRepository,
        tokenstore_path: Callable[[], str],
        registry: GarminSecretRegistry,
        env_credentials: Callable[[], bool] = lambda: False,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._tokenstore_path = tokenstore_path
        self._registry = registry
        self._env_credentials = env_credentials

    def _read_blob(self) -> str | None:
        with self._database_manager().reader() as db:
            blob = self._key_values.get(db, GARMIN_TOKENS_KEY) or None
        # Every read keeps the redactor aware of the live token values.
        self._registry.replace_tokens(blob)
        return blob

    def _disconnected(self) -> bool:
        with self._database_manager().reader() as db:
            return (
                self._key_values.get(db, GARMIN_TOKENSTORE_STATE_KEY)
                == GARMIN_TOKENSTORE_DISCONNECTED
            )

    def _legacy_path(self) -> Path:
        return Path(self._tokenstore_path())

    def _legacy_readable(self) -> bool:
        return not self._disconnected() and self._legacy_path().exists()

    def source(self) -> str:
        """Return where the active login tokens come from."""
        if self._read_blob():
            return GARMIN_SOURCE_DB
        if self._legacy_readable():
            return GARMIN_SOURCE_FILE
        if self._env_credentials():
            return GARMIN_SOURCE_ENV
        return GARMIN_SOURCE_NONE

    def connected(self) -> bool:
        return self.source() in {GARMIN_SOURCE_DB, GARMIN_SOURCE_FILE}

    def login_argument(self) -> str:
        """Return the value passed to the SDK ``login(tokenstore)``.

        The stored blob wins. A preserved legacy file is read only until the
        first successful login has written the blob to the database.
        """
        blob = self._read_blob()
        if blob:
            return blob
        if self._legacy_readable():
            return str(self._legacy_path())
        return str(self._legacy_path()) + ABSENT_TOKENSTORE_SUFFIX

    def store(self, blob: str) -> None:
        if not blob:
            raise AppError(502, TOKEN_EXPORT_MESSAGE)
        with self._database_lock(), self._database_manager().unit_of_work() as db:
            self._key_values.set(db, GARMIN_TOKENS_KEY, blob)
            self._key_values.delete(db, GARMIN_TOKENSTORE_STATE_KEY)
        self._registry.replace_tokens(blob)

    def write_back(self, client: Any) -> None:
        """Store the SDK's current token blob when it differs from the stored one.

        This records refreshed tokens and performs the one-time import of a
        legacy file. Failures are logged without exception text, because the
        SDK error may echo token material.
        """
        try:
            current = client.client.dumps()
        except Exception as exc:  # noqa: BLE001 - never surface SDK internals
            _LOGGER.warning(
                "Garmin token write-back skipped",
                extra={
                    "event": "garmin_tokens_writeback_failed",
                    "context": {"error_type": type(exc).__name__},
                },
            )
            return
        if current and current != self._read_blob():
            self.store(current)

    def clear(self) -> None:
        """Remove the stored tokens and block the legacy file until reconnect."""
        with self._database_lock(), self._database_manager().unit_of_work() as db:
            self._key_values.delete(db, GARMIN_TOKENS_KEY)
            self._key_values.set(
                db, GARMIN_TOKENSTORE_STATE_KEY, GARMIN_TOKENSTORE_DISCONNECTED
            )
        self._registry.replace_tokens(None)


@dataclass
class _PendingMfa:
    client: Any
    expires_at: float


def _text_field(body: object, name: str) -> str:
    if not isinstance(body, dict):
        raise AppError(400, INVALID_FIELD_MESSAGE)
    value = body.get(name)
    if not isinstance(value, str):
        raise AppError(400, INVALID_FIELD_MESSAGE)
    text = value.strip()
    if not text or len(text) > MAX_FIELD_LENGTH:
        raise AppError(400, INVALID_FIELD_MESSAGE)
    return text


def _mfa_code(body: object) -> str:
    code = _text_field(body, "code")
    if not code.isdigit() or not (
        MIN_MFA_CODE_LENGTH <= len(code) <= MAX_MFA_CODE_LENGTH
    ):
        raise AppError(400, MFA_INVALID_MESSAGE)
    return code


class GarminLoginService:
    """Own the Garmin login, MFA and disconnect flow for the authenticated PWA."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        client_factory: Callable[..., Any],
        tokens: GarminTokenStore,
        registry: GarminSecretRegistry,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._tokens = tokens
        self._registry = registry
        self._clock = clock
        # One pending MFA slot: a second login replaces it.
        self._lock = threading.Lock()
        self._pending: _PendingMfa | None = None

    def _mfa_active(self) -> bool:
        pending = self._pending
        if pending is None:
            return False
        if self._clock() >= pending.expires_at:
            self._pending = None
            return False
        return True

    def _snapshot(self) -> dict[str, Any]:
        """Status without the lock; callers must already hold ``self._lock``."""
        source = self._tokens.source()
        return {
            "connected": source in {GARMIN_SOURCE_DB, GARMIN_SOURCE_FILE},
            "source": source,
            "mfa_pending": self._mfa_active(),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot()

    def login(self, body: object) -> dict[str, Any]:
        email = _text_field(body, "email")
        password = _text_field(body, "password")
        with self._lock:
            self._pending = None
            with self._registry.hold(email, password):
                client = self._client_factory(email, password, return_on_mfa=True)
                try:
                    needs_mfa, _ = client.login()
                except Exception as exc:  # noqa: BLE001 - SDK text is not shown
                    raise self._login_error(exc) from None
                if needs_mfa:
                    self._pending = _PendingMfa(
                        client=client, expires_at=self._clock() + MFA_TTL_SECONDS
                    )
                    return {"status": "mfa_required", **self._snapshot()}
                self._store(client)
                return {"status": "connected", **self._snapshot()}

    def submit_mfa(self, body: object) -> dict[str, Any]:
        code = _mfa_code(body)
        with self._lock:
            if self._pending is None:
                raise AppError(409, MFA_NOT_PENDING_MESSAGE)
            if not self._mfa_active():
                raise AppError(409, MFA_EXPIRED_MESSAGE)
            pending = self._pending
            try:
                pending.client.resume_login(None, code)
            except Exception as exc:  # noqa: BLE001 - keep the slot for a retry
                _LOGGER.info(
                    "Garmin MFA code rejected",
                    extra={
                        "event": "garmin_mfa_rejected",
                        "context": {"error_type": type(exc).__name__},
                    },
                )
                raise AppError(401, MFA_INVALID_MESSAGE) from None
            self._pending = None
            self._store(pending.client)
            return {"status": "connected", **self._snapshot()}

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._pending = None
            self._tokens.clear()
            return {"status": "disconnected", **self._snapshot()}

    def _store(self, client: Any) -> None:
        try:
            blob = client.client.dumps()
        except Exception as exc:  # noqa: BLE001 - never surface SDK internals
            raise self._token_error(exc) from None
        self._tokens.store(blob)

    @staticmethod
    def _login_error(exc: BaseException) -> AppError:
        _LOGGER.warning(
            "Garmin login failed",
            extra={
                "event": "garmin_login_failed",
                "context": {"error_type": type(exc).__name__},
            },
        )
        if type(exc).__name__ in {"GarminConnectAuthenticationError"}:
            return AppError(401, LOGIN_FAILED_MESSAGE)
        return AppError(502, LOGIN_UNAVAILABLE_MESSAGE)

    @staticmethod
    def _token_error(exc: BaseException) -> AppError:
        _LOGGER.warning(
            "Garmin token export failed",
            extra={
                "event": "garmin_tokens_export_failed",
                "context": {"error_type": type(exc).__name__},
            },
        )
        return AppError(502, TOKEN_EXPORT_MESSAGE)
