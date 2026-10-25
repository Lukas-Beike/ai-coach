"""Schema v14 lets Yazio foods into the food mirror and saved products."""

import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    database_schema_signature,
)
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V13, released_shape

FIXTURES = Path(__file__).with_name("fixtures")
STAMP = "2026-10-25T08:00:00+00:00"
PRODUCT = (
    "INSERT INTO nutrition_products(id, barcode, name, basis_amount, basis_unit, "
    "kcal, source, created_at, updated_at) VALUES (?, ?, ?, 100, 'g', 250, ?, ?, ?)"
)
MIRROR = (
    "INSERT INTO food_database_entries(food_id, barcode, name, brand, payload, "
    "fetched_at, updated_at) VALUES (?, ?, ?, '', '{}', ?, ?)"
)


class YazioSourceMigrationTests(unittest.TestCase):
    def connect(self, version):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        db.executescript(
            (FIXTURES / f"schema_v{version}.sql.txt").read_text(encoding="utf-8")
        )
        db.execute(
            PRODUCT, ("p1", "4000000000001", "Haferflocken", "bls", STAMP, STAMP)
        )
        db.execute(PRODUCT, ("p2", None, "Skyr", "open_food_facts", STAMP, STAMP))
        if version >= 11:
            db.execute(
                MIRROR, ("off:4000000000002", "4000000000002", "Joghurt", STAMP, STAMP)
            )
        db.commit()
        return db

    def rows(self, db, table):
        return [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]

    def test_frozen_v13_fixture_is_the_recorded_released_shape(self):
        db = self.connect(13)
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V13
        )

    def test_v13_rejects_yazio_rows_before_the_upgrade(self):
        db = self.connect(13)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(MIRROR, ("yazio:abc", "", "Skyr", STAMP, STAMP))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(PRODUCT, ("p3", None, "Skyr", "yazio", STAMP, STAMP))

    def test_every_supported_schema_upgrades_keeping_rows_and_accepting_yazio(self):
        for version in (9, 10, 11, 12, 13):
            with self.subTest(version=version):
                db = self.connect(version)
                products = self.rows(db, "nutrition_products")
                mirror = self.rows(db, "food_database_entries") if version >= 11 else []
                migrate_schema(db)
                db.commit()
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertEqual(self.rows(db, "nutrition_products"), products)
                if version >= 11:
                    self.assertEqual(self.rows(db, "food_database_entries"), mirror)
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                db.execute(MIRROR, ("yazio:abc", "", "Skyr", STAMP, STAMP))
                db.execute(PRODUCT, ("p3", None, "Skyr", "yazio", STAMP, STAMP))
                db.commit()

    def test_failed_upgrade_rolls_back_to_the_unchanged_v13_database(self):
        db = self.connect(13)
        before = list(db.iterdump())

        def failing_step(connection):
            migrations._upgrade_v13_to_v14(connection)
            raise RuntimeError("injected migration failure")

        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {SHAPE_SCHEMA_V13: (SHAPE_CURRENT, failing_step)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 13)

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self):
        db = self.connect(13)
        migrate_schema(db)
        db.commit()
        upgraded = list(db.iterdump())
        migrate_schema(db)
        self.assertEqual(list(db.iterdump()), upgraded)


if __name__ == "__main__":
    unittest.main()
