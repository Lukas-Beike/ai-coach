"""Restore validation of released schema v5 backups and of unknown newer backups."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    initialize_schema,
)
from backend.errors import AppError

SCHEMA_V5 = Path(__file__).with_name("fixtures") / "schema_v5.sql.txt"
NOW = "2026-10-01T08:00:00+00:00"


def read_bytes(path):
    return path.read_bytes()


class RestoreSchemaUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def service(self, migrate=migrate_schema):
        return DatabaseRestoreValidationService(
            DatabaseRestoreValidationConfig(
                data_dir=self.root,
                maximum_bytes=10_000_000,
                app_password="",
                sqlcipher_available=False,
                sqlite_backend=sqlite3,
                configure_cipher=lambda _db, _password: None,
                row_factory=sqlite3.Row,
                schema_is_current=database_schema_is_current,
                migrate_schema=migrate,
            )
        )

    def backup_bytes(self, build):
        path = self.root / f"source-{build.__name__}.db"
        db = sqlite3.connect(path)
        try:
            build(db)
            db.commit()
        finally:
            db.close()
        payload = read_bytes(path)
        path.unlink()
        return payload

    def build_v5(self, db):
        db.executescript(SCHEMA_V5.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Synthetic question', ?)",
            (NOW,),
        )
        db.execute(
            "INSERT INTO nutrition_logs(id, meal_date, logged_at, meal_type, "
            "description, kcal, created_at, updated_at, logged_time_known) "
            "VALUES ('meal-1', '2026-09-15', ?, 'lunch', 'Synthetic meal', 500, ?, ?, 0)",
            (NOW, NOW, NOW),
        )

    def build_v6_with_provider_rows(self, db):
        initialize_schema(db)
        db.execute(
            "INSERT INTO provider_records(provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, created_at, updated_at) "
            "VALUES ('synthetic-provider', 'activity', 'synthetic-record', '{}', ?, ?, ?, ?)",
            ("b" * 64, NOW, NOW, NOW),
        )

    def build_newer(self, db):
        self.build_v6_with_provider_rows(db)
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")

    def test_v5_backup_restores_as_v6_with_rows_and_empty_provider_tables(self):
        payload = self.backup_bytes(self.build_v5)
        service = self.service()
        staged = service.stage(payload)

        service.validate(staged)

        db = sqlite3.connect(staged)
        db.row_factory = sqlite3.Row
        try:
            self.assertEqual(
                db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
            )
            self.assertTrue(database_schema_is_current(db))
            self.assertEqual(
                db.execute("SELECT content FROM messages").fetchone()[0],
                "Synthetic question",
            )
            self.assertEqual(
                tuple(
                    db.execute(
                        "SELECT description, logged_time_known FROM nutrition_logs"
                    ).fetchone()
                ),
                ("Synthetic meal", 0),
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0], 0
            )
        finally:
            db.close()
        staged.unlink()

    def test_v6_backup_with_provider_rows_restores_without_changes(self):
        payload = self.backup_bytes(self.build_v6_with_provider_rows)
        service = self.service()
        staged = service.stage(payload)

        service.validate(staged)

        db = sqlite3.connect(staged)
        db.row_factory = sqlite3.Row
        try:
            self.assertEqual(
                db.execute("SELECT source_record_id FROM provider_records").fetchone()[
                    0
                ],
                "synthetic-record",
            )
        finally:
            db.close()
        staged.unlink()

    def test_failed_v5_restore_validation_leaves_the_staged_copy_unchanged(self):
        payload = self.backup_bytes(self.build_v5)

        def failing_migration(db):
            migrate_schema(db)
            raise RuntimeError("injected validation failure")

        service = self.service(migrate=failing_migration)
        staged = service.stage(payload)

        with self.assertRaises(AppError):
            service.validate(staged)

        self.assertEqual(read_bytes(staged), payload)
        db = sqlite3.connect(staged)
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
        finally:
            db.close()
        staged.unlink()

    def test_newer_schema_backup_is_rejected_without_modifying_the_staged_copy(self):
        payload = self.backup_bytes(self.build_newer)
        service = self.service()
        staged = service.stage(payload)

        with self.assertRaises(AppError):
            service.validate(staged)

        self.assertEqual(read_bytes(staged), payload)
        staged.unlink()


if __name__ == "__main__":
    unittest.main()
