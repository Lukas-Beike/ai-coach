"""Application database bootstrap and bounded startup cleanup."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import (
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)


def initialize_application_database(
    db: Any,
    *,
    key_values: KeyValueRepository,
    now: str,
    current_time: datetime,
    default_profile_json: str,
    provider_resync_keys: Iterable[Mapping[str, str]],
    retention_days: int,
    all_sync_days: int,
) -> None:
    """Create and validate the application schema, then apply startup state."""
    if db.execute("PRAGMA user_version").fetchone()[
        "user_version"
    ] == 0 and not database_schema_signature(db):
        initialize_schema(db)
    else:
        migrate_schema(db)

    db.execute(
        "INSERT OR IGNORE INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
        (now,),
    )
    if not database_schema_is_current(db):
        raise RuntimeError(
            "Die neue Datenbank konnte nicht mit dem aktuellen Schema initialisiert werden."
        )

    if key_values.get(db, "profile") is None:
        key_values.set(db, "profile", default_profile_json)

    for provider_keys in provider_resync_keys:
        key_values.set(db, provider_keys["running"], "0")
        key_values.set(db, provider_keys["status"], "")

    if retention_days != all_sync_days:
        bounded_retention_days = max(30, min(retention_days, 3650))
        cutoff = (current_time - timedelta(days=bounded_retention_days)).isoformat()
        db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        db.execute("DELETE FROM snapshots WHERE created_at < ?", (cutoff,))
        db.execute(
            "UPDATE kv SET value='[]', updated_at=? "
            "WHERE key='gemini_conversation_history'",
            (now,),
        )
        db.execute(
            "UPDATE kv SET value='{}', updated_at=? WHERE key='gemini_call_names'",
            (now,),
        )
