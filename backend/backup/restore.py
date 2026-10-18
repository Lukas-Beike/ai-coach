"""Restore a validated database and resume durable work under maintenance."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
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
    diagnostics_suspended: Callable[[], AbstractContextManager[None]]
    canonical_backfill_start: Callable[[], None]
    # Re-derives the runtime configuration from the restored stored credentials.
    refresh_credentials: Callable[[], Any] | None = None


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
        try:
            # Restored jobs must run against the restored provider accounts.
            if dependencies.refresh_credentials is not None:
                dependencies.refresh_credentials()
            dependencies.sync_jobs.resume_interrupted()
            dependencies.coach_jobs.resume_interrupted(dependencies.coach_failures)
            # Restored canonical backfill state may be unfinished; the worker exits
            # once done or failed, so restart it (idempotent while alive).
            dependencies.canonical_backfill_start()
        finally:
            dependencies.sync_wake.set()
            dependencies.coach_wake.set()

    def _invalid_backup(self, exc: Exception) -> AppError:
        return AppError(
            400,
            "Das Datenbank-Backup konnte nicht validiert werden: "
            f"{self._dependencies.redact(str(exc))[:300]}",
        )

    def _stage(self, payload: bytes | Iterable[bytes]) -> Path:
        try:
            return self._dependencies.validation.stage(payload)
        except AppError:
            raise
        except Exception as exc:
            raise self._invalid_backup(exc) from exc

    def _promote(self, temporary_path: Path) -> str | None:
        """Validate the staged file and swap it in; the caller holds the gate."""
        try:
            self._dependencies.validation.validate(temporary_path)
            return self._replace(temporary_path)
        except AppError:
            raise
        except Exception as exc:
            raise self._invalid_backup(exc) from exc

    def restore(self, payload: bytes | Iterable[bytes]) -> dict[str, Any]:
        """Restore from a whole backup or its ordered chunks.

        The payload is staged before the maintenance gate is taken, so a slow
        upload does not hold back ordinary operations. Validation and the file
        swap run under the gate. The staged file is removed on every path.
        """
        temporary_path = self._stage(payload)
        try:
            with self._dependencies.maintenance_gate.restore():
                # Flushes stay blocked from before the swap until the cache is dropped,
                # so the pre-restore diagnostics cannot overwrite the restored ones.
                with self._dependencies.diagnostics_suspended():
                    previous_backup_name = self._promote(temporary_path)
                # The live database is already replaced here; failures must not be
                # reported as validation errors.
                try:
                    self._resume()
                except Exception as exc:
                    raise AppError(
                        500,
                        "Das Datenbank-Backup wurde wiederhergestellt, aber die "
                        "Hintergrundaufgaben konnten nicht fortgesetzt werden. "
                        "Bitte starte die App neu.",
                        reason="restored_resume_failed",
                    ) from exc
        finally:
            temporary_path.unlink(missing_ok=True)
        return {
            "status": "ok",
            "restored": True,
            "previous_database_backup": previous_backup_name,
        }
