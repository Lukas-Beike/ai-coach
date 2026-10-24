"""Startup removal of orphaned export, restore and backup staging files."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.backup.staging_sweep import remove_orphaned_staging_files


class OrphanedStagingSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        self.logger = Mock()

    def write(self, name: str) -> Path:
        path = self.data_dir / name
        path.write_bytes(b"synthetic")
        return path

    def test_removes_only_orphans_directly_in_the_data_directory(self) -> None:
        orphans = [
            self.write(".intervals-coach-export-3d1wg7mx.zip"),
            self.write(f".intervals-coach-restore-{'a' * 32}.db"),
            self.write(".database-backup-k2j4h1xw.tmp"),
            *(
                self.write(f".intervals-coach-restore-{'b' * 32}.db{suffix}")
                for suffix in ("-journal", "-wal", "-shm")
            ),
            *(
                self.write(f".database-backup-k2j4h1xw.tmp{suffix}")
                for suffix in ("-journal", "-wal", "-shm")
            ),
        ]
        kept = [
            self.write("intervals-coach.db"),
            self.write("intervals-coach.db-wal"),
            self.write("intervals-coach.db-shm"),
            self.write("intervals-coach.db.pre-restore-20261023120000-abc"),
            self.write("garmin_tokens"),
            self.write("intervals-coach.log"),
            self.write(".intervals-coach-export-3d1wg7mx.zip.keep"),
        ]
        directory = self.data_dir / ".intervals-coach-export-folder.zip"
        directory.mkdir()
        nested = directory / ".database-backup-nested.tmp"
        nested.write_bytes(b"synthetic")

        remove_orphaned_staging_files(self.data_dir, self.logger)

        self.assertEqual([path for path in orphans if path.exists()], [])
        self.assertEqual([path for path in kept if not path.exists()], [])
        self.assertTrue(directory.is_dir())
        self.assertTrue(nested.exists())
        self.logger.warning.assert_not_called()

    def test_symlinked_match_is_kept_with_its_target(self) -> None:
        target = self.write("intervals-coach.db")
        link = self.data_dir / ".intervals-coach-restore-link.db"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symbolic links are not permitted here")

        remove_orphaned_staging_files(self.data_dir, self.logger)

        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_bytes(), b"synthetic")

    def test_failed_removal_is_logged_without_name_and_the_sweep_continues(
        self,
    ) -> None:
        blocked = self.write(".intervals-coach-export-blocked.zip")
        other = self.write(".database-backup-other0000.tmp")
        real_unlink = os.unlink

        def unlink(path: str | os.PathLike[str]) -> None:
            if Path(path) == blocked:
                raise PermissionError("synthetic sensitive detail")
            real_unlink(path)

        with patch("backend.backup.staging_sweep.os.unlink", side_effect=unlink):
            remove_orphaned_staging_files(self.data_dir, self.logger)

        self.assertTrue(blocked.exists())
        self.assertFalse(other.exists())
        self.logger.warning.assert_called_once()
        extra = self.logger.warning.call_args.kwargs["extra"]
        self.assertEqual(extra["event"], "backup_staging_cleanup_failed")
        self.assertEqual(
            extra["context"],
            {"kind": "privacy_export", "error_class": "PermissionError"},
        )
        self.assertNotIn("blocked", repr(self.logger.warning.call_args))
        self.assertNotIn("sensitive", repr(self.logger.warning.call_args))

    def test_missing_data_directory_is_logged_and_ignored(self) -> None:
        remove_orphaned_staging_files(self.data_dir / "missing", self.logger)

        self.logger.warning.assert_called_once()
        self.assertEqual(
            self.logger.warning.call_args.kwargs["extra"]["context"],
            {"kind": "data_directory", "error_class": "FileNotFoundError"},
        )


if __name__ == "__main__":
    unittest.main()
