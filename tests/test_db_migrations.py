"""Upgrade regression tests against the frozen schema of release 1.12.19."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_DATABASE_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
    initialize_schema,
)

RELEASE_SCHEMA = Path(__file__).with_name("fixtures") / "schema_1_12_19.sql.txt"

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None


class DatabaseMigrationTests(unittest.TestCase):
    def connect(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db

    def old_database(self):
        db = self.connect()
        db.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
        return db

    def seed_all_tables(self, db):
        # One synthetic row per durable table, including FK-linked records.
        for table in CURRENT_DATABASE_SCHEMA:
            if table == "nutrition_products":
                continue
            columns = list(db.execute(f"PRAGMA table_info({table})"))
            values = []
            for column in columns:
                name = column["name"]
                value = 1 if column["type"] in ("INTEGER", "REAL") else "synthetic-id"
                if name == "payload":
                    value = '{"date":"2026-10-01"}'
                if name in ("role", "meal_type", "status"):
                    value = {"role": "user", "meal_type": "lunch", "status": "draft"}[
                        name
                    ]
                if name == "status" and table == "sync_jobs":
                    value = "completed"
                if name == "sync_state" and table == "nutrition_sync_dates":
                    value = "pending"
                values.append(value)
            db.execute(
                f"INSERT INTO {table}({','.join(column['name'] for column in columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                values,
            )
        db.commit()

    def rows(self, db):
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
            for table in CURRENT_DATABASE_SCHEMA
            if table != "nutrition_products"
        }

    def test_direct_1_12_19_upgrade_preserves_every_table_and_is_restart_safe(self):
        db = self.old_database()
        db.execute("PRAGMA foreign_keys = ON")
        self.seed_all_tables(db)
        before = self.rows(db)

        migrate_schema(db)
        db.commit()
        migrate_schema(db)
        db.commit()

        self.assertEqual(self.rows(db), before)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_unversioned_1_12_20_preserves_existing_products(self):
        db = self.connect()
        initialize_schema(db)
        db.execute("PRAGMA user_version = 0")
        db.execute(
            "INSERT INTO nutrition_products(id, name, basis_amount, basis_unit, source, created_at, updated_at) VALUES ('synthetic', 'Oats', 100, 'g', 'manual', '2026-10-01', '2026-10-01')"
        )
        db.commit()
        before = list(db.execute("SELECT * FROM nutrition_products").fetchone())

        migrate_schema(db)
        db.commit()

        self.assertEqual(
            list(db.execute("SELECT * FROM nutrition_products").fetchone()), before
        )
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    def test_failure_after_table_creation_rolls_back_and_can_be_retried(self):
        db = self.old_database()
        self.seed_all_tables(db)
        before = self.rows(db)
        with (
            patch(
                "backend.db.migrations.NUTRITION_PRODUCTS_DDL",
                "CREATE TABLE nutrition_products (id TEXT); INVALID SQL;",
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            migrate_schema(db)

        self.assertIsNone(
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
            ).fetchone()
        )
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(self.rows(db), before)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_invalid_migration_result_is_rolled_back(self):
        db = self.old_database()
        with (
            patch(
                "backend.db.migrations.NUTRITION_PRODUCTS_DDL",
                "CREATE TABLE nutrition_products (id TEXT);",
            ),
            self.assertRaisesRegex(RuntimeError, "validiert"),
        ):
            migrate_schema(db)
        self.assertIsNone(
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
            ).fetchone()
        )
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_unknown_or_newer_schema_is_not_modified(self):
        for newer in (False, True):
            with self.subTest(newer=newer):
                db = self.old_database()
                if newer:
                    db.execute("PRAGMA user_version = 99")
                else:
                    db.execute("ALTER TABLE messages ADD COLUMN unknown TEXT")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], 99 if newer else 0
                )

    def test_old_schema_with_changed_column_definition_is_not_migrated(self):
        db = self.old_database()
        db.executescript(
            """
            ALTER TABLE messages RENAME TO messages_original;
            CREATE TABLE messages (
                attachments TEXT NOT NULL DEFAULT '[]',
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT,
                client_turn_id TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO messages(id, role, content, client_turn_id, created_at)
                SELECT id, role, content, client_turn_id, created_at FROM messages_original;
            DROP TABLE messages_original;
            """
        )
        db.commit()
        before = list(db.iterdump())

        with self.assertRaises(RuntimeError):
            migrate_schema(db)

        self.assertEqual(list(db.iterdump()), before)

    def test_unknown_trigger_with_sqlite_like_name_is_rejected(self):
        db = self.old_database()
        db.execute("CREATE TRIGGER sqlitecustom AFTER INSERT ON kv BEGIN SELECT 1; END")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)

    def test_caller_rollback_also_rolls_back_schema_and_version(self):
        with tempfile.TemporaryDirectory() as root:
            manager = DatabaseManager(
                Path(root) / "upgrade.db", sqlite3, row_factory=sqlite3.Row
            )
            self.addCleanup(manager.close)
            with manager.unit_of_work() as db:
                db.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
            with (
                self.assertRaisesRegex(RuntimeError, "startup failure"),
                manager.unit_of_work() as db,
            ):
                migrate_schema(db)
                raise RuntimeError("startup failure")
            with manager.reader() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertIsNone(
                    db.execute(
                        "SELECT name FROM sqlite_master WHERE name='nutrition_products'"
                    ).fetchone()
                )
            manager.close()

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_1_12_19_update_preserves_data_and_reopens_with_same_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted.db"
            options = {
                "password": "synthetic-migration-test-key",
                "configure": configure_cipher,
                "row_factory": cipher_backend.Row,
            }
            manager = DatabaseManager(path, cipher_backend, **options)
            try:
                with manager.unit_of_work() as db:
                    db.executescript(RELEASE_SCHEMA.read_text(encoding="utf-8"))
                    self.seed_all_tables(db)
                    before = self.rows(db)
                with manager.unit_of_work() as db:
                    migrate_schema(db)
            finally:
                manager.close()
            reopened = DatabaseManager(path, cipher_backend, **options)
            try:
                with reopened.unit_of_work() as db:
                    migrate_schema(db)
                    self.assertEqual(self.rows(db), before)
                    self.assertTrue(database_schema_is_current(db))
                    self.assertEqual(
                        db.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                    )
                    self.assertEqual(
                        db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                    )
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
            finally:
                reopened.close()
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")


if __name__ == "__main__":
    unittest.main()
