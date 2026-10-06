"""Versioned, transactional upgrades of supported encrypted application schemas."""

from __future__ import annotations

from typing import Any

from backend.db.schema import (
    CURRENT_DATABASE_INDEXES,
    CURRENT_DATABASE_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    NUTRITION_PRODUCTS_DDL,
    database_index_names,
    database_schema_is_current,
    database_table_names,
)


def _schema_is_1_12_19(db: Any) -> bool:
    expected_tables = set(CURRENT_DATABASE_SCHEMA) - {"nutrition_products"}
    expected_indexes = CURRENT_DATABASE_INDEXES - {
        "idx_nutrition_products_name",
        "idx_nutrition_products_status",
    }
    if (
        database_table_names(db) != expected_tables
        or database_index_names(db) != expected_indexes
    ):
        return False
    return all(
        columns == {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for table, columns in CURRENT_DATABASE_SCHEMA.items()
        if table != "nutrition_products"
    )


def migrate_schema(db: Any) -> None:
    """Upgrade 1.12.19 or adopt unversioned 1.12.20 without touching athlete rows.

    The caller owns the commit. Individual DDL statements deliberately avoid
    executescript(), whose implicit commit would break rollback on failure.
    """
    version = db.execute("PRAGMA user_version").fetchone()["user_version"]
    if version not in (0, 1, CURRENT_SCHEMA_VERSION):
        raise RuntimeError(
            "Die Datenbankversion wird von diesem Release nicht unterstützt."
        )
    current = database_schema_is_current(db)
    if not current and (
        version == CURRENT_SCHEMA_VERSION or not _schema_is_1_12_19(db)
    ):
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
            for statement in NUTRITION_PRODUCTS_DDL.split(";"):
                if statement.strip():
                    db.execute(statement)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        if not database_schema_is_current(db):
            raise RuntimeError("Die Datenbankmigration konnte nicht validiert werden.")
    except Exception:
        db.execute("ROLLBACK TO schema_migration")
        db.execute("RELEASE schema_migration")
        raise
    db.execute("RELEASE schema_migration")
