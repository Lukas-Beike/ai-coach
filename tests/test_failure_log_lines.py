"""Failures of workers, jobs and backups reach the log file and the diagnostics."""

from __future__ import annotations

import io
import json
import logging
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from typing import Self
from unittest.mock import Mock

from support import make_config

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.errors import AppError
from backend.observability import Redactor, configure_logging
from backend.sync.executor import SyncJobExecutor
from backend.sync.worker import SyncJobWorker


class _ConfiguredLogging:
    """Install the application's handlers on the real ``intervals_coach`` logger."""

    def __init__(self, directory: Path) -> None:
        self.logger = logging.getLogger("intervals_coach")
        self.log_path = directory / "logs" / "coach.jsonl"
        self.redactor = Redactor(lambda: make_config())
        self._saved = (
            self.logger.handlers[:],
            self.logger.level,
            self.logger.propagate,
        )

    def __enter__(self) -> Self:
        self.logger.handlers.clear()
        configure_logging(
            self.logger,
            self.log_path.parent,
            self.log_path,
            self.redactor,
            stream=io.StringIO(),
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers[:] = self._saved[0]
        self.logger.setLevel(self._saved[1])
        self.logger.propagate = self._saved[2]

    def file_entries(self) -> list[dict]:
        text = self.log_path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def report_entries(self) -> list[dict]:
        service = RecentLogEntriesService(
            self.log_path, self.redactor, lambda: "fixed-time"
        )
        return service.report_entries()


class FailureLogLineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.logging = _ConfiguredLogging(Path(temporary.name))

    def assert_line(self, event: str, **context: object) -> None:
        for entries in (
            self.logging.file_entries(),
            self.logging.report_entries(),
        ):
            matching = [entry for entry in entries if entry["event"] == event]
            self.assertEqual(len(matching), 1, event)
            self.assertEqual(matching[0]["level"], "ERROR")
            self.assertEqual(
                {key: matching[0]["context"].get(key) for key in context}, context
            )

    def test_worker_iteration_failure_keeps_class_and_reason(self) -> None:
        with self.logging:
            SyncJobWorker._log_iteration_failure(
                AppError(503, "secret detail", reason="provider_down")
            )

            self.assert_line(
                "sync_worker_iteration_failed",
                error_class="AppError",
                reason="provider_down",
            )
            self.assertNotIn("secret detail", self.logging.log_path.read_text("utf-8"))

    def test_executor_hook_failure_keeps_class(self) -> None:
        executor = SyncJobExecutor.__new__(SyncJobExecutor)

        def broken(_job: object) -> None:
            raise RuntimeError("hook failure")

        executor._after_job = broken
        with self.logging:
            executor._run_after_job({"id": "job-1"})

            self.assert_line("sync_job_after_job_failed", error_class="RuntimeError")

    def test_backup_failure_keeps_class(self) -> None:
        manager = Mock()
        manager.unit_of_work.side_effect = OSError("disk detail")
        service = DatabaseBackupService(
            manager,
            nullcontext(),
            DatabaseBackupConfig(
                database_path=Path("unused.db"),
                data_dir=Path("."),
                maximum_bytes=1,
                minimum_free_bytes=1,
                time_limit_seconds=1,
            ),
            self.logging.logger,
        )

        with self.logging:
            service.checkpoint()

            for entries in (
                self.logging.file_entries(),
                self.logging.report_entries(),
            ):
                [entry] = [
                    entry
                    for entry in entries
                    if entry["event"] == "database_restore_checkpoint_failed"
                ]
                self.assertEqual(entry["level"], "WARNING")
                self.assertEqual(entry["context"], {"error_class": "OSError"})


if __name__ == "__main__":
    unittest.main()
