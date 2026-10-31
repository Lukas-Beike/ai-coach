"""Versioned, transactional upgrades of supported encrypted application schemas.

The oldest supported schema is version 9, written by release 1.13.6. Older
databases and backups are rejected unchanged; upgrade them with release 1.13.6
first. Every released schema from version 9 onward keeps its frozen fixture in
tests/fixtures, its digest in backend.db.schema_history and an upgrade step
here, so each supported release still reaches the current schema.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend.db.garmin_items_migration import split_garmin_snapshot
from backend.db.planning_fields_migration import rename_planning_fields_in_database
from backend.db.power_curve_migration import copy_power_curve_to_raw_record
from backend.db.schema import (
    ACTIVITY_DETAIL_DDL,
    CANONICAL_EXTENSIONS_DDL,
    CURRENT_SCHEMA_VERSION,
    FOOD_DATABASE_DDL,
    NUTRITION_PRODUCTS_DDL,
    POWER_CURVE_DDL,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V9,
    SHAPE_SCHEMA_V10,
    SHAPE_SCHEMA_V11,
    SHAPE_SCHEMA_V12,
    SHAPE_SCHEMA_V13,
    SHAPE_SCHEMA_V14,
    SHAPE_SCHEMA_V15,
    SHAPE_SCHEMA_V16,
    released_shape,
)

_UNSUPPORTED_SCHEMA_MESSAGE = (
    "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
    "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
)


def migrate_schema(db: Any) -> None:
    """Upgrade a supported schema to the current one, or reject it unchanged.

    The stored version and the frozen shape of the database are checked before
    any write. A supported shape is then upgraded step by step inside one
    savepoint. The caller owns the commit. DDL runs statement by statement,
    because executescript() would commit implicitly and break rollback.
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
    if shape == SHAPE_CURRENT:
        return
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT schema_migration")
    try:
        _upgrade_from_shape(db, shape)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        if not database_schema_is_current(db):
            raise RuntimeError("Die Datenbankmigration konnte nicht validiert werden.")
    except Exception:
        _abandon_migration_savepoint(db)
        raise
    db.execute("RELEASE schema_migration")


def _abandon_migration_savepoint(db: Any) -> None:
    # Errors such as SQLITE_FULL can roll the whole transaction back and drop
    # the savepoint. Cleanup must never replace the original error; the
    # caller's rollback still discards whatever this could not undo.
    if not db.in_transaction:
        return
    with contextlib.suppress(Exception):
        db.execute("ROLLBACK TO schema_migration")
        db.execute("RELEASE schema_migration")


def _upgrade_from_shape(db: Any, shape: str) -> None:
    pending = shape
    while pending != SHAPE_CURRENT:
        next_shape, step = UPGRADE_STEPS[pending]
        step(db)
        pending = next_shape


def _upgrade_v9_to_v10(db: Any) -> None:
    # Adds the empty canonical activity detail tables; no existing row changes.
    execute_ddl(db, ACTIVITY_DETAIL_DDL)


def _upgrade_v10_to_v11(db: Any) -> None:
    # Adds the empty local food database mirror; no existing row changes.
    execute_ddl(db, FOOD_DATABASE_DDL)


def _upgrade_v11_to_v12(db: Any) -> None:
    # Adds the day column of raw provider records, then moves the Garmin snapshot
    # blob into one raw record per payload element (see garmin_items_migration).
    db.execute("ALTER TABLE provider_records ADD COLUMN observed_on TEXT")
    db.execute(
        "CREATE INDEX idx_provider_records_observed "
        "ON provider_records(provider, record_kind, observed_on)"
    )
    split_garmin_snapshot(db)


def _upgrade_v12_to_v13(db: Any) -> None:
    # Adds the maximum speed of a lap; existing laps keep NULL until refetched.
    # The v9 step creates the detail tables from the current DDL, which already
    # has the column, so it is only added to tables written by v10 or later.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(activity_laps)")}
    if "max_speed_mps" not in columns:
        db.execute("ALTER TABLE activity_laps ADD COLUMN max_speed_mps REAL")


def _rebuild_table_allowing_yazio(db: Any, table: str, ddl: str) -> None:
    """Recreate a table from its current DDL when its constraints predate Yazio.

    SQLite cannot change a CHECK, so the rows move through a renamed copy. Older
    steps that create the table from the current DDL already have the new
    constraint and are left alone.
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None or "yazio" in row["sql"]:
        return
    statements = [statement for statement in ddl.split(";") if statement.strip()]
    columns = ", ".join(
        column["name"] for column in db.execute(f"PRAGMA table_info({table})")
    )
    indexes = [
        index["name"]
        for index in db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
            (table,),
        )
    ]
    db.execute(f"ALTER TABLE {table} RENAME TO {table}_v13")
    for index in indexes:
        db.execute(f"DROP INDEX {index}")
    db.execute(statements[0])
    db.execute(f"INSERT INTO {table}({columns}) SELECT {columns} FROM {table}_v13")
    db.execute(f"DROP TABLE {table}_v13")
    for statement in statements[1:]:
        db.execute(statement)


def _upgrade_v13_to_v14(db: Any) -> None:
    # Allows Yazio foods in the mirror and saved products; rows are unchanged.
    _rebuild_table_allowing_yazio(db, "food_database_entries", FOOD_DATABASE_DDL)
    _rebuild_table_allowing_yazio(db, "nutrition_products", NUTRITION_PRODUCTS_DDL)


# Feedback written before schema version 15 is keyed by a provider activity id
# and names its provider only when the client posted a local id.
_FEEDBACK_RECORD_MATCH: Final = (
    "record.provider_activity_id = activity_feedback.activity_id "
    "AND (activity_feedback.provider IS NULL "
    "OR record.provider = activity_feedback.provider) "
    "AND record.activity_id IS NOT NULL"
)


def _upgrade_v14_to_v15(db: Any) -> None:
    # Adds the canonical model extensions, then links feedback to the session it
    # was written for: a local session id links to itself, a provider id only
    # when exactly one provider record matches. Ambiguous and unmatched feedback
    # keeps session_id NULL; ids, contents, timestamps and row count stay as is.
    execute_ddl(db, CANONICAL_EXTENSIONS_DDL)
    db.execute(
        "UPDATE activity_feedback SET session_id = activity_id WHERE EXISTS "
        "(SELECT 1 FROM activity_sessions AS session "
        "WHERE session.activity_id = activity_feedback.activity_id)"
    )
    db.execute(
        "UPDATE activity_feedback SET session_id = (SELECT record.activity_id "
        f"FROM activity_records AS record WHERE {_FEEDBACK_RECORD_MATCH}) "
        "WHERE session_id IS NULL AND (SELECT COUNT(*) FROM activity_records AS record "
        f"WHERE {_FEEDBACK_RECORD_MATCH}) = 1 AND EXISTS (SELECT 1 "
        "FROM activity_records AS record JOIN activity_sessions AS session "
        f"ON session.activity_id = record.activity_id WHERE {_FEEDBACK_RECORD_MATCH})"
    )


def _upgrade_v15_to_v16(db: Any) -> None:
    # Names the start and duration of local planning records provider-neutrally
    # (see planning_fields_migration); ids, values and row counts stay as is.
    rename_planning_fields_in_database(db)


def _upgrade_v16_to_v17(db: Any) -> None:
    # Adds the canonical power curve table, then keeps the stored curve as a raw
    # record the backfill projects (see power_curve_migration); no row changes.
    execute_ddl(db, POWER_CURVE_DDL)
    copy_power_curve_to_raw_record(db)


UPGRADE_STEPS: Final[Mapping[str, tuple[str, Callable[[Any], None]]]] = {
    SHAPE_SCHEMA_V9: (SHAPE_SCHEMA_V10, _upgrade_v9_to_v10),
    SHAPE_SCHEMA_V10: (SHAPE_SCHEMA_V11, _upgrade_v10_to_v11),
    SHAPE_SCHEMA_V11: (SHAPE_SCHEMA_V12, _upgrade_v11_to_v12),
    SHAPE_SCHEMA_V12: (SHAPE_SCHEMA_V13, _upgrade_v12_to_v13),
    SHAPE_SCHEMA_V13: (SHAPE_SCHEMA_V14, _upgrade_v13_to_v14),
    SHAPE_SCHEMA_V14: (SHAPE_SCHEMA_V15, _upgrade_v14_to_v15),
    SHAPE_SCHEMA_V15: (SHAPE_SCHEMA_V16, _upgrade_v15_to_v16),
    SHAPE_SCHEMA_V16: (SHAPE_CURRENT, _upgrade_v16_to_v17),
}
