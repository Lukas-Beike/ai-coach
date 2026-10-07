"""Composition for bounded database backup and validated restore services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.restore import (
    DatabaseRestoreConfig,
    DatabaseRestoreService,
)
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.coach.job_store import CoachJobStore
from backend.coach.turn_failures import CoachTurnFailureService
from backend.db import DatabaseManager
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.queue import SyncJobQueueService


@dataclass(frozen=True)
class BackupStorageDependencies:
    database_manager: Callable[[], DatabaseManager]
    database_path: Callable[[], Path]
    data_dir: Callable[[], Path]
    database_lock: Callable[[], Any]
    maximum_bytes: int
    minimum_free_bytes: int
    time_limit_seconds: int
    logger: Any


@dataclass(frozen=True)
class RestoreValidationDependencies:
    app_password: Callable[[], str]
    sqlcipher_available: Callable[[], bool]
    sqlite_backend: Any
    configure_cipher: Callable[[Any, str], None]
    row_factory: Any
    schema_is_current: Callable[[Any], bool]


@dataclass(frozen=True)
class RestoreLifecycleDependencies:
    maintenance_gate: Callable[[], MaintenanceGate]
    sync_jobs: Callable[[], SyncJobQueueService]
    coach_jobs: Callable[[], CoachJobStore]
    coach_failures: Callable[[], CoachTurnFailureService]
    sync_wake_event: Callable[[], Any]
    coach_wake_event: Any
    redact: Callable[[str], str]


class BackupAssembly:
    """Create backup and restore owners over the shared process resources."""

    @dataclass(frozen=True)
    class Inputs:
        storage: BackupStorageDependencies
        validation: RestoreValidationDependencies
        lifecycle: RestoreLifecycleDependencies

    def __init__(self, *, dependencies: BackupAssembly.Inputs) -> None:
        storage = dependencies.storage
        validation = dependencies.validation
        lifecycle = dependencies.lifecycle
        self._database_manager = storage.database_manager
        self._database_path = storage.database_path
        self._data_dir = storage.data_dir
        self._database_lock = storage.database_lock
        self._maximum_bytes = storage.maximum_bytes
        self._minimum_free_bytes = storage.minimum_free_bytes
        self._time_limit_seconds = storage.time_limit_seconds
        self._logger = storage.logger
        self._app_password = validation.app_password
        self._sqlcipher_available = validation.sqlcipher_available
        self._sqlite_backend = validation.sqlite_backend
        self._configure_cipher = validation.configure_cipher
        self._row_factory = validation.row_factory
        self._schema_is_current = validation.schema_is_current
        self._maintenance_gate = lifecycle.maintenance_gate
        self._sync_jobs = lifecycle.sync_jobs
        self._coach_jobs = lifecycle.coach_jobs
        self._coach_failures = lifecycle.coach_failures
        self._sync_wake_event = lifecycle.sync_wake_event
        self._coach_wake_event = lifecycle.coach_wake_event
        self._redact = lifecycle.redact

    def backup_service(self) -> DatabaseBackupService:
        return DatabaseBackupService(
            self._database_manager(),
            self._database_lock(),
            DatabaseBackupConfig(
                database_path=self._database_path(),
                data_dir=self._data_dir(),
                maximum_bytes=self._maximum_bytes,
                minimum_free_bytes=self._minimum_free_bytes,
                time_limit_seconds=self._time_limit_seconds,
            ),
            self._logger,
        )

    def restore_validation_service(self) -> DatabaseRestoreValidationService:
        return DatabaseRestoreValidationService(
            DatabaseRestoreValidationConfig(
                data_dir=self._data_dir(),
                maximum_bytes=self._maximum_bytes,
                app_password=self._app_password(),
                sqlcipher_available=self._sqlcipher_available(),
                sqlite_backend=self._sqlite_backend,
                configure_cipher=self._configure_cipher,
                row_factory=self._row_factory,
                schema_is_current=self._schema_is_current,
            )
        )

    def restore_service(self) -> DatabaseRestoreService:
        return DatabaseRestoreService(
            self.restore_validation_service(),
            self.backup_service(),
            self._database_manager,
            self._database_lock(),
            self._maintenance_gate(),
            self._sync_jobs(),
            self._coach_jobs(),
            self._coach_failures(),
            self._sync_wake_event(),
            self._coach_wake_event,
            DatabaseRestoreConfig(self._data_dir(), self._database_path()),
            self._redact,
        )
