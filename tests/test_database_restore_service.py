"""Disposable-file contracts for the complete database restore owner."""

from __future__ import annotations

import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from backend.backup.restore import DatabaseRestoreConfig, DatabaseRestoreService
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class DatabaseRestoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name)
        self.database_path = self.data_dir / "coach.db"
        self.database_path.write_bytes(b"previous database")
        self.lock = threading.RLock()
        self.gate = MaintenanceGate()
        self.validation = Mock()
        self.backup = Mock()
        self.manager = Mock()
        self.sync_jobs = Mock()
        self.coach_jobs = Mock()
        self.coach_failures = Mock()
        self.sync_wake = Mock()
        self.coach_wake = Mock()
        self.calls: list[str] = []

        def stage(payload: bytes) -> Path:
            self.assertTrue(self.gate.state()["active"])
            self.calls.append("stage")
            staged = self.data_dir / "staged.db"
            staged.write_bytes(payload)
            return staged

        def validate(path: Path) -> None:
            self.assertTrue(self.gate.state()["active"])
            self.assertEqual(path.read_bytes(), b"replacement database")
            self.calls.append("validate")

        @contextmanager
        def drain():
            self.assertTrue(self.lock._is_owned())
            self.assertTrue(self.gate.state()["active"])
            self.calls.append("drain")
            yield

        def manager():
            self.assertTrue(self.lock._is_owned())
            return self.manager

        self.validation.stage.side_effect = stage
        self.validation.validate.side_effect = validate
        self.backup.checkpoint.side_effect = lambda: self.calls.append("checkpoint")
        self.manager.restore_drain.side_effect = drain
        self.sync_jobs.resume_interrupted.side_effect = lambda: self.calls.append("sync-resume")
        self.coach_jobs.resume_interrupted.side_effect = lambda _failures: self.calls.append("coach-resume")
        self.sync_wake.set.side_effect = lambda: self.calls.append("sync-wake")
        self.coach_wake.set.side_effect = lambda: self.calls.append("coach-wake")
        self.service = DatabaseRestoreService(
            self.validation,
            self.backup,
            manager,
            self.lock,
            self.gate,
            self.sync_jobs,
            self.coach_jobs,
            self.coach_failures,
            self.sync_wake,
            self.coach_wake,
            DatabaseRestoreConfig(self.data_dir, self.database_path),
            lambda _message: "redacted",
        )

    def test_restores_after_checkpoint_and_drain_then_resumes_both_job_owners(self) -> None:
        Path(f"{self.database_path}-wal").write_bytes(b"stale wal")
        Path(f"{self.database_path}-shm").write_bytes(b"stale shm")

        result = self.service.restore(b"replacement database")

        self.assertEqual(self.database_path.read_bytes(), b"replacement database")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["restored"])
        self.assertEqual(
            (self.data_dir / result["previous_database_backup"]).read_bytes(),
            b"previous database",
        )
        self.assertFalse(Path(f"{self.database_path}-wal").exists())
        self.assertFalse(Path(f"{self.database_path}-shm").exists())
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.assertEqual(
            self.calls,
            ["stage", "validate", "checkpoint", "drain", "sync-resume", "coach-resume", "sync-wake", "coach-wake"],
        )
        self.coach_jobs.resume_interrupted.assert_called_once_with(self.coach_failures)
        self.assertFalse(self.gate.state()["active"])

    def test_invalid_backup_never_changes_live_database_and_cleans_stage(self) -> None:
        self.validation.validate.side_effect = AppError(400, "invalid backup")

        with self.assertRaises(AppError) as raised:
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.database_path.read_bytes(), b"previous database")
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.backup.checkpoint.assert_not_called()
        self.sync_jobs.resume_interrupted.assert_not_called()
        self.assertFalse(self.gate.state()["active"])

    def test_two_restores_keep_distinct_recovery_copies(self) -> None:
        first = self.service.restore(b"replacement database")
        second = self.service.restore(b"replacement database")

        self.assertNotEqual(first["previous_database_backup"], second["previous_database_backup"])
        self.assertEqual(
            (self.data_dir / first["previous_database_backup"]).read_bytes(),
            b"previous database",
        )
        self.assertEqual(
            (self.data_dir / second["previous_database_backup"]).read_bytes(),
            b"replacement database",
        )

    def test_unexpected_validation_error_is_redacted_without_mutation(self) -> None:
        self.validation.validate.side_effect = RuntimeError("sensitive source")

        with self.assertRaises(AppError) as raised:
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 400)
        self.assertIn("redacted", raised.exception.message)
        self.assertNotIn("sensitive source", raised.exception.message)
        self.assertEqual(self.database_path.read_bytes(), b"previous database")
        self.assertFalse((self.data_dir / "staged.db").exists())

    def test_swap_failure_preserves_previous_database_and_releases_gate(self) -> None:
        with (
            patch("backend.backup.restore.os.replace", side_effect=OSError("sensitive path")),
            self.assertRaises(AppError) as raised,
        ):
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.database_path.read_bytes(), b"previous database")
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.sync_jobs.resume_interrupted.assert_not_called()
        self.assertFalse(self.gate.state()["active"])


if __name__ == "__main__":
    unittest.main()
