"""Consistent WAL-aware snapshots for encrypted database backups."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db.manager import DatabaseManager
from backend.errors import AppError


class DatabaseBackupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "athlete.db"
        self.manager = DatabaseManager(self.path, sqlite3, timeout=0.1)
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

    def service(self, config: DatabaseBackupConfig | None = None) -> DatabaseBackupService:
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
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
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

    def test_size_and_free_space_limits_reject_backup(self) -> None:
        cases = (
            (replace(self.config, maximum_bytes=1), 413),
            (replace(self.config, disk_usage=lambda _path: SimpleNamespace(free=0)), 507),
        )
        for config, status in cases:
            with self.subTest(status=status), self.assertRaises(AppError) as raised:
                with self.service(config).stream_file():
                    self.fail("an over-limit backup must not stream")
            self.assertEqual(raised.exception.status, status)
            self.assertFalse(list(self.root.glob(".database-backup-*.tmp")))

    def test_missing_database_does_not_create_an_empty_successful_backup(self) -> None:
        missing = replace(self.config, database_path=self.root / "missing.db")
        with self.assertRaises(AppError) as raised:
            with self.service(missing).stream_file():
                self.fail("a missing database must not stream")
        self.assertEqual(raised.exception.status, 503)


if __name__ == "__main__":
    unittest.main()
