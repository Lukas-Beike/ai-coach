"""Schema version 20: favorite products, upgraded in place from every release.

A populated release adds ``nutrition_products.favorite`` as 0, so no product
becomes a favorite on its own and every other value stays as it was. A failure
rolls back to the unchanged release and a restart changes nothing. Temporary
databases and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.schema import CURRENT_SCHEMA_VERSION, database_schema_is_current
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V18

FIXTURES = Path(__file__).with_name("fixtures")
STAMP = "2026-11-04T08:00:00+00:00"
PRODUCT = (
    "INSERT INTO nutrition_products(id, name, basis_amount, basis_unit, kcal, "
    "source, created_at, updated_at) VALUES (?, ?, 100, 'g', 250, 'manual', ?, ?)"
)
COLUMNS = (
    "id, name, basis_amount, basis_unit, kcal, source, status, created_at, updated_at"
)


class ProductFavoriteMigrationTests(unittest.TestCase):
    def database(self, version: int) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        db.executescript(
            (FIXTURES / f"schema_v{version}.sql.txt").read_text(encoding="utf-8")
        )
        db.execute(PRODUCT, ("p1", "Skyr", STAMP, STAMP))
        db.execute(PRODUCT, ("p2", "Haferflocken", STAMP, STAMP))
        db.commit()
        return db

    def products(self, db: sqlite3.Connection) -> list[tuple]:
        return [
            tuple(row)
            for row in db.execute(
                f"SELECT {COLUMNS} FROM nutrition_products ORDER BY id"
            )
        ]

    def test_every_supported_release_upgrades_without_favorites(self) -> None:
        for version in (16, 17, 18, 19):
            with self.subTest(version=version):
                db = self.database(version)
                before = self.products(db)
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(self.products(db), before)
                self.assertEqual(
                    [
                        r[0]
                        for r in db.execute("SELECT favorite FROM nutrition_products")
                    ],
                    [0, 0],
                )
                after = list(db.iterdump())
                migrate_schema(db)
                self.assertEqual(list(db.iterdump()), after)

    def test_favorite_accepts_only_zero_and_one(self) -> None:
        db = self.database(19)
        migrate_schema(db)
        db.execute("UPDATE nutrition_products SET favorite = 1 WHERE id = 'p1'")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE nutrition_products SET favorite = 2 WHERE id = 'p1'")

    def test_failed_upgrade_leaves_the_release_unchanged(self) -> None:
        for version in (18, 19):
            with self.subTest(version=version):
                db = self.database(version)
                before = list(db.iterdump())

                def failing(connection: sqlite3.Connection) -> None:
                    migrations._upgrade_v18_to_v20(connection)
                    raise RuntimeError("injected migration failure")

                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V18: (SHAPE_CURRENT, failing)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)


if __name__ == "__main__":
    unittest.main()
