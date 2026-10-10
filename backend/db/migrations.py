"""Versioned, transactional upgrades of supported encrypted application schemas."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    NUTRITION_PRODUCTS_DDL,
    database_schema_is_current,
    database_schema_signature,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    SHAPE_CURRENT,
    SHAPE_RELEASE_1_12_19,
    SHAPE_SCHEMA_V2,
    SHAPE_SCHEMA_V3_V4,
    released_shape,
)

_UNSUPPORTED_SCHEMA_MESSAGE = (
    "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
    "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
)


def migrate_schema(db: Any) -> None:
    """Upgrade supported schemas and remove retired Gemini conversation state.

    The stored version and the frozen shape of the database are checked before
    any write. A supported shape is then upgraded step by step inside one
    savepoint. The caller owns the commit. Individual DDL statements deliberately
    avoid executescript(), whose implicit commit would break rollback on failure.
    """
    version = db.execute("PRAGMA user_version").fetchone()["user_version"]
    if version not in ACCEPTED_SHAPES_BY_VERSION:
        raise RuntimeError(
            "Die Datenbankversion wird von diesem Release nicht unterstützt."
        )
    current = database_schema_is_current(db)
    shape = SHAPE_CURRENT if current else released_shape(database_schema_signature(db))
    if shape is None or shape not in ACCEPTED_SHAPES_BY_VERSION[version]:
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MESSAGE)
    if current and version == CURRENT_SCHEMA_VERSION:
        return
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT schema_migration")
    try:
        if shape != SHAPE_CURRENT:
            _upgrade_from_shape(db, shape)
        _remove_gemini_state(db)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        if not database_schema_is_current(db):
            raise RuntimeError("Die Datenbankmigration konnte nicht validiert werden.")
    except Exception:
        db.execute("ROLLBACK TO schema_migration")
        db.execute("RELEASE schema_migration")
        raise
    db.execute("RELEASE schema_migration")


def _upgrade_from_shape(db: Any, shape: str) -> None:
    """Apply the registered steps, in order, from a released shape to the live one."""
    pending = shape
    while pending != SHAPE_CURRENT:
        next_shape, step = UPGRADE_STEPS[pending]
        step(db)
        pending = next_shape


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous receipt fields")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> Any:
    raise ValueError("Invalid JSON constant")


def _json_object(value: Any) -> dict[str, Any] | None:
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_unique_json_object,
            parse_constant=_invalid_json_constant,
        )
    except TypeError, ValueError, RecursionError:
        return None
    return decoded if isinstance(decoded, dict) else None


_GEMINI_RECEIPT_KEYS = (
    "ai_provider",
    "model",
    "session_key",
    "user_message_id",
    "message",
    "text",
    "intent",
    "pending_operations",
    "pending_tool_calls",
    "pending_tool_outputs",
    "response_input",
    "previous_response_id",
    "openai_response_id",
)


def _scrub_gemini_command(db: Any, row: Any, receipt: dict[str, Any]) -> None:
    client_turn_id = str(row["client_turn_id"] or "")
    if row["status"] in ("queued", "running"):
        receipt = {
            "status": "cancelled",
            "phase": "migration_gemini_removed",
            "error": "gemini_provider_state_removed",
        }
        db.execute(
            "UPDATE coach_commands SET conversation_id=NULL, intent='{}', "
            "status='cancelled', error_class='gemini_provider_state_removed', "
            "receipt=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE client_turn_id=?",
            (json.dumps(receipt, separators=(",", ":")), client_turn_id),
        )
        return
    for key in _GEMINI_RECEIPT_KEYS:
        receipt.pop(key, None)
    db.execute(
        "UPDATE coach_commands SET conversation_id=NULL, intent='{}', receipt=? "
        "WHERE client_turn_id=?",
        (
            json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
            client_turn_id,
        ),
    )


def _scrub_gemini_commands(db: Any) -> list[str]:
    gemini_turn_ids: list[str] = []
    rows = db.execute(
        "SELECT client_turn_id, status, receipt FROM coach_commands"
    ).fetchall()
    for row in rows:
        receipt = _json_object(row["receipt"])
        if receipt is None or receipt.get("ai_provider") != "gemini":
            continue
        if row["client_turn_id"]:
            gemini_turn_ids.append(str(row["client_turn_id"]))
        _scrub_gemini_command(db, row, receipt)
    return gemini_turn_ids


def _delete_gemini_dialogue(db: Any, gemini_turn_ids: list[str]) -> None:
    gemini_message_ids = {
        message["id"]
        for turn_id in gemini_turn_ids
        for message in db.execute(
            "SELECT id FROM messages WHERE client_turn_id=?", (turn_id,)
        )
    }
    pending_row = db.execute(
        "SELECT value FROM kv WHERE key='coach_pending_request'"
    ).fetchone()
    pending = _json_object(pending_row["value"]) if pending_row else None
    source_ids = pending.get("source_message_ids") if pending else None
    if (
        isinstance(source_ids, list)
        and source_ids
        and all(
            type(message_id) is int and message_id in gemini_message_ids
            for message_id in source_ids
        )
    ):
        db.execute("DELETE FROM kv WHERE key='coach_pending_request'")
    db.executemany(
        "DELETE FROM messages WHERE client_turn_id=?",
        ((turn_id,) for turn_id in gemini_turn_ids),
    )
    db.executemany(
        "UPDATE coach_plan_artifacts SET conversation_id=NULL, "
        "updated_at=CURRENT_TIMESTAMP WHERE client_turn_id=?",
        ((turn_id,) for turn_id in gemini_turn_ids),
    )


def _remove_gemini_state(db: Any) -> None:
    """Erase attributable Gemini dialogue, retaining durable action records.

    Command receipts, proposal rows, and plan artifact payloads record local
    effects; only turn intent and pending dialogue state are discarded.
    """
    gemini_turn_ids = _scrub_gemini_commands(db)
    if gemini_turn_ids:
        _delete_gemini_dialogue(db, gemini_turn_ids)
    for table in ("coach_commands", "coach_plan_artifacts"):
        db.execute(
            f"UPDATE {table} SET conversation_id=NULL, "
            "updated_at=CURRENT_TIMESTAMP "
            "WHERE substr(conversation_id, 1, 7)='gemini_' "
            "OR conversation_id IN (SELECT value FROM kv "
            "WHERE key='gemini_conversation_id' AND value!='' "
            "AND value NOT IN (SELECT value FROM kv WHERE key='openai_conversation_id'))"
        )
    db.execute(
        "UPDATE kv SET value='openai', updated_at=CURRENT_TIMESTAMP "
        "WHERE key='selected_ai_provider' AND value='gemini'"
    )
    db.execute(
        "DELETE FROM kv WHERE key GLOB 'gemini_*' "
        "OR key='selected_model_gemini' "
        "OR (key='last_coach_ai_provider' AND value='gemini')"
    )


def _add_nutrition_products(db: Any) -> None:
    """Released shape 1.12.19 -> schema version 2."""
    for statement in NUTRITION_PRODUCTS_DDL.split(";"):
        if statement.strip():
            db.execute(statement)


def _add_no_training_signal(db: Any) -> None:
    """Schema version 2 -> schema versions 3 and 4."""
    db.execute(
        "ALTER TABLE external_calendar_events "
        "ADD COLUMN no_training INTEGER NOT NULL DEFAULT 0"
    )
    # v2 discarded descriptions; irrelevant rows can be ordinary appointments
    # or description-only NO_TRAINING markers. Require fresh evidence rather
    # than assigning a hard marker to an ambiguous row.
    db.execute(
        "UPDATE external_calendar_events SET no_training=1 "
        "WHERE instr(upper(name), '[NO_TRAINING]') > 0"
    )
    db.execute(
        "INSERT OR REPLACE INTO kv(key, value, updated_at) "
        "SELECT 'external_calendar_constraints_refresh_required', '1', MAX(updated_at) "
        "FROM external_calendar_events WHERE training_relevant=0 AND no_training=0 "
        "HAVING COUNT(*) > 0"
    )


def _add_logged_time_known(db: Any) -> None:
    """Schema versions 3 and 4 -> the current schema."""
    # Existing meal logs were recorded with a time; they keep logged_time_known=1.
    db.execute(
        "ALTER TABLE nutrition_logs ADD COLUMN logged_time_known INTEGER NOT NULL DEFAULT 1"
    )


UpgradeStep = Callable[[Any], None]

# Released shape -> (shape reached after the step, step). Every released shape
# is upgraded through the chain ending at the current shape.
UPGRADE_STEPS: Final[Mapping[str, tuple[str, UpgradeStep]]] = {
    SHAPE_RELEASE_1_12_19: (SHAPE_SCHEMA_V2, _add_nutrition_products),
    SHAPE_SCHEMA_V2: (SHAPE_SCHEMA_V3_V4, _add_no_training_signal),
    SHAPE_SCHEMA_V3_V4: (SHAPE_CURRENT, _add_logged_time_known),
}
