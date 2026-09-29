"""Create bounded, consistent snapshots for encrypted database backups."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.db.manager import DatabaseManager
from backend.errors import AppError


@dataclass(frozen=True)
class DatabaseBackupConfig:
    database_path: Path
    data_dir: Path
    maximum_bytes: int
    minimum_free_bytes: int
    time_limit_seconds: int
    monotonic: Callable[[], float] = time.monotonic
    disk_usage: Callable[[Path], Any] = shutil.disk_usage


class DatabaseBackupService:
    """Create one consistent snapshot and release it after HTTP streaming."""

    def __init__(
        self,
        manager: DatabaseManager,
        database_lock: AbstractContextManager[Any],
        config: DatabaseBackupConfig,
        logger: logging.Logger,
    ) -> None:
        self._manager = manager
        self._database_lock = database_lock
        self._config = config
        self._logger = logger

    def checkpoint(self) -> None:
        """Checkpoint before restore swaps the active database file."""
        with self._database_lock:
            with self._manager.unit_of_work() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _snapshot(self, deadline: float) -> Path:
        if not self._config.database_path.is_file():
            raise AppError(503, "Der Backup-Speicher ist nicht verfügbar.")
        try:
            with self._manager.reader() as source:
                page_count = int(source.execute("PRAGMA page_count").fetchone()[0])
                page_size = int(source.execute("PRAGMA page_size").fetchone()[0])
                expected_size = page_count * page_size
                if expected_size > self._config.maximum_bytes:
                    raise AppError(413, "Das Datenbank-Backup überschreitet das Größenlimit.")
                free_bytes = self._config.disk_usage(self._config.data_dir).free
                if free_bytes < expected_size + self._config.minimum_free_bytes:
                    raise AppError(507, "Für den Backup-Download ist nicht ausreichend freier Speicher verfügbar.")

                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".database-backup-", suffix=".tmp", dir=self._config.data_dir
                )
                os.close(descriptor)
                snapshot = Path(temporary_name)
                target = self._manager.backend.connect(
                    snapshot, timeout=self._manager.timeout, check_same_thread=False
                )
                try:
                    if self._manager.password and self._manager.configure:
                        self._manager.configure(target, self._manager.password)
                    target.execute("PRAGMA foreign_keys = ON")

                    def check_deadline(_status: int, _remaining: int, _total: int) -> None:
                        if self._config.monotonic() > deadline:
                            raise TimeoutError("database backup time limit reached")

                    source.backup(target, pages=128, progress=check_deadline, sleep=0.01)
                    check = target.execute("PRAGMA integrity_check").fetchone()
                    if not check or str(check[0]).lower() != "ok":
                        raise RuntimeError("database backup integrity check failed")
                finally:
                    target.close()

            size = snapshot.stat().st_size
            if size > self._config.maximum_bytes:
                raise AppError(413, "Das Datenbank-Backup überschreitet das Größenlimit.")
            if self._config.disk_usage(self._config.data_dir).free < self._config.minimum_free_bytes:
                raise AppError(507, "Für den Backup-Download ist nicht ausreichend freier Speicher verfügbar.")
            return snapshot
        except AppError:
            if "snapshot" in locals():
                snapshot.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if "snapshot" in locals():
                snapshot.unlink(missing_ok=True)
            self._logger.warning(
                "Database backup snapshot could not be created",
                extra={"event": "database_backup_snapshot_failed", "error_class": type(exc).__name__},
            )
            raise AppError(503, "Die Datenbank konnte nicht konsistent als Backup vorbereitet werden.") from exc

    def read_bytes(self) -> bytes:
        with self.stream_file() as (path, _deadline):
            try:
                return path.read_bytes()
            except OSError as exc:
                raise AppError(500, "Die Datenbank konnte nicht als Backup gelesen werden.") from exc

    @contextmanager
    def stream_file(self) -> Iterator[tuple[Path, float]]:
        started = self._config.monotonic()
        deadline = started + self._config.time_limit_seconds
        snapshot = self._snapshot(deadline)
        try:
            yield snapshot, deadline
        finally:
            snapshot.unlink(missing_ok=True)
