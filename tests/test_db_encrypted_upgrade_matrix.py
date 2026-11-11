"""SQLCipher open, upgrade, rollback, restart and backup/restore at the baseline.

The baseline (schema v26, release 2.0.5, the schema production runs) is
populated in an encrypted temporary database. It reaches the live schema with
every original value, the file stays encrypted, a failing upgrade step leaves the
database exactly as it was and a retry succeeds, a restart with the same build
changes nothing, a wrong key reads nothing, and an encrypted backup restores the
same rows. Runs in the container suite; SQLCipher has no Windows wheel.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import test_db_migrations as gate
from support import temp_database

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
)

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None

CIPHER_PHRASE = "synthetic encrypted matrix"
PLAINTEXT_HEADER = b"SQLite format 3\x00"


STAMP = "2026-10-31T08:00:00+00:00"
SESSION = "act_feedback"


def add_rows(db: Any) -> None:
    """A message, a snapshot, rated and linked feedback and planning records."""
    db.execute(
        "INSERT INTO messages(role, content, created_at) VALUES ('user', 'Hallo', ?)",
        (STAMP,),
    )
    db.execute(
        "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
        "VALUES (?, ?, ?, 0)",
        (json.dumps({"synced_at": STAMP}), STAMP, STAMP),
    )
    db.execute(
        "INSERT INTO activity_sessions(activity_id, primary_provider, "
        "primary_provider_activity_id, started_at, created_at, updated_at) "
        "VALUES (?, 'garmin', 'g1', '2026-10-30T07:00:00+00:00', ?, ?)",
        (SESSION, STAMP, STAMP),
    )
    db.executemany(
        "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, "
        "notes, session_rpe, deviation_reason, created_at, updated_at, provider, "
        "session_id, session_rpe_rated_at, purpose) "
        "VALUES (?, ?, '2026-10-30', ?, ?, '', ?, ?, ?, ?, ?, ?)",
        [
            ("g1", "Ride", "fine", 5, STAMP, STAMP, "garmin", SESSION, STAMP, "race"),
            ("w1", "Run", "", 0, STAMP, STAMP, None, None, None, None),
        ],
    )
    db.execute(
        "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "matrix-unit",
            "matrix-unit",
            json.dumps({"planned_load": 42, "planned_intensity": 0.8}),
            "now",
            "now",
        ),
    )
    db.executemany(
        "INSERT INTO workout_library(id, local_id, payload, updated_at) "
        "VALUES (?, ?, ?, 'now')",
        [
            (f"matrix-{i}", f"matrix-{i}", json.dumps({"planned_load": i}))
            for i in range(130)
        ],
    )
    db.commit()


def populated_baseline(db: Any) -> None:
    db.executescript(gate.BASELINE_FIXTURE.read_text(encoding="utf-8"))
    add_rows(db)


def populated_previous_shape(db: Any) -> None:
    gate.previous_shape_database(db)
    add_rows(db)


def snapshot(db: Any) -> dict[str, Any]:
    """Every row of every table, from a connection with positional rows."""
    released = gate.DatabaseSchemaGateTests(
        "test_current_schema_is_accepted_repeatedly_without_changes"
    )
    tables = released.user_tables(db)
    return released.table_rows(db, tables, released.table_columns(db, tables))


def plain_baseline() -> dict[str, Any]:
    """The same populated baseline opened without encryption."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        populated_baseline(db)
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

    def encrypted(
        self, build: Callable[[Any], None], name: str
    ) -> tuple[Path, dict[str, Any]]:
        path = self.root / f"{name}.db"
        db = self.connect(path)
        try:
            build(db)
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

    def test_the_encrypted_baseline_reaches_the_live_schema_like_the_plain_one(
        self,
    ) -> None:
        path, _ = self.encrypted(populated_baseline, "baseline")
        db = self.connect(path)
        try:
            migrate_schema(db)
            db.commit()
            self.assertEqual(snapshot(db), plain_baseline())
            payload = json.loads(
                db.execute(
                    "SELECT payload FROM planned_units WHERE id = 'matrix-unit'"
                ).fetchone()[0]
            )
            self.assertEqual(payload, {"planned_load": 42, "planned_intensity": 0.8})
            library = db.execute(
                "SELECT id, payload FROM workout_library WHERE id LIKE 'matrix-%'"
            ).fetchall()
            self.assertEqual(len(library), 130)
            for unit_id, unit_payload in library:
                self.assertEqual(
                    json.loads(unit_payload),
                    {"planned_load": int(unit_id.removeprefix("matrix-"))},
                )
            self.assertTrue(database_schema_is_current(db))
            self.assertEqual(
                db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
            )
            self.assertEqual(db.execute("PRAGMA cipher_integrity_check").fetchall(), [])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            db.close()
        self.assert_encrypted(path)

    def test_a_failing_upgrade_leaves_the_encrypted_database_unchanged(self) -> None:
        def failing_step(connection: Any) -> None:
            gate.add_index_step(connection)
            raise RuntimeError("injected migration failure")

        path, before = self.encrypted(populated_previous_shape, "previous")
        db = self.connect(path)
        try:
            with (
                gate.registered_previous_shape(db, failing_step),
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
                reopened.execute("PRAGMA user_version").fetchone()[0],
                gate.PREVIOUS_VERSION,
            )
            with gate.registered_previous_shape(reopened):
                migrate_schema(reopened)
            reopened.commit()
            self.assertEqual(snapshot(reopened), before)
            self.assertTrue(database_schema_is_current(reopened))
        finally:
            reopened.close()
        self.assert_encrypted(path)

    def manager(self, path: Path) -> DatabaseManager:
        return temp_database(
            self,
            path=path,
            backend=cipher_backend,
            password=CIPHER_PHRASE,
            configure=configure_cipher,
            row_factory=row_factory,
        )

    def opened_baseline(self) -> Path:
        path, _ = self.encrypted(populated_baseline, "baseline")
        db = self.connect(path)
        try:
            migrate_schema(db)
            db.commit()
        finally:
            db.close()
        return path

    def test_the_baseline_restarts_unchanged_and_needs_its_key(self) -> None:
        path = self.opened_baseline()
        opened = self.rows(path)
        manager = self.manager(path)
        with manager.unit_of_work() as db:
            migrate_schema(db)
            self.assertTrue(database_schema_is_current(db))
        manager.close()
        self.assertEqual(self.rows(path), opened)
        wrong = self.connect(path, "another synthetic phrase")
        try:
            with self.assertRaises(cipher_backend.DatabaseError):
                wrong.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            wrong.close()

    def test_an_encrypted_backup_at_the_baseline_restores_the_same_rows(self) -> None:
        path = self.opened_baseline()
        opened = self.rows(path)
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
                data_dir=self.root / "restore",
                maximum_bytes=50_000_000,
                app_password=CIPHER_PHRASE,
                sqlcipher_available=True,
                sqlite_backend=cipher_backend,
                configure_cipher=configure_cipher,
                row_factory=row_factory,
                schema_is_current=database_schema_is_current,
                startup_invariants=lambda _db: None,
            )
        )
        staged = validation.stage(backup)
        validation.validate(staged)
        self.assertEqual(self.rows(staged), opened)
        self.assert_encrypted(staged)


if __name__ == "__main__":
    unittest.main()
