"""Build the bounded database backup and validated restore services."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.app.context import AppContext
from backend.athlete.profile import DEFAULT_PROFILE
from backend.backup.database import (
    EXPORT_TIME_LIMIT_SECONDS,
    MAX_BACKUP_BYTES,
    MIN_EXPORT_FREE_BYTES,
    DatabaseBackupConfig,
    DatabaseBackupService,
)
from backend.backup.restore import (
    DatabaseRestoreConfig,
    DatabaseRestoreService,
    RestoreDependencies,
)
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.db import row_factory
from backend.db.bootstrap import apply_startup_invariants
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.runtime import clock as runtime_clock
from backend.runtime import maintenance as runtime_maintenance
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync.worker import shared_sync_job_wake_event


@dataclass(frozen=True)
class BackupServices:
    backup_service: Callable[[], DatabaseBackupService]
    restore_validation_service: Callable[[], DatabaseRestoreValidationService]
    restore_service: Callable[[], DatabaseRestoreService]


def build_backup(ctx: AppContext) -> BackupServices:
    """Backup and restore over the live database; each call builds a fresh service."""

    def backup_service() -> DatabaseBackupService:
        return DatabaseBackupService(
            ctx.database(),
            DatabaseBackupConfig(
                database_path=ctx.database_path(),
                data_dir=ctx.data_dir(),
                maximum_bytes=MAX_BACKUP_BYTES,
                minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
                time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
            ),
            ctx.logger,
        )

    def startup_invariants(db: Any) -> None:
        apply_startup_invariants(
            db,
            key_values=ctx.key_values,
            now=runtime_clock.utc_now(),
            default_profile_json=json.dumps(DEFAULT_PROFILE),
            provider_resync_keys=PROVIDER_RESYNC_KEYS.values(),
        )

    def restore_validation_service() -> DatabaseRestoreValidationService:
        return DatabaseRestoreValidationService(
            DatabaseRestoreValidationConfig(
                data_dir=ctx.data_dir(),
                maximum_bytes=MAX_BACKUP_BYTES,
                app_password=ctx.config().app_password,
                sqlcipher_available=ctx.sqlcipher_available(),
                sqlite_backend=ctx.sqlite_backend,
                configure_cipher=configure_cipher,
                row_factory=row_factory,
                schema_is_current=database_schema_is_current,
                startup_invariants=startup_invariants,
            )
        )

    def restore_service() -> DatabaseRestoreService:
        return DatabaseRestoreService(
            RestoreDependencies(
                validation=restore_validation_service(),
                backup=backup_service(),
                database_manager=ctx.database,
                # Read live, like the maintenance decorators.
                maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
                profile_mutation_coordinator=ctx.profile_mutation_coordinator,
                sync_jobs=ctx.sync_job_queue.service(),
                coach_jobs=ctx.coach_background_jobs.job_store(),
                coach_failures=ctx.coach_background_jobs.turn_failure_service(),
                sync_wake=shared_sync_job_wake_event(),
                coach_wake=COACH_JOB_WORKER.wake_event,
                config=DatabaseRestoreConfig(ctx.data_dir(), ctx.database_path()),
                redact=ctx.redactor.redact_text,
                diagnostics_suspended=lambda: ctx.diagnostic_capture.suspended(),
                canonical_backfill_start=lambda: ctx.canonical_backfill.worker.start(),
                logger=ctx.logger,
                refresh_credentials=ctx.refresh_config,
                cancel_coach_turns=lambda: (
                    ctx.coach_conversation.reset_service().cancel_running_turns()
                ),
            )
        )

    return BackupServices(backup_service, restore_validation_service, restore_service)
