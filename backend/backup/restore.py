"""Restore a validated database and resume durable work under maintenance."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True)
class RestoreDependencies:
    validation: DatabaseRestoreValidationService
    backup: DatabaseBackupService
    database_manager: Callable[[], DatabaseManager]
    database_lock: Any
    maintenance_gate: MaintenanceGate
    sync_jobs: SyncJobQueueService
    coach_jobs: CoachJobStore
    coach_failures: CoachTurnFailureService
    sync_wake: Any
    coach_wake: Any
    config: DatabaseRestoreConfig
    redact: Callable[[str], str]


class DatabaseRestoreService:
    """Own the complete staged restore, file swap, and worker recovery."""

    def __init__(self, dependencies: RestoreDependencies) -> None:
        self._dependencies = dependencies

    def _replace(self, temporary_path: Path) -> str | None:
        config = self._dependencies.config
        database_path = config.database_path
        previous_backup_name: str | None = None
        with self._dependencies.database_lock:
            self._dependencies.backup.checkpoint()
            with self._dependencies.database_manager().restore_drain():
                backup_path = config.data_dir / (
                    f"{database_path.name}.pre-restore-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-"
                    f"{uuid.uuid4().hex}"
                )
                if database_path.exists():
                    shutil.copy2(database_path, backup_path)
                    previous_backup_name = backup_path.name
                for sidecar in (
                    Path(f"{database_path}-wal"),
                    Path(f"{database_path}-shm"),
                ):
                    try:
                        sidecar.unlink()
                    except FileNotFoundError:
                        pass
                os.replace(temporary_path, database_path)
        return previous_backup_name

    def _resume(self) -> None:
        dependencies = self._dependencies
        dependencies.sync_jobs.resume_interrupted()
        dependencies.coach_jobs.resume_interrupted(dependencies.coach_failures)
        dependencies.sync_wake.set()
        dependencies.coach_wake.set()

    def restore(self, payload: bytes) -> dict[str, Any]:
        with self._dependencies.maintenance_gate.restore():
            temporary_path: Path | None = None
            try:
                temporary_path = self._dependencies.validation.stage(payload)
                self._dependencies.validation.validate(temporary_path)
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
                    f"{self._dependencies.redact(str(exc))[:300]}",
                ) from exc
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink()
                    except FileNotFoundError:
                        pass
