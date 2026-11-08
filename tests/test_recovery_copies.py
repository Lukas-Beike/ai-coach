from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.backup.recovery_copies import RecoveryCopies
from backend.sync.intervals_ingest import PURGE_MARKER_FILE
from backend.sync.intervals_purge import BACKUP_LABEL

DATABASE = "athlete.db"
STAMP = "20261101120000-" + "0123456789abcdef" * 2


class RecoveryCopiesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.copies = RecoveryCopies(self.root, DATABASE)

    def touch(self, *names: str) -> None:
        for name in names:
            (self.root / name).write_bytes(b"x")

    def test_it_matches_the_names_the_producers_write(self) -> None:
        produced = (
            f"{DATABASE}.pre-restore-{STAMP}",
            f"{DATABASE}.{BACKUP_LABEL}-{STAMP}",
            PURGE_MARKER_FILE,
        )
        self.touch(*produced)
        self.assertEqual([path.name for path in self.copies.paths()], sorted(produced))

    def test_it_never_touches_the_live_database_or_other_files(self) -> None:
        kept = (
            DATABASE,
            f"{DATABASE}-wal",
            f"{DATABASE}-shm",
            f"{DATABASE}.pre-restore-{STAMP}.tmp",
            f"other.db.pre-restore-{STAMP}",
            ".intervals-coach-export-abc.zip",
            "garmin-tokens.json",
        )
        self.touch(*kept)
        (self.root / f"{DATABASE}.pre-restore-{STAMP[:-1]}x").mkdir()
        self.assertEqual(self.copies.paths(), [])
        self.assertEqual(self.copies.erase().removed, 0)
        for name in kept:
            self.assertTrue((self.root / name).exists())

    def test_erase_counts_removed_and_failed_files(self) -> None:
        self.touch(f"{DATABASE}.pre-restore-{STAMP}", PURGE_MARKER_FILE)
        real_unlink = Path.unlink

        def unlink(path: Path, *args: object, **kwargs: object) -> None:
            if path.name == PURGE_MARKER_FILE:
                raise PermissionError("locked")
            real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

        with patch.object(Path, "unlink", unlink):
            outcome = self.copies.erase()
        self.assertEqual((outcome.removed, outcome.failed), (1, 1))

    def test_a_missing_data_directory_has_no_copies(self) -> None:
        missing = RecoveryCopies(self.root / "missing", DATABASE)
        self.assertEqual(missing.count(), 0)
        self.assertEqual(missing.erase().removed, 0)


if __name__ == "__main__":
    unittest.main()
