"""Disposable-file contracts for the complete database restore owner."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.restore import (
    DatabaseRestoreConfig,
    DatabaseRestoreService,
    RestoreDependencies,
)
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
        self.discard_diagnostic_cache = Mock()
        self.canonical_backfill_start = Mock()
        self.calls: list[str] = []

        def stage(payload: bytes | Iterable[bytes]) -> Path:
            # Staging runs before the maintenance gate is taken.
            self.assertFalse(self.gate.state()["active"])
            self.calls.append("stage")
            staged = self.data_dir / "staged.db"
            staged.write_bytes(
                payload if isinstance(payload, bytes) else b"".join(payload)
            )
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
        self.sync_jobs.resume_interrupted.side_effect = lambda: self.calls.append(
            "sync-resume"
        )
        self.coach_jobs.resume_interrupted.side_effect = lambda _failures: (
            self.calls.append("coach-resume")
        )
        self.sync_wake.set.side_effect = lambda: self.calls.append("sync-wake")
        self.coach_wake.set.side_effect = lambda: self.calls.append("coach-wake")
        self.discard_diagnostic_cache.side_effect = lambda: self.calls.append(
            "diagnostics-discard"
        )
        self.canonical_backfill_start.side_effect = lambda: self.calls.append(
            "backfill-start"
        )
        self.service = DatabaseRestoreService(
            RestoreDependencies(
                validation=self.validation,
                backup=self.backup,
                database_manager=manager,
                database_lock=self.lock,
                maintenance_gate=self.gate,
                sync_jobs=self.sync_jobs,
                coach_jobs=self.coach_jobs,
                coach_failures=self.coach_failures,
                sync_wake=self.sync_wake,
                coach_wake=self.coach_wake,
                config=DatabaseRestoreConfig(self.data_dir, self.database_path),
                redact=lambda _message: "redacted",
                discard_diagnostic_cache=self.discard_diagnostic_cache,
                canonical_backfill_start=self.canonical_backfill_start,
            )
        )

    def test_restores_after_checkpoint_and_drain_then_resumes_both_job_owners(
        self,
    ) -> None:
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
            [
                "stage",
                "validate",
                "checkpoint",
                "drain",
                "diagnostics-discard",
                "sync-resume",
                "coach-resume",
                "backfill-start",
                "sync-wake",
                "coach-wake",
            ],
        )
        self.coach_jobs.resume_interrupted.assert_called_once_with(self.coach_failures)
        self.assertFalse(self.gate.state()["active"])

    def test_restore_restarts_the_canonical_backfill_worker_once_after_the_swap(
        self,
    ) -> None:
        # The worker may already have exited (done or failed) before the restore.
        self.service.restore(b"replacement database")

        self.canonical_backfill_start.assert_called_once_with()
        self.discard_diagnostic_cache.assert_called_once_with()

    def test_invalid_backup_neither_restarts_backfill_nor_discards_diagnostics(
        self,
    ) -> None:
        self.validation.validate.side_effect = AppError(400, "invalid backup")

        with self.assertRaises(AppError):
            self.service.restore(b"replacement database")

        self.canonical_backfill_start.assert_not_called()
        self.discard_diagnostic_cache.assert_not_called()

    def test_chunked_upload_restores_like_whole_bytes(self) -> None:
        chunks = iter([b"replacement ", b"database"])

        result = self.service.restore(chunks)

        self.assertEqual(self.database_path.read_bytes(), b"replacement database")
        self.assertTrue(result["restored"])
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.assertEqual(self.calls[:2], ["stage", "validate"])

    def test_staged_upload_is_removed_when_the_maintenance_gate_refuses(self) -> None:
        with (
            patch.object(self.gate, "restore", side_effect=AppError(409, "busy")),
            self.assertRaises(AppError) as raised,
        ):
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 409)
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.assertEqual(self.database_path.read_bytes(), b"previous database")
        self.validation.validate.assert_not_called()

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

        self.assertNotEqual(
            first["previous_database_backup"], second["previous_database_backup"]
        )
        self.assertEqual(
            (self.data_dir / first["previous_database_backup"]).read_bytes(),
            b"previous database",
        )
        self.assertEqual(
            (self.data_dir / second["previous_database_backup"]).read_bytes(),
            b"replacement database",
        )

    def test_restore_continues_when_damaged_database_checkpoint_fails(self) -> None:
        manager = Mock()
        manager.unit_of_work.side_effect = sqlite3.DatabaseError(
            "synthetic damaged database"
        )
        logger = Mock()
        backup = DatabaseBackupService(
            manager,
            self.lock,
            DatabaseBackupConfig(
                database_path=self.database_path,
                data_dir=self.data_dir,
                maximum_bytes=1_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=5,
            ),
            logger,
        )
        self.service._dependencies = replace(self.service._dependencies, backup=backup)

        result = self.service.restore(b"replacement database")

        self.assertTrue(result["restored"])
        self.assertEqual(self.database_path.read_bytes(), b"replacement database")
        logger.warning.assert_called_once()
        self.assertEqual(
            logger.warning.call_args.kwargs["extra"]["event"],
            "database_restore_checkpoint_failed",
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
            patch(
                "backend.backup.restore.os.replace",
                side_effect=OSError("sensitive path"),
            ),
            self.assertRaises(AppError) as raised,
        ):
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.database_path.read_bytes(), b"previous database")
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.sync_jobs.resume_interrupted.assert_not_called()
        self.assertFalse(self.gate.state()["active"])

    def test_resume_failure_after_replace_reports_restored_and_still_wakes_workers(
        self,
    ) -> None:
        self.sync_jobs.resume_interrupted.side_effect = RuntimeError(
            "sensitive resume detail"
        )

        with self.assertRaises(AppError) as raised:
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(raised.exception.reason, "restored_resume_failed")
        self.assertIn("wiederhergestellt", raised.exception.message)
        self.assertIn("App neu", raised.exception.message)
        self.assertNotIn("konnte nicht validiert", raised.exception.message)
        self.assertNotIn("sensitive resume detail", raised.exception.message)
        self.assertEqual(self.database_path.read_bytes(), b"replacement database")
        self.assertFalse((self.data_dir / "staged.db").exists())
        self.coach_jobs.resume_interrupted.assert_not_called()
        self.sync_wake.set.assert_called_once_with()
        self.coach_wake.set.assert_called_once_with()
        self.assertFalse(self.gate.state()["active"])

    def test_coach_resume_failure_after_replace_still_wakes_both_workers(self) -> None:
        self.coach_jobs.resume_interrupted.side_effect = RuntimeError(
            "synthetic coach resume failure"
        )

        with self.assertRaises(AppError) as raised:
            self.service.restore(b"replacement database")

        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(raised.exception.reason, "restored_resume_failed")
        self.assertEqual(self.database_path.read_bytes(), b"replacement database")
        self.sync_wake.set.assert_called_once_with()
        self.coach_wake.set.assert_called_once_with()
        self.assertFalse(self.gate.state()["active"])


if __name__ == "__main__":
    unittest.main()
