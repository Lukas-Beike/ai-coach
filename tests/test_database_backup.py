"""Consistent WAL-aware snapshots for encrypted database backups."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import sqlcipher3
except ImportError:
    sqlcipher3 = None

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.schema import configure_cipher
from backend.errors import AppError


class DatabaseBackupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "athlete.db"
        self.manager = DatabaseManager(
            self.path, sqlite3, timeout=0.1, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("CREATE TABLE records (value TEXT NOT NULL)")
            db.execute("INSERT INTO records VALUES ('saved in wal')")
        self.assertTrue(Path(f"{self.path}-wal").exists())
        self.lock = Mock()
        self.logger = Mock()
        self.config = DatabaseBackupConfig(
            database_path=self.path,
            data_dir=self.root,
            maximum_bytes=1_000_000,
            minimum_free_bytes=10,
            time_limit_seconds=5,
            monotonic=lambda: 10.0,
            disk_usage=lambda _path: SimpleNamespace(free=2_000_000),
        )

    def service(
        self, config: DatabaseBackupConfig | None = None
    ) -> DatabaseBackupService:
        return DatabaseBackupService(
            self.manager, self.lock, config or self.config, self.logger
        )

    def assert_snapshot_has_wal_data(self, path: Path) -> None:
        snapshot = sqlite3.connect(path)
        try:
            self.assertEqual(
                snapshot.execute("SELECT value FROM records").fetchone()[0],
                "saved in wal",
            )
            self.assertEqual(
                snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )
        finally:
            snapshot.close()

    def test_stream_uses_complete_snapshot_without_holding_database_lock(self) -> None:
        service = self.service()
        with service.stream_file() as (path, deadline):
            self.lock.assert_not_called()
            self.assertEqual(deadline, 15.0)
            self.assert_snapshot_has_wal_data(path)
            self.assertNotEqual(path, self.path)
        self.assertFalse(path.exists())

    def test_read_bytes_contains_wal_changes(self) -> None:
        backup = self.service().read_bytes()
        snapshot = self.root / "bytes-test.db"
        try:
            snapshot.write_bytes(backup)
            self.assert_snapshot_has_wal_data(snapshot)
        finally:
            snapshot.unlink(missing_ok=True)

    def test_checkpoint_failure_is_logged_and_does_not_block_restore(self) -> None:
        manager = Mock()
        database = Mock()
        manager.unit_of_work.return_value = nullcontext(database)
        database.execute.side_effect = sqlite3.DatabaseError(
            "synthetic checkpoint failure"
        )
        service = DatabaseBackupService(
            manager, nullcontext(), self.config, self.logger
        )

        service.checkpoint()

        self.logger.warning.assert_called_once()
        self.assertEqual(
            self.logger.warning.call_args.kwargs["extra"],
            {
                "event": "database_restore_checkpoint_failed",
                "error_class": "DatabaseError",
            },
        )

    def test_failed_snapshot_creation_discards_temporary_file(self) -> None:
        connection_service = self.service()
        copy_service = self.service()
        size_service = self.service(replace(self.config, maximum_bytes=1))
        free_space_service = self.service()
        cases = (
            (
                "target connection",
                connection_service,
                patch.object(
                    connection_service,
                    "_connect_target",
                    side_effect=RuntimeError("synthetic connection failure"),
                ),
            ),
            (
                "snapshot copy",
                copy_service,
                patch.object(
                    copy_service,
                    "_copy_snapshot",
                    side_effect=RuntimeError("synthetic copy failure"),
                ),
            ),
            (
                "post-copy size check",
                size_service,
                patch.object(size_service, "_check_source_capacity"),
            ),
            (
                "post-copy free-space check",
                free_space_service,
                patch.object(
                    free_space_service,
                    "_check_free_space",
                    side_effect=[None, RuntimeError("synthetic free-space failure")],
                ),
            ),
        )

        for name, service, failure in cases:
            with self.subTest(failure=name), failure, self.assertRaises(AppError):
                service._snapshot(deadline=15.0)
            self.assertFalse(list(self.root.glob(".database-backup-*.tmp")))

    @unittest.skipIf(sqlcipher3 is None, "SQLCipher runtime required")
    def test_sqlcipher_snapshot_keeps_encrypted_data_and_mapping_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "encrypted.db"
            password = "synthetic-sqlcipher-backup-test-key"
            manager = DatabaseManager(
                database_path,
                sqlcipher3,
                password=password,
                configure=configure_cipher,
                row_factory=row_factory,
                timeout=0.1,
            )
            try:
                with manager.unit_of_work() as db:
                    db.execute("CREATE TABLE records (value TEXT NOT NULL)")
                    db.execute("INSERT INTO records VALUES ('encrypted snapshot')")
                config = replace(
                    self.config,
                    database_path=database_path,
                    data_dir=root,
                )
                backup = DatabaseBackupService(
                    manager, self.lock, config, self.logger
                ).read_bytes()
                backup_path = root / "encrypted-backup.db"
                backup_path.write_bytes(backup)
                restored = sqlcipher3.connect(backup_path)
                try:
                    configure_cipher(restored, password)
                    self.assertEqual(
                        restored.execute("SELECT value FROM records").fetchone()[0],
                        "encrypted snapshot",
                    )
                finally:
                    restored.close()
            finally:
                manager.close()

    def test_size_and_free_space_limits_reject_backup(self) -> None:
        cases = (
            (replace(self.config, maximum_bytes=1), 413),
            (
                replace(self.config, disk_usage=lambda _path: SimpleNamespace(free=0)),
                507,
            ),
        )
        for config, status in cases:
            with (
                self.subTest(status=status),
                self.assertRaises(AppError) as raised,
                self.service(config).stream_file(),
            ):
                self.fail("an over-limit backup must not stream")
            self.assertEqual(raised.exception.status, status)
            self.assertFalse(list(self.root.glob(".database-backup-*.tmp")))

    def test_missing_database_does_not_create_an_empty_successful_backup(self) -> None:
        missing = replace(self.config, database_path=self.root / "missing.db")
        with self.assertRaises(AppError) as raised, self.service(missing).stream_file():
            self.fail("a missing database must not stream")
        self.assertEqual(raised.exception.status, 503)


if __name__ == "__main__":
    unittest.main()
