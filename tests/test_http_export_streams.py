from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from support import temp_database

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.http_api.export_streams import ExportStreamTransport


class ExportStreamTransportTests(unittest.TestCase):
    def backup(self, root: Path) -> DatabaseBackupService:
        database_path = root / "coach.db"
        manager = self.manager = temp_database(
            self, path=database_path, row_factory=None, persist_connections=False
        )
        with manager.unit_of_work() as db:
            db.execute("CREATE TABLE records(value TEXT NOT NULL)")
            db.execute("INSERT INTO records VALUES ('saved')")
        return DatabaseBackupService(
            manager,
            DatabaseBackupConfig(
                database_path=database_path,
                data_dir=root,
                maximum_bytes=100_000,
                minimum_free_bytes=0,
                time_limit_seconds=8,
                monotonic=lambda: 10,
                disk_usage=lambda _path: SimpleNamespace(free=100_000),
            ),
            logging.getLogger(__name__),
        )

    def test_database_backup_releases_the_writer_before_send(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = self.backup(root)
            privacy_export_factory = Mock(
                side_effect=RuntimeError("unused privacy export construction failed")
            )
            transport = ExportStreamTransport(
                lambda: backup,
                privacy_export_factory,
            )
            handler = Mock()

            def send_file_stream(*args: object, **kwargs: object) -> None:
                with self.manager.unit_of_work(timeout=0):
                    pass
                self.assertEqual(args[0].name.startswith(".database-backup-"), True)
                self.assertEqual(
                    args[1:],
                    ("application/octet-stream", "pacecraft-database.backup"),
                )
                self.assertEqual(kwargs, {})
                self.assertTrue(Path(args[0]).exists())

            handler.send_file_stream.side_effect = send_file_stream
            transport.stream_database_backup(handler)

            with self.manager.unit_of_work(timeout=0):
                pass
            self.assertFalse(list(root.glob(".database-backup-*.tmp")))
            privacy_export_factory.assert_not_called()

    def test_database_backup_releases_the_writer_when_send_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = self.backup(root)
            transport = ExportStreamTransport(
                lambda: backup,
                Mock(
                    side_effect=RuntimeError(
                        "unused privacy export construction failed"
                    )
                ),
            )
            handler = Mock()
            handler.send_file_stream.side_effect = RuntimeError("send failed")

            with self.assertRaisesRegex(RuntimeError, "send failed"):
                transport.stream_database_backup(handler)

            with self.manager.unit_of_work(timeout=0):
                pass
            self.assertFalse(list(root.glob(".database-backup-*.tmp")))

    def test_privacy_export_cleans_up_on_send_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "export.zip"
            archive_path.write_bytes(b"archive")
            database_backup_factory = Mock(
                side_effect=RuntimeError("unused backup construction failed")
            )
            privacy_export = Mock()
            privacy_export.create_file.return_value = archive_path
            transport = ExportStreamTransport(
                database_backup_factory,
                lambda: privacy_export,
            )
            handler = Mock()

            def send_file_stream(*args: object, **kwargs: object) -> None:
                self.assertEqual(
                    args,
                    (archive_path, "application/zip", "pacecraft-export.zip"),
                )
                self.assertEqual(kwargs, {"cleanup": True})
                try:
                    raise BrokenPipeError("client disconnected")
                finally:
                    if kwargs.get("cleanup"):
                        archive_path.unlink(missing_ok=True)

            handler.send_file_stream.side_effect = send_file_stream
            with self.assertRaisesRegex(BrokenPipeError, "client disconnected"):
                transport.stream_privacy_export(handler)

            privacy_export.create_file.assert_called_once_with()
            database_backup_factory.assert_not_called()
            self.assertFalse(archive_path.exists())


if __name__ == "__main__":
    unittest.main()
