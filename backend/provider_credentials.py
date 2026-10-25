"""Provider credentials stored in the encrypted key/value table.

Credentials entered in the PWA live in the SQLCipher ``kv`` table and take
precedence over the environment. Environment values stay the read-only
fallback. Only non-empty stored values override the environment, so clearing a
field restores the environment value.

This module owns the storage keys, the field policy and the effective
configuration. It never returns secret values in status projections, and the
key set in ``CREDENTIAL_KV_KEYS`` is excluded from export, diagnostics and
privacy-state reads.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, cast

from backend.canonical.vocabulary import ProviderId
from backend.config import Config, validated_openai_base_url
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError

_LOGGER = logging.getLogger(__name__)

PROVIDER_CREDENTIALS_KEY = "provider_credentials"
GARMIN_TOKENS_KEY = "garmin_oauth_tokens"
# "disconnected" after an explicit disconnect, so a preserved legacy token file
# is not imported again on the next sync.
GARMIN_TOKENSTORE_STATE_KEY = "garmin_tokenstore_state"
GARMIN_TOKENSTORE_DISCONNECTED = "disconnected"
WAHOO_TOKENS_KEY = f"{ProviderId.WAHOO.value}_oauth_tokens"
WAHOO_STATE_KEY = f"{ProviderId.WAHOO.value}_oauth_state"
# Keys that must never leave the database through export, diagnostics or context.
WAHOO_SECRET_KEYS = frozenset({WAHOO_TOKENS_KEY, WAHOO_STATE_KEY})
CREDENTIAL_KV_KEYS = frozenset(
    {PROVIDER_CREDENTIALS_KEY, GARMIN_TOKENS_KEY, GARMIN_TOKENSTORE_STATE_KEY}
) | (WAHOO_SECRET_KEYS)

# Secret values: never returned, only their source and presence.
SECRET_FIELDS = frozenset(
    {
        "openai_api_key",
        "intervals_api_key",
        "wahoo_client_secret",
        "yazio_password",
        "yazio_client_id",
        "yazio_client_secret",
    }
)
# Non-secret values that the PWA may display.
VISIBLE_FIELDS = frozenset(
    {"openai_base_url", "intervals_athlete_id", "wahoo_client_id"}
)
# Reported as configured only; the address itself is not echoed back.
MASKED_FIELDS = frozenset({"garmin_email", "yazio_email"})
CREDENTIAL_FIELDS = SECRET_FIELDS | VISIBLE_FIELDS | MASKED_FIELDS

MAX_VALUE_LENGTH = 4096
SOURCE_DB = "db"
SOURCE_ENV = "env"
SOURCE_NONE = "none"
# Garmin connection sources: where the login tokens currently come from.
GARMIN_SOURCE_DB = "db"
GARMIN_SOURCE_FILE = "file"
GARMIN_SOURCE_ENV = "env"
GARMIN_SOURCE_NONE = "none"


def _is_control(char: str) -> bool:
    return ord(char) < 32 or ord(char) == 127


def stored_credentials(raw: str | None) -> dict[str, str]:
    """Decode the stored credential object, keeping only known non-empty fields."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except TypeError, ValueError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        field: text
        for field, text in value.items()
        if field in CREDENTIAL_FIELDS and isinstance(text, str) and text.strip()
    }


def _with_values(config: Config, values: Mapping[str, Any]) -> Config:
    # dataclasses.replace is typed as returning the generic dataclass protocol.
    return cast(Config, dataclasses.replace(config, **values))


def effective_config(env_config: Config, stored: Mapping[str, str]) -> Config:
    """Return the runtime configuration with stored credentials overlaid.

    A stored base URL that no longer validates is ignored with a warning rather
    than failing boot; the environment value then applies.
    """
    overrides: dict[str, str] = {}
    for field, value in stored.items():
        if field not in CREDENTIAL_FIELDS:
            continue
        if field == "openai_base_url":
            try:
                value = validated_openai_base_url(value)
            except AppError:
                _LOGGER.warning(
                    "Ignoring stored OPENAI_BASE_URL that failed validation",
                    extra={"event": "provider_credential_invalid", "setting": field},
                )
                continue
        overrides[field] = value
    if not overrides:
        return env_config
    return _with_values(env_config, overrides)


def credential_status(
    env_config: Config,
    stored: Mapping[str, str],
    *,
    garmin_source: str = GARMIN_SOURCE_NONE,
) -> dict[str, Any]:
    """Project per-field source and presence without any secret value."""
    effective = effective_config(env_config, stored)
    fields: dict[str, Any] = {}
    for field in sorted(CREDENTIAL_FIELDS):
        if field in stored:
            source = SOURCE_DB
        elif str(getattr(env_config, field, "") or "").strip():
            source = SOURCE_ENV
        else:
            source = SOURCE_NONE
        entry: dict[str, Any] = {
            "source": source,
            "configured": source != SOURCE_NONE,
        }
        if field in VISIBLE_FIELDS:
            entry["value"] = str(getattr(effective, field, "") or "")
        fields[field] = entry
    return {
        "fields": fields,
        "garmin_connected": garmin_source in {GARMIN_SOURCE_DB, GARMIN_SOURCE_FILE},
        "garmin_connection_source": garmin_source,
        "openai_configured": bool(effective.openai_api_key.strip()),
        "intervals_configured": bool(
            effective.intervals_api_key.strip()
            and str(effective.intervals_athlete_id).strip()
        ),
        "wahoo_configured": effective.wahoo_configured,
        "yazio_configured": effective.yazio_configured,
    }


def garmin_tokens_connected(
    read_value: Callable[[str], str | None], tokenstore_path: str
) -> bool:
    """Configured signal: a DB token exists, or an un-imported legacy file does.

    Mirrors ``GarminTokenStore.source()`` without requiring a live store, so
    read-only status sites can use the same rule as the login service.
    """
    if (read_value(GARMIN_TOKENS_KEY) or "").strip():
        return True
    if read_value(GARMIN_TOKENSTORE_STATE_KEY) == GARMIN_TOKENSTORE_DISCONNECTED:
        return False
    return Path(tokenstore_path).exists()


def _validated_change(field: str, value: object) -> str | None:
    """Return the cleaned value, or None to clear the stored field."""
    if field not in CREDENTIAL_FIELDS:
        raise AppError(400, "Unbekanntes Zugangsdatenfeld.")
    if value is None:
        return None
    if not isinstance(value, str):
        raise AppError(400, f"Ungültiger Wert für {field}.")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_VALUE_LENGTH or any(_is_control(char) for char in text):
        raise AppError(400, f"Ungültiger Wert für {field}.")
    if field == "openai_base_url":
        try:
            return validated_openai_base_url(text)
        except AppError as exc:
            raise AppError(
                400, "OPENAI_BASE_URL muss HTTPS oder HTTP auf Loopback verwenden."
            ) from exc
    return text


def _intervals_data_exists(db: Any) -> bool:
    provider = ProviderId.INTERVALS.value
    return any(
        db.execute(
            f"SELECT 1 FROM {table} WHERE provider = ? LIMIT 1", (provider,)
        ).fetchone()
        for table in ("provider_records", "provider_sync_cursors")
    )


def validated_changes(values: object) -> dict[str, str | None]:
    """Validate a whole submission before anything is written."""
    if not isinstance(values, dict):
        raise AppError(400, "Die Zugangsdaten müssen als Objekt gesendet werden.")
    return {field: _validated_change(field, value) for field, value in values.items()}


class ProviderCredentialService:
    """Read, update and apply the stored provider credentials."""

    def __init__(
        self,
        *,
        env_config: Config,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Callable[[], AbstractContextManager[Any]],
        key_values: KeyValueRepository,
        apply_config: Callable[[Config], None],
        garmin_connection: Callable[[], dict[str, Any]] | None = None,
        current_config: Callable[[], Config] | None = None,
    ) -> None:
        self._env_config = env_config
        # The running configuration; refresh only changes credential fields on it.
        self._current_config = current_config or (lambda: env_config)
        # Fields a previous refresh overrode from the database.
        self._overridden: frozenset[str] = frozenset()
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._apply_config = apply_config
        self._garmin_connection = garmin_connection

    def _read_stored(self) -> dict[str, str]:
        with self._database_manager().reader() as db:
            return stored_credentials(
                self._key_values.get(db, PROVIDER_CREDENTIALS_KEY)
            )

    def _garmin_status(self) -> dict[str, Any]:
        if self._garmin_connection is not None:
            return self._garmin_connection()
        with self._database_manager().reader() as db:
            source = (
                GARMIN_SOURCE_DB
                if self._key_values.get(db, GARMIN_TOKENS_KEY)
                else GARMIN_SOURCE_NONE
            )
        return {
            "connected": source == GARMIN_SOURCE_DB,
            "source": source,
            "mfa_pending": False,
        }

    def status(self) -> dict[str, Any]:
        garmin = self._garmin_status()
        return {
            **credential_status(
                self._env_config,
                self._read_stored(),
                garmin_source=str(garmin.get("source") or GARMIN_SOURCE_NONE),
            ),
            "garmin_connection": garmin,
        }

    def refresh(self) -> Config:
        """Recompute the runtime configuration from env plus stored credentials.

        Read and apply happen under the database lock, so concurrent saves or a
        privacy deletion apply their configurations in commit order. Only
        credential fields change: a field no longer stored returns to its
        environment value, and every other runtime setting is kept.
        """
        with self._database_lock():
            stored = self._read_stored()
            current = self._current_config()
            base = _with_values(
                current,
                {field: getattr(self._env_config, field) for field in self._overridden},
            )
            effective = effective_config(base, stored)
            self._overridden = frozenset(stored) & CREDENTIAL_FIELDS
            if effective != current:
                self._apply_config(effective)
        return effective

    def _athlete_id(self, stored: Mapping[str, str]) -> str:
        value = (
            stored.get("intervals_athlete_id") or self._env_config.intervals_athlete_id
        )
        return str(value or "").strip()

    def update(self, values: object) -> dict[str, Any]:
        """Apply a validated submission; null or empty clears a field."""
        changes = validated_changes(values)
        if changes:
            with self._database_lock(), self._database_manager().unit_of_work() as db:
                current = stored_credentials(
                    self._key_values.get(db, PROVIDER_CREDENTIALS_KEY)
                )
                previous_athlete = self._athlete_id(current)
                for field, value in changes.items():
                    if value is None:
                        current.pop(field, None)
                    else:
                        current[field] = value
                # Records and cursors are not scoped by athlete; syncing another
                # athlete into them would mix both histories.
                if (
                    previous_athlete
                    and self._athlete_id(current) != previous_athlete
                    and _intervals_data_exists(db)
                ):
                    raise AppError(
                        409,
                        "Die Intervals.icu-Athlete-ID kann nicht geändert werden, "
                        "solange Intervals.icu-Daten gespeichert sind. Lösche "
                        "zuerst die lokalen Daten unter Datenschutz.",
                    )
                if current:
                    self._key_values.set(
                        db,
                        PROVIDER_CREDENTIALS_KEY,
                        json.dumps(current, separators=(",", ":"), sort_keys=True),
                    )
                else:
                    self._key_values.delete(db, PROVIDER_CREDENTIALS_KEY)
            self.refresh()
        return self.status()
