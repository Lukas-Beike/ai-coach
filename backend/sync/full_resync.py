"""Own complete provider resynchronization workflows."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.sync import observation
from backend.sync.competitions import CompetitionSyncService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.gates import ProviderResyncGate
from backend.sync.intervals import IntervalsSyncService
from backend.sync.observation import OPERATION_CONTEXT, SyncOperationObserver

FULL_RESYNC_LABEL = "Vollständiger Resync"
PROVIDER_INTERVALS_NAME = "Intervals.icu"
GARMIN_NOT_CONFIGURED_ERROR = "Garmin ist nicht konfiguriert oder nicht verfügbar."

PROVIDER_RESYNC_KEYS: dict[str, dict[str, str]] = {
    "intervals": {
        "running": "intervals_full_resync_running",
        "status": "intervals_full_resync_status",
        "last_at": "intervals_full_resync_at",
        "error": "intervals_full_resync_error",
    },
    "garmin": {
        "running": "garmin_full_resync_running",
        "status": "garmin_full_resync_status",
        "last_at": "garmin_full_resync_at",
        "error": "garmin_full_resync_error",
    },
}


@dataclass
class FullResyncProviderExecution:
    """Own the provider-specific admission, gates, and resync execution."""

    config: Config
    intervals_service: IntervalsSyncService
    garmin_service: GarminSyncService
    competition_service: CompetitionSyncService
    intervals_gate: ProviderResyncGate
    garmin_gate: ProviderResyncGate
    all_sync_days: int

    def validate_configuration(self, provider: str) -> None:
        if provider == "intervals" and not self.config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)
        if provider == "garmin" and not self.garmin_service.configured():
            raise AppError(503, GARMIN_NOT_CONFIGURED_ERROR)

    def gate(self, provider: str) -> ProviderResyncGate:
        return self.intervals_gate if provider == "intervals" else self.garmin_gate

    def label(self, provider: str) -> str:
        return PROVIDER_INTERVALS_NAME if provider == "intervals" else "Garmin"

    def run(
        self, provider: str, operation_id: str, observer: SyncOperationObserver
    ) -> dict[str, Any]:
        if provider == "garmin":
            return self.garmin_service.sync(
                days=self.all_sync_days,
                operation_id=operation_id,
                reason=FULL_RESYNC_LABEL,
            )

        result = self.intervals_service.sync(
            FULL_RESYNC_LABEL,
            activity_days=self.all_sync_days,
            operation_id=operation_id,
        )
        with (
            observer.observe(
                "intervals", "competitions", FULL_RESYNC_LABEL, operation_id
            ) as scope,
            self.intervals_gate.operation(),
        ):
            competitions = self.competition_service.sync(
                reason=FULL_RESYNC_LABEL, push_local=False
            )
            scope.result = competitions
        return {**result, "competitions": competitions}


@dataclass
class FullResyncStateStore:
    """Own durable full-resync state and its bounded database writes."""

    database_manager: DatabaseManager
    key_value_repository: KeyValueRepository

    def state(
        self, provider: str, gate: ProviderResyncGate, db: Any | None = None
    ) -> dict[str, Any]:
        keys = PROVIDER_RESYNC_KEYS[provider]
        if db is None:
            with self.database_manager.reader() as owned:
                return self.state(provider, gate, owned)
        running = (
            gate.is_resetting()
            or self.key_value_repository.get(db, keys["running"]) == "1"
        )
        status = (
            self.key_value_repository.get(db, keys["status"]) if running else None
        )
        last_resync_at = self.key_value_repository.get(db, keys["last_at"])
        last_error = self.key_value_repository.get(db, keys["error"]) or None
        return {
            "running": running,
            "status": status,
            "last_resync_at": last_resync_at,
            "last_error": last_error,
        }

    def start(self, provider: str, label: str) -> None:
        keys = PROVIDER_RESYNC_KEYS[provider]
        self.set_value(keys["running"], "1")
        self.set_value(
            keys["status"],
            f"{label}: bestehende Daten bleiben erhalten, Resync läuft…",
        )
        self.set_value(keys["error"], "")
        self.set_value(keys["status"], f"{label}: vollständiger Resync läuft…")

    def complete(self, provider: str, finished_at: str) -> None:
        keys = PROVIDER_RESYNC_KEYS[provider]
        self.set_value(keys["last_at"], finished_at)
        self.set_value(keys["error"], "")

    def record_failure(self, provider: str, redacted_error: str) -> None:
        self.set_value(PROVIDER_RESYNC_KEYS[provider]["error"], redacted_error)

    def finish(self, provider: str) -> None:
        keys = PROVIDER_RESYNC_KEYS[provider]
        try:
            self.set_value(keys["running"], "0")
        finally:
            self.set_value(keys["status"], "")

    def set_value(self, key: str, value: str) -> None:
        with self.database_manager.unit_of_work() as db:
            self.key_value_repository.set(db, key, value)


@dataclass
class FullResyncOperationJournal:
    """Own correlation, redaction, timing, and lifecycle records."""

    observer: SyncOperationObserver
    logger: logging.Logger
    redactor: Callable[[str], str]
    utc_now: Callable[[], str]
    monotonic_clock: Callable[[], float]
    operation_id_factory: Callable[[], str]

    def new_operation_id(self) -> str:
        return self.operation_id_factory()

    def monotonic(self) -> float:
        return self.monotonic_clock()

    def set_context(self, operation_id: str) -> Any:
        return OPERATION_CONTEXT.set(
            {"operation_id": operation_id, "trigger": "full_resync"}
        )

    def log_started(self, operation_id: str, provider: str, started: float) -> None:
        observation.log_operation_event(
            self.logger,
            "operation_started",
            operation_id,
            "full_resync",
            provider,
            "resync",
            started,
            monotonic=self.monotonic_clock,
        )

    def error_code(self, error: Exception) -> str:
        return observation.operation_error_code(error)

    def record_failure(self, provider: str) -> None:
        self.logger.exception(
            "Full provider resynchronization failed",
            extra={
                "event": "provider_full_resync_failed",
                "context": {"provider": provider},
            },
        )

    def redact_error(self, error: Exception) -> str:
        return self.redactor(str(error))[:1000]

    def finish(
        self,
        provider: str,
        operation_id: str,
        started: float,
        succeeded: bool,
        result: Any,
        failure_code: str | None,
    ) -> None:
        if succeeded:
            observation.log_operation_event(
                self.logger,
                "operation_completed",
                operation_id,
                "full_resync",
                provider,
                "resync",
                started,
                count=observation.operation_result_count(result),
                monotonic=self.monotonic_clock,
            )
        else:
            observation.log_operation_event(
                self.logger,
                "operation_failed",
                operation_id,
                "full_resync",
                provider,
                "resync",
                started,
                error_code=failure_code or "internal_error",
                monotonic=self.monotonic_clock,
            )


class FullProviderResyncService:
    """Run a provider's full refresh while retaining its last good local data."""

    def __init__(
        self,
        provider_execution: FullResyncProviderExecution,
        state_store: FullResyncStateStore,
        operation_journal: FullResyncOperationJournal,
    ) -> None:
        self._provider_execution = provider_execution
        self._state_store = state_store
        self._operation_journal = operation_journal

    def state(self, provider: str, db: Any | None = None) -> dict[str, Any]:
        self._validate_provider(provider)
        return self._state_store.state(
            provider, self._provider_execution.gate(provider), db
        )

    def resync(self, provider: str, operation_id: str | None = None) -> dict[str, Any]:
        self._validate_provider(provider)
        self._provider_execution.validate_configuration(provider)
        gate = self._provider_execution.gate(provider)
        if not gate.begin_reset():
            return {"status": "already_running", "source": provider}

        operation_token = None
        operation_started: float | None = None
        resolved_operation_id: str | None = None
        operation_result: Any = None
        operation_succeeded = False
        operation_failure_code: str | None = None
        try:
            resolved_operation_id = (
                operation_id or self._operation_journal.new_operation_id()
            )
            operation_token = self._operation_journal.set_context(
                resolved_operation_id
            )
            operation_started = self._operation_journal.monotonic()
            self._operation_journal.log_started(
                resolved_operation_id, provider, operation_started
            )
            self._state_store.start(
                provider, self._provider_execution.label(provider)
            )
            result = self._provider_execution.run(
                provider, resolved_operation_id, self._operation_journal.observer
            )
            finished_at = self._operation_journal.utc_now()
            self._state_store.complete(provider, finished_at)
            operation_result = result
            operation_succeeded = True
            return {
                "status": "ok",
                "source": provider,
                "resynced_at": finished_at,
                **result,
            }
        except Exception as exc:
            operation_failure_code = self._operation_journal.error_code(exc)
            self._state_store.record_failure(
                provider, self._operation_journal.redact_error(exc)
            )
            self._operation_journal.record_failure(provider)
            raise
        finally:
            try:
                if operation_started is not None:
                    assert resolved_operation_id is not None
                    try:
                        self._state_store.finish(provider)
                    finally:
                        self._operation_journal.finish(
                            provider,
                            resolved_operation_id,
                            operation_started,
                            operation_succeeded,
                            operation_result,
                            operation_failure_code,
                        )
            finally:
                try:
                    if operation_token is not None:
                        OPERATION_CONTEXT.reset(operation_token)
                finally:
                    gate.end_reset()

    def _validate_provider(self, provider: str) -> None:
        if provider not in PROVIDER_RESYNC_KEYS:
            raise AppError(400, "Unbekannte Anbindung.")
