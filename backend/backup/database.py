"""Bounded database backup reads with a lock held through HTTP streaming."""

from __future__ import annotations

import logging
import shutil
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
    """Checkpoint and expose one consistent, size-bounded database file."""

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

    def _checkpoint_locked(self) -> None:
        if not self._config.database_path.exists():
            return
        try:
            with self._manager.unit_of_work() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            # Preserve a recovery path even when the current database is damaged.
            self._logger.warning(
                "Database WAL checkpoint failed",
                extra={"event": "database_wal_checkpoint_failed"},
                exc_info=True,
            )

    def checkpoint(self) -> None:
        with self._database_lock:
            self._checkpoint_locked()

    def read_bytes(self) -> bytes:
        with self._database_lock:
            self._checkpoint_locked()
            try:
                return self._config.database_path.read_bytes()
            except OSError as exc:
                raise AppError(500, "Die Datenbank konnte nicht als Backup gelesen werden.") from exc

    @contextmanager
    def stream_file(self) -> Iterator[tuple[Path, float]]:
        started = self._config.monotonic()
        with self._database_lock:
            self._checkpoint_locked()
            try:
                size = self._config.database_path.stat().st_size
                free_bytes = self._config.disk_usage(self._config.data_dir).free
            except OSError as exc:
                raise AppError(503, "Der Backup-Speicher ist nicht verfügbar.") from exc
            if size > self._config.maximum_bytes:
                raise AppError(413, "Das Datenbank-Backup überschreitet das Größenlimit.")
            if free_bytes < max(self._config.minimum_free_bytes, size):
                raise AppError(507, "Für den Backup-Download ist nicht ausreichend freier Speicher verfügbar.")
            yield self._config.database_path, started + self._config.time_limit_seconds
