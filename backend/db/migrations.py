"""Versioned, transactional upgrades of supported encrypted application schemas."""

from __future__ import annotations

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


def migrate_schema(db: Any) -> None:
    """Upgrade 1.12.19 or adopt unversioned 1.12.20 without touching athlete rows.

    The caller owns the commit. Individual DDL statements deliberately avoid
    executescript(), whose implicit commit would break rollback on failure.
    """
    version = db.execute("PRAGMA user_version").fetchone()["user_version"]
    if version not in (0, 1, 2, CURRENT_SCHEMA_VERSION):
        raise RuntimeError(
            "Die Datenbankversion wird von diesem Release nicht unterstützt."
        )
    current = database_schema_is_current(db)
    previous_calendar_schema = not current and _schema_is_previous_calendar_schema(db)
    old_schema = not current and _schema_is_1_12_19(db)
    if not current and version == CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            "Die vorhandene Datenbank entspricht keinem unterstÃ¼tzten Schema. "
            "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
        )
    if not current and not (old_schema or previous_calendar_schema):
        raise RuntimeError(
            "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
            "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
        )
    if current and version == CURRENT_SCHEMA_VERSION:
        return
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT schema_migration")
    try:
        if not current:
            _upgrade_legacy_schema(db, old_schema)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        if not database_schema_is_current(db):
            raise RuntimeError("Die Datenbankmigration konnte nicht validiert werden.")
    except Exception:
        db.execute("ROLLBACK TO schema_migration")
        db.execute("RELEASE schema_migration")
        raise
    db.execute("RELEASE schema_migration")


def _upgrade_legacy_schema(db: Any, old_schema: bool) -> None:
    if old_schema:
        for statement in NUTRITION_PRODUCTS_DDL.split(";"):
            if statement.strip():
                db.execute(statement)
    db.execute(
        "ALTER TABLE external_calendar_events "
        "ADD COLUMN no_training INTEGER NOT NULL DEFAULT 0"
    )
    # v2 discarded descriptions but retained NO_TRAINING as training_relevant=0.
    # Preserve this safety signal until a successful sync supplies fresh markers.
    db.execute(
        "UPDATE external_calendar_events SET no_training=1 "
        "WHERE training_relevant=0 OR instr(upper(name), '[NO_TRAINING]') > 0"
    )
