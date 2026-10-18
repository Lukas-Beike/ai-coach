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

from backend.db.schema import (
    ACTIVITY_DETAIL_DDL,
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V9,
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


UPGRADE_STEPS: Final[Mapping[str, tuple[str, Callable[[Any], None]]]] = {
    SHAPE_SCHEMA_V9: (SHAPE_CURRENT, _upgrade_v9_to_v10),
}
