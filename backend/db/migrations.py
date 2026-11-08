"""Versioned, transactional upgrades of supported encrypted application schemas.

The oldest supported schema is version 21, written by releases 1.13.41 to
1.13.44. Older databases and backups are rejected unchanged; upgrade them with
release 1.13.44 first. Every released schema from version 21 onward keeps its
frozen fixture in tests/fixtures, its digest in backend.db.schema_history and an
upgrade step here, so each supported release still reaches the current schema.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    FEEDBACK_PURPOSE_DDL,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    OLDEST_SUPPORTED_SCHEMA_VERSION,
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V21,
    SHAPE_SCHEMA_V22,
    released_shape,
)
from backend.db.strength_sets_migration import add_strength_sets

_UNSUPPORTED_SCHEMA_MESSAGE = (
    "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
    "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
)
_OLDER_SCHEMA_MESSAGE = (
    "Die Datenbank stammt aus einem Release vor 1.13.41 (Schema älter als 21) "
    "und wird nicht mehr unterstützt. Bitte zuerst mit Release 1.13.44 öffnen; "
    "der Datenbestand bleibt unverändert."
)


class OlderSchemaError(RuntimeError):
    """The database predates the oldest supported schema; nothing was changed."""


def migrate_schema(db: Any) -> None:
    """Upgrade a supported schema to the current one, or reject it unchanged.

    The stored version and the frozen shape of the database are checked before
    any write. A supported shape is then upgraded step by step inside one
    savepoint. The caller owns the commit. DDL runs statement by statement,
    because executescript() would commit implicitly and break rollback.
    """
    version = db.execute("PRAGMA user_version").fetchone()["user_version"]
    if 0 < version < OLDEST_SUPPORTED_SCHEMA_VERSION:
        raise OlderSchemaError(_OLDER_SCHEMA_MESSAGE)
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


def _upgrade_v21_to_v22(db: Any) -> None:
    # Adds the strength set detail kind; every detail row stays as it was.
    add_strength_sets(db)


def _upgrade_v22_to_v23(db: Any) -> None:
    # Adds the athlete's session purpose marking; every feedback row stays as it
    # was and carries no marking (NULL).
    execute_ddl(db, FEEDBACK_PURPOSE_DDL)


UPGRADE_STEPS: Final[Mapping[str, tuple[str, Callable[[Any], None]]]] = {
    SHAPE_SCHEMA_V21: (SHAPE_SCHEMA_V22, _upgrade_v21_to_v22),
    SHAPE_SCHEMA_V22: (SHAPE_CURRENT, _upgrade_v22_to_v23),
}
