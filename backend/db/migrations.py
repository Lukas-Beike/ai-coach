"""Versioned, transactional upgrades of supported encrypted application schemas.

The only supported baseline is the schema production runs: version 26, written
by release 2.0.5. Older databases and backups are rejected unchanged; upgrade
them with release 2.0.5 first. The baseline keeps its frozen fixture in
tests/fixtures and its digest in backend.db.schema_history; each later schema
adds one upgrade step here, so the baseline reaches the current schema. A
released later schema (v27) keeps only its digest and enters the chain there.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    OLDEST_SUPPORTED_SCHEMA_VERSION,
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V26,
    SHAPE_SCHEMA_V27,
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


# Frozen copy of the v27 product table (#2364): later schemas add their own step.
_V27_PRODUCTS_DDL: Final = """
    CREATE TABLE nutrition_products (
        id TEXT PRIMARY KEY,
        barcode TEXT,
        name TEXT NOT NULL,
        brand TEXT NOT NULL DEFAULT '',
        basis_amount REAL NOT NULL CHECK (basis_amount > 0),
        basis_unit TEXT CHECK (basis_unit IN ('g', 'ml', 'portion')),
        kcal REAL,
        carbs_g REAL,
        protein_g REAL,
        fat_g REAL,
        sugar_g REAL,
        fiber_g REAL,
        salt_g REAL,
        source TEXT NOT NULL CHECK (source IN ('packaging_label', 'manual', 'open_food_facts', 'yazio', 'bls', 'fddb_export')),
        source_url TEXT NOT NULL DEFAULT '',
        external_id TEXT NOT NULL DEFAULT '',
        provenance TEXT NOT NULL DEFAULT 'manual',
        extraction_confidence REAL,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
        origin TEXT NOT NULL DEFAULT 'own' CHECK (origin GLOB '[a-z]*' AND length(origin) <= 32),
        fetched_at TEXT,
        details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        CHECK (origin <> 'own' OR basis_unit IS NOT NULL)
    );
    CREATE INDEX idx_nutrition_products_name ON nutrition_products(name COLLATE NOCASE);
    CREATE INDEX idx_nutrition_products_status ON nutrition_products(status, updated_at DESC);
    CREATE UNIQUE INDEX idx_nutrition_products_own_barcode ON nutrition_products(barcode) WHERE origin = 'own';
    CREATE INDEX idx_nutrition_products_database ON nutrition_products(barcode, fetched_at DESC) WHERE origin <> 'own'
"""
_V27_NUTRIENTS: Final = (
    "kcal",
    "carbs_g",
    "protein_g",
    "fat_g",
    "sugar_g",
    "fiber_g",
    "salt_g",
)
_V27_ORIGINS: Final = {"off": "open_food_facts", "yazio": "yazio", "bls": "bls"}
_V27_FOOD_COLUMN_FIELDS: Final = frozenset(
    {
        "id",
        "name",
        "brands",
        "basis_amount",
        "basis_unit",
        "per_100",
        "source_url",
        "barcode",
    }
)


def _v27_origin(food_id: str) -> str:
    return _V27_ORIGINS[food_id.split(":", 1)[0]]


def _v27_store_food(
    db: Any, food: dict[str, Any], fetched_at: str, updated_at: str
) -> bool:
    """Store a mirrored food as a product of its database; an own product of its id wins."""
    payload = {key: value for key, value in food.items() if key != "fetched_at"}
    food_id = str(payload["id"])
    origin = _v27_origin(food_id)
    barcode = (
        str(payload.get("barcode") or "")
        if origin == "yazio"
        else food_id.removeprefix("off:")
    ) or None
    per_100 = payload.get("per_100")
    per_100 = per_100 if isinstance(per_100, dict) else {}
    details = {
        key: value
        for key, value in payload.items()
        if key not in _V27_FOOD_COLUMN_FIELDS
    }
    if absent := [key for key in _V27_NUTRIENTS if key not in per_100]:
        details["absent_nutrients"] = absent
    for field in ("brands", "source_url"):
        if field not in payload:
            details.setdefault("absent_fields", []).append(field)
        elif not isinstance(payload[field], str):
            details[field] = payload[field]
    refreshed = {
        "name": payload["name"],
        "brand": str(payload.get("brands") or ""),
        "basis_amount": payload.get("basis_amount") or 100,
        "basis_unit": payload.get("basis_unit"),
        **{key: per_100.get(key) for key in _V27_NUTRIENTS},
        "source_url": str(payload.get("source_url") or ""),
        "details": json.dumps(details, ensure_ascii=False),
        "fetched_at": fetched_at,
        "updated_at": updated_at or fetched_at,
    }
    values = {
        "id": food_id,
        "barcode": barcode,
        **refreshed,
        "source": origin,
        "external_id": food_id,
        "provenance": json.dumps({"kind": origin}),
        "origin": origin,
        "created_at": updated_at or fetched_at,
    }
    return (
        db.execute(
            "INSERT INTO nutrition_products("
            + ", ".join(values)
            + ") VALUES ("
            + ", ".join("?" for _ in values)
            + ") ON CONFLICT(id) DO UPDATE SET "
            "barcode=COALESCE(excluded.barcode, barcode), "
            + ", ".join(f"{column}=excluded.{column}" for column in refreshed)
            + " WHERE nutrition_products.origin <> 'own'",
            tuple(values.values()),
        ).rowcount
        > 0
    )


def _v27_fill_own(
    db: Any, product_id: str, food: Mapping[str, Any], fetched_at: str
) -> bool:
    """Fill an own product's empty brand and nutrients from a food; existing values win."""
    row = db.execute(
        "SELECT brand, basis_amount, basis_unit, details, "
        + ", ".join(_V27_NUTRIENTS)
        + " FROM nutrition_products WHERE id=?",
        (product_id,),
    ).fetchone()
    per_100 = food.get("per_100")
    same_unit = (
        food.get("basis_unit") is not None
        and food.get("basis_unit") == row["basis_unit"]
    )
    values = per_100 if same_unit and isinstance(per_100, dict) else {}
    scale = row["basis_amount"] / (food.get("basis_amount") or 100)
    updates: dict[str, Any] = {
        key: value if scale == 1 else round(value * scale, 3)
        for key in _V27_NUTRIENTS
        if row[key] is None
        and isinstance(value := values.get(key), int | float)
        and not isinstance(value, bool)
    }
    if not row["brand"] and food.get("brands"):
        updates["brand"] = str(food["brands"])
    if not updates:
        return False
    origin = _v27_origin(str(food["id"]))
    passed_on = food.get("filled_fields") or {}
    details = json.loads(row["details"])
    details.setdefault("filled_fields", {}).update(
        {
            key: passed_on.get(key) or {"origin": origin, "fetched_at": fetched_at}
            for key in updates
        }
    )
    db.execute(
        "UPDATE nutrition_products SET "
        + ", ".join(f"{key}=?" for key in updates)
        + ", details=? WHERE id=?",
        (*updates.values(), json.dumps(details, ensure_ascii=False), product_id),
    )
    return True


def _v27_fill_own_from_foods(db: Any, product_id: str, barcode: str) -> bool:
    """Fill an own product from the stored foods of its EAN, newest first."""
    filled = False
    for row in db.execute(
        "SELECT id, brand, basis_amount, basis_unit, details, fetched_at, "
        + ", ".join(_V27_NUTRIENTS)
        + " FROM nutrition_products WHERE origin <> 'own' AND barcode=? "
        "ORDER BY fetched_at DESC LIMIT 5",
        (barcode,),
    ).fetchall():
        food = {
            "id": row["id"],
            "brands": row["brand"],
            "basis_amount": row["basis_amount"],
            "basis_unit": row["basis_unit"],
            "per_100": {key: row[key] for key in _V27_NUTRIENTS},
            "filled_fields": json.loads(row["details"]).get("filled_fields"),
        }
        filled |= _v27_fill_own(db, product_id, food, row["fetched_at"])
    return filled


def _canonical_products(db: Any) -> None:
    """Schema v27: own products and mirrored foods in one canonical product table.

    Every own product keeps its row and id as origin 'own'. Every mirrored food
    becomes a product of its database's origin with its fetch time, id and all
    fields. An own product with the EAN of mirrored foods wins: only its empty
    fields are filled, newest food first, and the foods stay stored. The step
    uses its own frozen copy of the v27 table and row move (#2364), so later
    changes to the live product DDL or repositories never change its result.
    """
    db.execute("DROP INDEX idx_nutrition_products_name")
    db.execute("DROP INDEX idx_nutrition_products_status")
    db.execute("ALTER TABLE nutrition_products RENAME TO nutrition_products_v26")
    execute_ddl(db, _V27_PRODUCTS_DDL)
    db.execute(
        f"INSERT INTO nutrition_products({_V26_PRODUCT_COLUMNS}) "
        f"SELECT {_V26_PRODUCT_COLUMNS} FROM nutrition_products_v26"
    )
    db.execute("DROP TABLE nutrition_products_v26")
    moved = 0
    for row in db.execute(
        "SELECT food_id, barcode, payload, fetched_at, updated_at "
        "FROM food_database_entries ORDER BY fetched_at DESC, food_id"
    ).fetchall():
        food = json.loads(row["payload"])
        if row["barcode"]:
            food["barcode"] = row["barcode"]
        if _v27_store_food(db, food, row["fetched_at"], row["updated_at"]):
            moved += 1
        else:
            # An own product already holds the food's id: it wins.
            _v27_fill_own(db, row["food_id"], food, row["fetched_at"])
    db.execute("DROP TABLE food_database_entries")
    merged = sum(
        _v27_fill_own_from_foods(db, own["id"], own["barcode"])
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


# Frozen copy of the v28 decision table; the live DDL may change later.
_V28_CALENDAR_DECISIONS_DDL: Final = """
    CREATE TABLE external_calendar_decisions (
        uid TEXT NOT NULL CHECK (length(uid) BETWEEN 1 AND 500),
        occurrence_start TEXT NOT NULL DEFAULT '' CHECK (length(occurrence_start) <= 40),
        impact TEXT NOT NULL CHECK (impact IN ('block', 'short', 'easy', 'none')),
        decided_at TEXT NOT NULL,
        PRIMARY KEY (uid, occurrence_start)
    )"""


def _calendar_decisions(db: Any) -> None:
    """Schema v28: an empty table for the athlete's calendar event decisions."""
    execute_ddl(db, _V28_CALENDAR_DECISIONS_DDL)


# Released shape -> (next shape, step).
UPGRADE_STEPS: Final[Mapping[str, tuple[str, Callable[[Any], None]]]] = {
    SHAPE_SCHEMA_V26: (SHAPE_SCHEMA_V27, _canonical_products),
    SHAPE_SCHEMA_V27: (SHAPE_CURRENT, _calendar_decisions),
}
