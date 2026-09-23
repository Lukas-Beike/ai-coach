from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from unittest.mock import Mock

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.http_api.export_streams import ExportStreamTransport


class TrackedLock:
    def __init__(self) -> None:
        self.held = False

    def __enter__(self) -> Self:
        self.held = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.held = False


class ExportStreamTransportTests(unittest.TestCase):
    def test_database_backup_holds_lock_until_send_finishes_and_passes_service_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "coach.db"
            database_path.write_bytes(b"backup")
            lock = TrackedLock()
            backup = DatabaseBackupService(
                Mock(),
                lock,
                DatabaseBackupConfig(
                    database_path=database_path,
                    data_dir=Path(temporary),
                    maximum_bytes=100,
                    minimum_free_bytes=0,
                    time_limit_seconds=8,
                    monotonic=lambda: 10,
                    disk_usage=lambda _path: SimpleNamespace(free=100),
                ),
                logging.getLogger(__name__),
            )
            backup._checkpoint_locked = Mock()
            privacy_export = Mock()
            transport = ExportStreamTransport(
                backup,
                privacy_export,
                monotonic=lambda: 50,
                time_limit_seconds=20,
            )
            handler = Mock()

            def send_file_stream(*args: object, **kwargs: object) -> None:
                self.assertTrue(lock.held)
                self.assertEqual(args, (database_path, "application/octet-stream", "intervals-coach-database.backup"))
                self.assertEqual(kwargs, {"deadline": 18})

            handler.send_file_stream.side_effect = send_file_stream
            transport.stream_database_backup(handler)

            self.assertFalse(lock.held)
            backup._checkpoint_locked.assert_called_once()

    def test_database_backup_releases_lock_when_send_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "coach.db"
            database_path.write_bytes(b"backup")
            lock = TrackedLock()
            backup = DatabaseBackupService(
                Mock(),
                lock,
                DatabaseBackupConfig(
                    database_path=database_path,
                    data_dir=Path(temporary),
                    maximum_bytes=100,
                    minimum_free_bytes=0,
                    time_limit_seconds=8,
                    monotonic=lambda: 10,
                    disk_usage=lambda _path: SimpleNamespace(free=100),
                ),
                logging.getLogger(__name__),
            )
            backup._checkpoint_locked = Mock()
            transport = ExportStreamTransport(backup, Mock(), monotonic=lambda: 50, time_limit_seconds=20)
            handler = Mock()
            handler.send_file_stream.side_effect = RuntimeError("send failed")

            with self.assertRaisesRegex(RuntimeError, "send failed"):
                transport.stream_database_backup(handler)

            self.assertFalse(lock.held)

    def test_privacy_export_uses_injected_deadline_and_cleans_up_on_send_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "export.zip"
            archive_path.write_bytes(b"archive")
            privacy_export = Mock()
            privacy_export.create_file.return_value = archive_path
            transport = ExportStreamTransport(
                Mock(),
                privacy_export,
                monotonic=lambda: 12.5,
                time_limit_seconds=7,
            )
            handler = Mock()

            def send_file_stream(*args: object, **kwargs: object) -> None:
                self.assertEqual(args, (archive_path, "application/zip", "intervals-coach-export.zip"))
                self.assertEqual(kwargs, {"deadline": 19.5, "cleanup": True})
                try:
                    raise BrokenPipeError("client disconnected")
                finally:
                    if kwargs.get("cleanup"):
                        archive_path.unlink(missing_ok=True)

            handler.send_file_stream.side_effect = send_file_stream
            with self.assertRaisesRegex(BrokenPipeError, "client disconnected"):
                transport.stream_privacy_export(handler)

            privacy_export.create_file.assert_called_once_with()
            self.assertFalse(archive_path.exists())


if __name__ == "__main__":
    unittest.main()
