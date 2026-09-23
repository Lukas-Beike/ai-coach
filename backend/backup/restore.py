"""Restore a validated database and resume durable work under maintenance."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.backup.database import DatabaseBackupService
from backend.backup.restore_validation import DatabaseRestoreValidationService
from backend.coach.job_store import CoachJobStore
from backend.coach.turn_failures import CoachTurnFailureService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.queue import SyncJobQueueService


@dataclass(frozen=True)
class DatabaseRestoreConfig:
    data_dir: Path
    database_path: Path


class DatabaseRestoreService:
    """Own the complete staged restore, file swap, and worker recovery."""

    def __init__(
        self,
        validation: DatabaseRestoreValidationService,
        backup: DatabaseBackupService,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        maintenance_gate: MaintenanceGate,
        sync_jobs: SyncJobQueueService,
        coach_jobs: CoachJobStore,
        coach_failures: CoachTurnFailureService,
        sync_wake: Any,
        coach_wake: Any,
        config: DatabaseRestoreConfig,
        redact: Callable[[str], str],
    ) -> None:
        self._validation = validation
        self._backup = backup
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._maintenance_gate = maintenance_gate
        self._sync_jobs = sync_jobs
        self._coach_jobs = coach_jobs
        self._coach_failures = coach_failures
        self._sync_wake = sync_wake
        self._coach_wake = coach_wake
        self._config = config
        self._redact = redact

    def _replace(self, temporary_path: Path) -> str | None:
        database_path = self._config.database_path
        previous_backup_name: str | None = None
        with self._database_lock:
            self._backup.checkpoint()
            with self._database_manager().restore_drain():
                backup_path = self._config.data_dir / (
                    f"{database_path.name}.pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-"
                    f"{uuid.uuid4().hex}"
                )
                if database_path.exists():
                    shutil.copy2(database_path, backup_path)
                    previous_backup_name = backup_path.name
                for sidecar in (Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
                    try:
                        sidecar.unlink()
                    except FileNotFoundError:
                        pass
                os.replace(temporary_path, database_path)
        return previous_backup_name

    def _resume(self) -> None:
        self._sync_jobs.resume_interrupted()
        self._coach_jobs.resume_interrupted(self._coach_failures)
        self._sync_wake.set()
        self._coach_wake.set()

    def restore(self, payload: bytes) -> dict[str, Any]:
        with self._maintenance_gate.restore():
            temporary_path: Path | None = None
            try:
                temporary_path = self._validation.stage(payload)
                self._validation.validate(temporary_path)
                previous_backup_name = self._replace(temporary_path)
                temporary_path = None
                self._resume()
                return {
                    "status": "ok",
                    "restored": True,
                    "previous_database_backup": previous_backup_name,
                }
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    400,
                    "Das Datenbank-Backup konnte nicht validiert werden: "
                    f"{self._redact(str(exc))[:300]}",
                ) from exc
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink()
                    except FileNotFoundError:
                        pass
