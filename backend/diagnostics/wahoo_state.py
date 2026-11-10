"""Secret-free Wahoo connection and last-sync state for diagnostics.

Reports whether the grant exists, its scope, whether the access token is still
valid, and the last sync time and redacted error. Tokens, expiry times and
provider payloads never leave this module.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.config import Config
from backend.db.repositories import KeyValueRepository
from backend.provider_credentials import WAHOO_TOKENS_KEY
from backend.sync.wahoo_connection import access_token_state, connection_status
from backend.sync.wahoo_sync import LAST_ERROR_KEY, LAST_SYNC_KEY


def summarize_wahoo(
    key_values: KeyValueRepository,
    db: Any,
    config: Config,
    redact_text: Callable[[str], str],
    now: datetime,
) -> dict[str, Any]:
    """Project the Wahoo grant and the last sync outcome."""
    raw_tokens = key_values.get(db, WAHOO_TOKENS_KEY)
    status = connection_status(config, raw_tokens)
    return {
        "configured": status["configured"],
        "connected": status["connected"],
        "scope": status["scope"],
        "access_token": access_token_state(raw_tokens, now),
        "last_wahoo_sync_at": key_values.get(db, LAST_SYNC_KEY) or None,
        "last_wahoo_sync_error": redact_text(key_values.get(db, LAST_ERROR_KEY) or "")
        or None,
    }
