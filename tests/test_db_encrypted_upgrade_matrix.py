"""SQLCipher upgrade, rollback, restart and backup/restore from every released schema.

Each supported released schema (v16 to v18) is populated in an encrypted temporary database
with the rows of the native migration tests. The upgrade keeps every original
value, the file stays encrypted, a failing upgrade leaves the database exactly as
it was, a restart with the same build changes nothing, a wrong key reads nothing,
and an encrypted backup of the upgraded database restores the same rows. Runs in
the container suite; SQLCipher has no Windows wheel.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import test_db_feedback_rating_time_migration as rating_time
import test_db_migrations as gate
import test_db_power_curve_migration as power_curve

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db import migrations, row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
)
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V18

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None

CIPHER_PHRASE = "synthetic encrypted matrix"
PLAINTEXT_HEADER = b"SQLite format 3\x00"


def builders() -> dict[int, Callable[[Any], None]]:
    """The populated released databases of the native migration tests."""
    base = {
        16: power_curve.populated_power_curve_database,
        17: rating_time.populated_feedback_database,
        18: lambda db: rating_time.populated_feedback_database(
            db, gate.FIXTURES / "schema_v18.sql.txt"
        ),
    }

    def populated(db: Any, build: Callable[[Any], Any]) -> None:
        build(db)
        db.execute(
            "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                "matrix-unit",
                "matrix-unit",
                json.dumps({"icu_training_load": 42, "icu_intensity": 0.8}),
                "now",
                "now",
            ),
        )
        db.executemany(
            "INSERT INTO workout_library(id, local_id, payload, updated_at) VALUES (?, ?, ?, 'now')",
            [
                (f"matrix-{i}", f"matrix-{i}", json.dumps({"icu_training_load": i}))
                for i in range(130)
            ],
        )
        db.commit()

    return {version: partial(populated, build=build) for version, build in base.items()}


def snapshot(db: Any) -> dict[str, Any]:
    """Every row of every table, from a connection with positional rows."""
    released = gate.DatabaseSchemaGateTests(
        "test_current_schema_is_accepted_repeatedly_without_changes"
    )
    tables = released.user_tables(db)
    return released.table_rows(db, tables, released.table_columns(db, tables))


def fixed_clock() -> Any:
    """No supported migration depends on the wall clock."""
    from contextlib import nullcontext

    return nullcontext()


def plain_upgrade(version: int) -> dict[str, Any]:
    """The same populated release upgraded without encryption."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        builders()[version](db)
        with fixed_clock():
            migrate_schema(db)
        db.commit()
        return snapshot(db)
    finally:
        db.close()


@unittest.skipIf(cipher_backend is None, "SQLCipher requires the Docker runtime")
class EncryptedUpgradeMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def connect(self, path: Path, password: str = CIPHER_PHRASE) -> Any:
        db = cipher_backend.connect(str(path))
        db.row_factory = cipher_backend.Row
        configure_cipher(db, password)
        return db

    def released(self, version: int) -> tuple[Path, dict[str, Any]]:
        path = self.root / f"v{version}.db"
        db = self.connect(path)
        try:
            builders()[version](db)
            db.commit()
            return path, snapshot(db)
        finally:
            db.close()

    def rows(self, path: Path) -> dict[str, Any]:
        db = self.connect(path)
        try:
            return snapshot(db)
        finally:
            db.close()

    def assert_encrypted(self, path: Path) -> None:
        self.assertNotEqual(path.read_bytes()[:16], PLAINTEXT_HEADER)

    def test_every_released_schema_upgrades_encrypted_like_the_plain_upgrade(
        self,
    ) -> None:
        # The native migration tests prove the plain upgrade keeps every row.
        for version in builders():
            with self.subTest(version=version):
                path, _ = self.released(version)
                db = self.connect(path)
                try:
                    with fixed_clock():
                        migrate_schema(db)
                    db.commit()
                    self.assertEqual(snapshot(db), plain_upgrade(version))
                    payload = json.loads(
                        db.execute(
                            "SELECT payload FROM planned_units WHERE id = 'matrix-unit'"
                        ).fetchone()[0]
                    )
                    self.assertEqual(
                        payload, {"planned_load": 42, "planned_intensity": 0.8}
                    )
                    migrated = db.execute(
                        "SELECT id, payload FROM workout_library WHERE id LIKE 'matrix-%'"
                    ).fetchall()
                    self.assertEqual(len(migrated), 130)
                    for unit_id, unit_payload in migrated:
                        self.assertEqual(
                            json.loads(unit_payload),
                            {"planned_load": int(unit_id.removeprefix("matrix-"))},
                        )
                    self.assertTrue(database_schema_is_current(db))
                    self.assertEqual(
                        db.execute("PRAGMA user_version").fetchone()[0],
                        CURRENT_SCHEMA_VERSION,
                    )
                    self.assertEqual(
                        db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                    )
                    self.assertEqual(
                        db.execute("PRAGMA foreign_key_check").fetchall(), []
                    )
                finally:
                    db.close()
                self.assert_encrypted(path)

    def test_a_failing_upgrade_leaves_every_released_schema_unchanged(self) -> None:
        def failing_last_step(connection: Any) -> None:
            migrations._upgrade_v18_to_v19(connection)
            raise RuntimeError("injected migration failure")

        for version in builders():
            with self.subTest(version=version):
                path, before = self.released(version)
                db = self.connect(path)
                try:
                    with (
                        mock.patch.dict(
                            migrations.UPGRADE_STEPS,
                            {SHAPE_SCHEMA_V18: (SHAPE_CURRENT, failing_last_step)},
                        ),
                        self.assertRaisesRegex(RuntimeError, "injected"),
                    ):
                        migrate_schema(db)
                    db.rollback()
                finally:
                    db.close()
                reopened = self.connect(path)
                try:
                    self.assertEqual(snapshot(reopened), before)
                    self.assertEqual(
                        reopened.execute("PRAGMA user_version").fetchone()[0], version
                    )
                finally:
                    reopened.close()
                self.assert_encrypted(path)

    def manager(self, path: Path) -> DatabaseManager:
        manager = DatabaseManager(
            path,
            cipher_backend,
            password=CIPHER_PHRASE,
            configure=configure_cipher,
            row_factory=row_factory,
        )
        self.addCleanup(manager.close)
        return manager

    def upgraded(self, version: int) -> Path:
        path, _ = self.released(version)
        db = self.connect(path)
        try:
            migrate_schema(db)
            db.commit()
        finally:
            db.close()
        return path

    def test_an_upgraded_database_restarts_unchanged_and_needs_its_key(self) -> None:
        for version in builders():
            with self.subTest(version=version):
                path = self.upgraded(version)
                upgraded = self.rows(path)
                manager = self.manager(path)
                with manager.unit_of_work() as db:
                    migrate_schema(db)
                    self.assertTrue(database_schema_is_current(db))
                manager.close()
                self.assertEqual(self.rows(path), upgraded)
                wrong = self.connect(path, "another synthetic phrase")
                try:
                    with self.assertRaises(cipher_backend.DatabaseError):
                        wrong.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
                finally:
                    wrong.close()

    def test_an_encrypted_backup_of_an_upgrade_restores_the_same_rows(self) -> None:
        for version in builders():
            with self.subTest(version=version):
                path = self.upgraded(version)
                upgraded = self.rows(path)
                manager = self.manager(path)
                backup = DatabaseBackupService(
                    manager,
                    threading.RLock(),
                    DatabaseBackupConfig(
                        database_path=path,
                        data_dir=self.root,
                        maximum_bytes=50_000_000,
                        minimum_free_bytes=0,
                        time_limit_seconds=60,
                        monotonic=lambda: 0.0,
                        disk_usage=lambda _path: SimpleNamespace(free=10**12),
                    ),
                    mock.Mock(),
                ).read_bytes()
                self.assertNotEqual(backup[:16], PLAINTEXT_HEADER)
                validation = DatabaseRestoreValidationService(
                    DatabaseRestoreValidationConfig(
                        data_dir=self.root / f"restore-{version}",
                        maximum_bytes=50_000_000,
                        app_password=CIPHER_PHRASE,
                        sqlcipher_available=True,
                        sqlite_backend=cipher_backend,
                        configure_cipher=configure_cipher,
                        row_factory=row_factory,
                        schema_is_current=database_schema_is_current,
                    )
                )
                staged = validation.stage(backup)
                validation.validate(staged)
                self.assertEqual(self.rows(staged), upgraded)
                self.assert_encrypted(staged)


if __name__ == "__main__":
    unittest.main()
