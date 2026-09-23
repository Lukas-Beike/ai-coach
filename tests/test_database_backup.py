"""Synthetic boundaries for locked, bounded database backups."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.errors import AppError


class _Lock:
    active = False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, *_exc):
        self.active = False


class _Database:
    def __init__(self, lock):
        self.lock = lock
        self.checkpoints = 0
        self.failure = False

    def execute(self, sql):
        if not self.lock.active or sql != "PRAGMA wal_checkpoint(TRUNCATE)":
            raise AssertionError("checkpoint escaped the backup lock")
        self.checkpoints += 1
        if self.failure:
            raise OSError("synthetic damaged database")


class _Manager:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def unit_of_work(self):
        yield self.database


class DatabaseBackupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.db"
        self.path.write_bytes(b"synthetic-database")
        self.lock = _Lock()
        self.database = _Database(self.lock)
        self.logger = Mock()
        self.config = DatabaseBackupConfig(
            database_path=self.path,
            data_dir=self.path.parent,
            maximum_bytes=100,
            minimum_free_bytes=10,
            time_limit_seconds=5,
            monotonic=lambda: 10.0,
            disk_usage=lambda _path: SimpleNamespace(free=100),
        )

    def service(self, config=None):
        return DatabaseBackupService(
            _Manager(self.database), self.lock, config or self.config, self.logger
        )

    def test_checkpoint_and_lock_cover_the_entire_stream_and_bytes_read(self):
        service = self.service()
        with service.stream_file() as (path, deadline):
            self.assertTrue(self.lock.active)
            self.assertEqual(path.read_bytes(), b"synthetic-database")
            self.assertEqual(deadline, 15.0)
        self.assertFalse(self.lock.active)
        self.assertEqual(service.read_bytes(), b"synthetic-database")
        self.assertEqual(self.database.checkpoints, 2)

    def test_stream_bounds_and_unavailable_storage_keep_the_lock_balanced(self):
        for config, status in (
            (replace(self.config, maximum_bytes=1), 413),
            (replace(self.config, disk_usage=lambda _path: SimpleNamespace(free=0)), 507),
            (replace(self.config, database_path=self.path.parent / "missing.db"), 503),
        ):
            with self.subTest(status=status), self.assertRaises(AppError) as raised, self.service(config).stream_file():
                self.fail("an invalid backup must not stream")
            self.assertEqual(raised.exception.status, status)
            self.assertFalse(self.lock.active)

    def test_failed_checkpoint_still_allows_recovery_backup(self):
        self.database.failure = True
        self.assertEqual(self.service().read_bytes(), b"synthetic-database")
        self.logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
