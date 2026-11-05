"""Versioned, transactional upgrades of supported encrypted application schemas.

The oldest supported schema is version 16, written by release 1.13.32. Older
databases and backups are rejected unchanged; upgrade them with release 1.13.32
first. Every released schema from version 16 onward keeps its frozen fixture in
tests/fixtures, its digest in backend.db.schema_history and an upgrade step
here, so each supported release still reaches the current schema.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend.db.planning_metrics_migration import rename_planning_metrics
from backend.db.power_curve_migration import copy_power_curve_to_raw_record
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    FEEDBACK_RATING_TIME_DDL,
    OBSERVATION_LIFECYCLE_DDL,
    POWER_CURVE_DDL,
    PRODUCT_FAVORITE_DDL,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V16,
    SHAPE_SCHEMA_V17,
    SHAPE_SCHEMA_V18,
    SHAPE_SCHEMA_V20,
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


def _upgrade_v16_to_v17(db: Any) -> None:
    # Adds the canonical power curve table, then keeps the stored curve as a raw
    # record the backfill projects (see power_curve_migration); no row changes.
    execute_ddl(db, POWER_CURVE_DDL)
    copy_power_curve_to_raw_record(db)


def _upgrade_v17_to_v18(db: Any) -> None:
    # Adds the rating time of the session RPE; existing feedback keeps NULL, so
    # its rating time stays unknown. No row changes.
    execute_ddl(db, FEEDBACK_RATING_TIME_DDL)


def _upgrade_v18_to_v20(db: Any) -> None:
    # Schema v19 changed stored planning metric keys only, so its tables have the
    # shape of v18. A v19 database already holds the renamed records.
    if db.execute("PRAGMA user_version").fetchone()["user_version"] < 19:
        rename_planning_metrics(db)
    # Adds the product favorite flag; every existing product is no favorite.
    execute_ddl(db, PRODUCT_FAVORITE_DDL)


def _upgrade_v20_to_v21(db: Any) -> None:
    # Adds the observation lifecycle: every existing row stays active, and rows
    # whose raw record is known exactly get it as their owner.
    execute_ddl(db, OBSERVATION_LIFECYCLE_DDL)
    _assign_observation_owners(db)


# An owner is the source record id of the stored raw record whose projection
# emits the observation; a sync that maps that record again and no longer emits
# the row retires it. Only exact ownership is assigned here:
#
# - Intervals.icu wellness and Wahoo threshold observations name their raw record
#   as their source record id.
# - Every other Intervals.icu observation comes from the single athlete record.
#   Its source record id is the athlete id, or NULL for an unusable one; a
#   wellness day id (``YYYY-MM-DD``) is never taken for an athlete value.
#
# Garmin observations name a mapper entry, not their raw element, so they keep no
# owner here; the canonical re-projection that follows the upgrade assigns one to
# every row a stored element still emits. A row without an owner is never retired.
# The record kinds are frozen literals, as this step must not change with code.
_EXACT_OWNER_KINDS = (
    ("intervals", "wellness"),
    ("wahoo", "power_zones"),
    ("wahoo", "user"),
)
_ATHLETE_RECORD = ("intervals", "athlete", "athlete")
_DAY_PATTERN = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"


def _assign_observation_owners(db: Any) -> None:
    """Set ``owner_record_id`` where the owning raw record is known exactly."""
    for provider, kind in _EXACT_OWNER_KINDS:
        db.execute(
            "UPDATE observations SET owner_record_id = source_record_id "
            "WHERE provider = ? AND owner_record_id IS NULL AND EXISTS ("
            "SELECT 1 FROM provider_records AS raw WHERE raw.provider = ? "
            "AND raw.record_kind = ? "
            "AND raw.source_record_id = observations.source_record_id)",
            (provider, provider, kind),
        )
    provider, kind, record_id = _ATHLETE_RECORD
    db.execute(
        "UPDATE observations SET owner_record_id = ? "
        "WHERE provider = ? AND owner_record_id IS NULL "
        "AND (source_record_id IS NULL OR source_record_id NOT GLOB ?) "
        "AND EXISTS (SELECT 1 FROM provider_records AS raw WHERE raw.provider = ? "
        "AND raw.record_kind = ? AND raw.source_record_id = ?)",
        (record_id, provider, _DAY_PATTERN, provider, kind, record_id),
    )


UPGRADE_STEPS: Final[Mapping[str, tuple[str, Callable[[Any], None]]]] = {
    SHAPE_SCHEMA_V16: (SHAPE_SCHEMA_V17, _upgrade_v16_to_v17),
    SHAPE_SCHEMA_V17: (SHAPE_SCHEMA_V18, _upgrade_v17_to_v18),
    SHAPE_SCHEMA_V18: (SHAPE_SCHEMA_V20, _upgrade_v18_to_v20),
    SHAPE_SCHEMA_V20: (SHAPE_CURRENT, _upgrade_v20_to_v21),
}
