"""Versioned, transactional upgrades of supported encrypted application schemas."""

from __future__ import annotations

import json
from typing import Any

from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    NUTRITION_PRODUCTS_DDL,
    current_schema_signature,
    database_schema_is_current,
    database_schema_signature,
)


def _schema_is_1_12_19(db: Any) -> bool:
    expected = tuple(
        (
            definition[0],
            definition[1],
            definition[2],
            definition[3].replace(", no_training INTEGER NOT NULL DEFAULT 0", ""),
        )
        for definition in current_schema_signature()
        if definition[2] != "nutrition_products"
    )
    return database_schema_signature(db) == expected


def _schema_is_previous_calendar_schema(db: Any) -> bool:
    """Recognize the released schema immediately before no_training."""
    expected = tuple(
        (
            definition[0],
            definition[1],
            definition[2],
            definition[3].replace(", no_training INTEGER NOT NULL DEFAULT 0", ""),
        )
        if definition[2] == "external_calendar_events"
        else definition
        for definition in current_schema_signature()
    )
    return database_schema_signature(db) == expected


_UNSUPPORTED_SCHEMA_MESSAGE = (
    "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
    "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
)


def _schema_unsupported(
    version: int,
    current: bool,
    current_shape: bool,
    old_schema: bool,
    previous_calendar_schema: bool,
) -> bool:
    if version == 1:
        return not old_schema
    if version == 2:
        return not previous_calendar_schema
    if version == 3 and not current_shape:
        return True
    if current:
        return False
    if version == CURRENT_SCHEMA_VERSION:
        return True
    return not (current_shape or old_schema or previous_calendar_schema)


def migrate_schema(db: Any) -> None:
    """Upgrade supported schemas and remove retired Gemini conversation state.

    The caller owns the commit. Individual DDL statements deliberately avoid
    executescript(), whose implicit commit would break rollback on failure.
    """
    version = db.execute("PRAGMA user_version").fetchone()["user_version"]
    if version not in (0, 1, 2, 3, CURRENT_SCHEMA_VERSION):
        raise RuntimeError(
            "Die Datenbankversion wird von diesem Release nicht unterstützt."
        )
    current = database_schema_is_current(db)
    current_shape = database_schema_signature(db) == current_schema_signature()
    previous_calendar_schema = not current and _schema_is_previous_calendar_schema(db)
    old_schema = not current and _schema_is_1_12_19(db)
    if _schema_unsupported(
        version, current, current_shape, old_schema, previous_calendar_schema
    ):
        raise RuntimeError(_UNSUPPORTED_SCHEMA_MESSAGE)
    if current and version == CURRENT_SCHEMA_VERSION:
        return
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT schema_migration")
    try:
        if not current_shape and not current:
            _upgrade_legacy_schema(db, old_schema)
        _remove_gemini_state(db)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        if not database_schema_is_current(db):
            raise RuntimeError("Die Datenbankmigration konnte nicht validiert werden.")
    except Exception:
        db.execute("ROLLBACK TO schema_migration")
        db.execute("RELEASE schema_migration")
        raise
    db.execute("RELEASE schema_migration")


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


def _upgrade_legacy_schema(db: Any, old_schema: bool) -> None:
    if old_schema:
        for statement in NUTRITION_PRODUCTS_DDL.split(";"):
            if statement.strip():
                db.execute(statement)
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
