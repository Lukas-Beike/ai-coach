"""Application database bootstrap and bounded startup cleanup."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from backend.change_history import RETENTION_DAYS
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import (
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)

LOGGER = logging.getLogger("intervals_coach")


# The change-history references a receipt's tool steps carry (``turn_changes``).
_UNDO_REFERENCES = (
    "SELECT 1 FROM json_each(receipt, '$.command_receipts') AS step, "
    "json_each(CASE WHEN step.type = 'object' THEN step.value ELSE '{}' END, "
    "'$.changes') AS change WHERE 1"
)


def apply_startup_invariants(
    db: Any,
    *,
    key_values: KeyValueRepository,
    now: str,
    default_profile_json: str,
    provider_resync_keys: Iterable[Mapping[str, str]],
) -> None:
    """Idempotent state every running database needs; shared with restore."""
    db.execute(
        "INSERT OR IGNORE INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
        (now,),
    )
    if key_values.get(db, "profile") is None:
        key_values.set(db, "profile", default_profile_json)
    for provider_keys in provider_resync_keys:
        key_values.set(db, provider_keys["running"], "0")
        key_values.set(db, provider_keys["status"], "")


def initialize_application_database(
    db: Any,
    *,
    key_values: KeyValueRepository,
    now: str,
    current_time: datetime,
    default_profile_json: str,
    provider_resync_keys: Iterable[Mapping[str, str]],
    retention_days: int,
) -> None:
    """Create and validate the application schema, then apply startup state."""
    if db.execute("PRAGMA user_version").fetchone()[
        "user_version"
    ] == 0 and not database_schema_signature(db):
        initialize_schema(db)
    else:
        migrate_schema(db)

    if not database_schema_is_current(db):
        raise RuntimeError(
            "Die neue Datenbank konnte nicht mit dem aktuellen Schema initialisiert werden."
        )
    apply_startup_invariants(
        db,
        key_values=key_values,
        now=now,
        default_profile_json=default_profile_json,
        provider_resync_keys=provider_resync_keys,
    )

    # Values <= 0 (including the documented -1) retain data indefinitely.
    if retention_days > 0:
        bounded_retention_days = max(30, min(retention_days, 3650))
        cutoff = (current_time - timedelta(days=bounded_retention_days)).isoformat()
        messages_deleted = db.execute(
            "DELETE FROM messages WHERE created_at < ?", (cutoff,)
        ).rowcount
        # The newest snapshot is the latest provider state, even when it is old.
        snapshots_deleted = db.execute(
            "DELETE FROM snapshots WHERE created_at < ? "
            "AND id <> (SELECT MAX(id) FROM snapshots)",
            (cutoff,),
        ).rowcount
        # Receipts hold copies of the chat; a turn whose changes can still be
        # undone keeps its receipt, which is the only place that lists them. It
        # can be undone only while every change-history row it names is kept
        # and inside the history's retention window (#2134, K-003).
        history_cutoff = (current_time - timedelta(days=RETENTION_DAYS)).isoformat()
        commands_deleted = db.execute(
            "DELETE FROM coach_commands WHERE status='completed' AND created_at < ? "
            "AND NOT CASE WHEN json_valid(receipt) THEN "
            "COALESCE(json_extract(receipt, '$.change_summary.undoable') = 1 "
            "AND json_extract(receipt, '$.change_summary.undone_at') IS NULL, 0) "
            f"AND EXISTS ({_UNDO_REFERENCES}) "
            f"AND NOT EXISTS ({_UNDO_REFERENCES} AND json_extract(change.value, '$.id') "
            "NOT IN (SELECT id FROM change_history WHERE created_at >= ?)) "
            "ELSE 0 END",
            (cutoff, history_cutoff),
        ).rowcount
        artifacts_deleted = db.execute(
            "DELETE FROM coach_plan_artifacts WHERE status <> 'draft' "
            "AND created_at < ? AND id NOT IN "
            "(SELECT artifact_id FROM coach_commands WHERE artifact_id IS NOT NULL)",
            (cutoff,),
        ).rowcount
        proposals_deleted = db.execute(
            "DELETE FROM coach_action_proposals WHERE expires_at <= ?",
            (current_time.timestamp(),),
        ).rowcount
        LOGGER.info(
            "Data retention purge completed",
            extra={
                "event": "data_retention_purged",
                "context": {
                    "retention_days": bounded_retention_days,
                    "messages_deleted": messages_deleted,
                    "snapshots_deleted": snapshots_deleted,
                    "coach_commands_deleted": commands_deleted,
                    "coach_plan_artifacts_deleted": artifacts_deleted,
                    "coach_action_proposals_deleted": proposals_deleted,
                },
            },
        )
