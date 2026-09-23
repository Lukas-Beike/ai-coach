"""Dependency-light projection and persistence of synchronization status."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from backend.athlete.profile import ProfileService
from backend.config import Config
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.freshness import ProviderFreshnessService
from backend.sync.garmin import GarminSyncStateService
from backend.sync.queue import SyncJobQueueService


class _StateVersionProvider(Protocol):
    def versions(self) -> dict[str, str]: ...


class SyncOperationStateWriter:
    """Persist and publish the bounded state of one provider sync."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        event_buffer: Any,
        redactor: Callable[[str], str],
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._event_buffer = event_buffer
        self._redactor = redactor

    def write(
        self,
        operation_id: str,
        status: str,
        phase: str,
        progress: int,
        message: str,
        error: str | None = None,
    ) -> None:
        persist_sync_operation_state(
            operation_id,
            status,
            phase,
            progress,
            message,
            error,
            set_value=self._set_value,
            redact=self._redactor,
        )
        self._event_buffer.publish(
            "sync",
            {
                "operation_id": str(operation_id)[:80],
                "status": str(status)[:20],
                "phase": str(phase)[:40],
                "progress": max(0, min(int(progress), 100)),
            },
        )

    def _set_value(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)


def persist_sync_operation_state(
    operation_id: str,
    status: str,
    phase: str,
    progress: int,
    message: str,
    error: str | None = None,
    *,
    set_value: Callable[[str, str], None],
    redact: Callable[[str], str],
) -> None:
    """Persist bounded, non-athlete-facing state through an injected store."""
    set_value("sync_operation_id", operation_id)
    set_value("sync_operation_status", status)
    set_value("sync_operation_phase", phase)
    set_value("sync_operation_progress", str(max(0, min(progress, 100))))
    set_value("sync_operation_message", message)
    if error is not None:
        set_value("last_sync_error", redact(error)[:1000])


def project_sync_status(
    *,
    running: bool,
    get_value: Callable[[str], str | None],
    state_versions: Mapping[str, Any],
    provider_freshness: list[dict[str, Any]],
    maintenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the public sync-status DTO from explicitly supplied state."""
    status = get_value("sync_operation_status") or ("running" if running else "idle")
    try:
        progress = max(0, min(int(get_value("sync_operation_progress") or 0), 100))
    except (TypeError, ValueError):
        progress = 0
    return {
        "status": status,
        "phase": get_value("sync_operation_phase")
        or ("running" if running else "idle"),
        "progress": progress,
        "operation_id": get_value("sync_operation_id"),
        "running": running,
        "message": get_value("sync_operation_message") or None,
        "started_at": get_value("sync_operation_started_at"),
        "finished_at": get_value("sync_operation_finished_at"),
        "last_error": get_value("last_sync_error") or None,
        "state_versions": dict(state_versions),
        "provider_freshness": provider_freshness,
        "maintenance": dict(maintenance),
    }


class SyncPublicStateService:
    """Project bounded public sync state from its owning local services."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        provider_freshness_service: ProviderFreshnessService,
        profile_service: ProfileService,
        garmin_sync_state_service: GarminSyncStateService,
        maintenance_gate: MaintenanceGate,
        sync_job_queue_service: SyncJobQueueService,
        state_version_service: _StateVersionProvider,
        intervals_sync_lock: Any,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._provider_freshness_service = provider_freshness_service
        self._profile_service = profile_service
        self._garmin_sync_state_service = garmin_sync_state_service
        self._maintenance_gate = maintenance_gate
        self._sync_job_queue_service = sync_job_queue_service
        self._state_version_service = state_version_service
        self._intervals_sync_lock = intervals_sync_lock

    def _get_value(self, key: str) -> str | None:
        with self._database_manager.reader() as db:
            return self._key_value_repository.get(db, key)

    def state(
        self,
        *,
        freshness: list[dict[str, Any]] | None = None,
        jobs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        running = (
            self._intervals_sync_lock.locked() or self._get_value("sync_running") == "1"
        )
        provider_freshness = freshness
        if provider_freshness is None:
            provider_freshness = self._provider_freshness_service.current(
                profile=self._profile_service.get(),
                garmin_has_core_error=bool(
                    self._garmin_sync_state_service.core_error_entries()
                ),
                garmin_tokenstore_exists=Path(self._config.garmin_tokenstore).exists(),
            )
        result = project_sync_status(
            running=running,
            get_value=self._get_value,
            state_versions=self._state_version_service.versions(),
            provider_freshness=provider_freshness,
            maintenance=self._maintenance_gate.state(),
        )
        result["jobs"] = (
            jobs if jobs is not None else self._sync_job_queue_service.list()
        )
        return result

    def browser_state(
        self,
        *,
        freshness: list[dict[str, Any]] | None = None,
        jobs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return the bounded sync projection consumed by the browser."""
        result = self.state(freshness=freshness, jobs=jobs)
        # Bootstrap already carries these projections at the top level. Keeping
        # them out of the nested sync card preserves its bounded payload size.
        for key in ("state_versions", "provider_freshness", "maintenance"):
            result.pop(key, None)
        result["status"] = self._get_value("sync_status") or result.get("message")
        return result
