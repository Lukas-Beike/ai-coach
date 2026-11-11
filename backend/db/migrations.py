"""Versioned, transactional upgrades of supported encrypted application schemas.

The only supported baseline is the schema production runs: version 26, written
by release 2.0.5. Older databases and backups are rejected unchanged; upgrade
them with release 2.0.5 first. The baseline keeps its frozen fixture in
tests/fixtures and its digest in backend.db.schema_history; each later schema
adds one upgrade step here, so the baseline reaches the current schema.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend.db.repositories import (
    FoodDatabaseEntryRepository,
    NutritionProductRepository,
    fill_empty_product_fields,
)
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    NUTRITION_PRODUCTS_DDL,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    OLDEST_SUPPORTED_SCHEMA_VERSION,
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V26,
    released_shape,
)

_LOGGER = logging.getLogger("intervals_coach")

_UNSUPPORTED_SCHEMA_MESSAGE = (
    "Die vorhandene Datenbank entspricht keinem unterstützten Schema. "
    "Der Datenbestand bleibt erhalten; bitte ein kompatibles Release verwenden."
)
_OLDER_SCHEMA_MESSAGE = (
    "Die Datenbank stammt aus einem Release vor 2.0.5 (Schema älter als 26) "
    "und wird nicht mehr unterstützt. Bitte zuerst mit Release 2.0.5 öffnen; "
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


# Own product columns of schema v26, copied unchanged into the canonical table.
_V26_PRODUCT_COLUMNS: Final = (
    "id, barcode, name, brand, basis_amount, basis_unit, kcal, carbs_g, protein_g, "
    "fat_g, sugar_g, fiber_g, salt_g, source, source_url, external_id, provenance, "
    "extraction_confidence, status, created_at, updated_at, favorite"
)


def _canonical_products(db: Any) -> None:
    """Schema v27: own products and mirrored foods in one canonical product table.

    Every own product keeps its row and id as origin 'own'. Every mirrored food
    becomes a product of its database's origin with its fetch time, id and all
    fields. An own product with the EAN of mirrored foods wins: only its empty
    fields are filled, newest food first, and the foods stay stored. This step
    uses the live product DDL and repositories; a later schema that changes
    either freezes this step's copy first.
    """
    db.execute("DROP INDEX idx_nutrition_products_name")
    db.execute("DROP INDEX idx_nutrition_products_status")
    db.execute("ALTER TABLE nutrition_products RENAME TO nutrition_products_v26")
    execute_ddl(db, NUTRITION_PRODUCTS_DDL)
    db.execute(
        f"INSERT INTO nutrition_products({_V26_PRODUCT_COLUMNS}) "
        f"SELECT {_V26_PRODUCT_COLUMNS} FROM nutrition_products_v26"
    )
    db.execute("DROP TABLE nutrition_products_v26")
    entries, products = FoodDatabaseEntryRepository(), NutritionProductRepository()
    moved = 0
    for row in db.execute(
        "SELECT food_id, barcode, payload, fetched_at, updated_at "
        "FROM food_database_entries ORDER BY fetched_at DESC, food_id"
    ).fetchall():
        food = json.loads(row["payload"])
        if row["barcode"]:
            food["barcode"] = row["barcode"]
        if entries.upsert(db, food, row["fetched_at"], row["updated_at"]):
            moved += 1
        else:
            # An own product already holds the food's id: it wins.
            fill_empty_product_fields(db, row["food_id"], food, row["fetched_at"])
    db.execute("DROP TABLE food_database_entries")
    merged = sum(
        products.fill_from_database_entries(db, own["id"], own["barcode"])
        for own in db.execute(
            "SELECT id, barcode FROM nutrition_products "
            "WHERE origin = 'own' AND barcode IS NOT NULL"
        ).fetchall()
    )
    _LOGGER.info(
        "Schema v27: %s database foods moved into the product table; "
        "%s own products filled from foods with their EAN.",
        moved,
        merged,
    )


# Baseline shape -> (next shape, step).
UPGRADE_STEPS: Final[Mapping[str, tuple[str, Callable[[Any], None]]]] = {
    SHAPE_SCHEMA_V26: (SHAPE_CURRENT, _canonical_products),
}
