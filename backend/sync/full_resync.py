"""Own complete provider resynchronization workflows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.sync import observation
from backend.sync.gates import ProviderResyncGate, resync_gate
from backend.sync.observation import OPERATION_CONTEXT, SyncOperationObserver
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import FullResyncHandler

FULL_RESYNC_LABEL = "Vollständiger Resync"
GARMIN_NOT_CONFIGURED_ERROR = "Garmin ist nicht konfiguriert oder nicht verfügbar."

RESYNC_FIELDS = ("running", "status", "last_at", "error")


def resync_field_keys(
    key_map: Mapping[str, tuple[str, ...]],
) -> dict[str, dict[str, str]]:
    """Name each provider's ordered full-resync state keys by their role."""
    for provider_id, keys in key_map.items():
        if len(keys) != len(RESYNC_FIELDS):
            raise ValueError(
                f"{provider_id} full resync needs keys for "
                f"{', '.join(RESYNC_FIELDS)}; got {len(keys)}"
            )
    return {
        provider_id: dict(zip(RESYNC_FIELDS, keys, strict=True))
        for provider_id, keys in key_map.items()
    }


PROVIDER_RESYNC_KEYS: dict[str, dict[str, str]] = resync_field_keys(
    DEFAULT_PROVIDER_REGISTRY.resync_key_map()
)


@dataclass
class FullResyncStateStore:
    """Own durable full-resync state and its bounded database writes."""

    database_manager: DatabaseManager
    key_value_repository: KeyValueRepository
    resync_keys: Mapping[str, Mapping[str, str]]

    def state(
        self, provider: str, gate: ProviderResyncGate, db: Any | None = None
    ) -> dict[str, Any]:
        keys = self.resync_keys[provider]
        if db is None:
            with self.database_manager.reader() as owned:
                return self.state(provider, gate, owned)
        running = (
            gate.is_resetting()
            or self.key_value_repository.get(db, keys["running"]) == "1"
        )
        status = self.key_value_repository.get(db, keys["status"]) if running else None
        last_resync_at = self.key_value_repository.get(db, keys["last_at"])
        last_error = self.key_value_repository.get(db, keys["error"]) or None
        return {
            "running": running,
            "status": status,
            "last_resync_at": last_resync_at,
            "last_error": last_error,
        }

    def start(self, provider: str, label: str) -> None:
        keys = self.resync_keys[provider]
        self.set_value(keys["running"], "1")
        self.set_value(
            keys["status"],
            f"{label}: bestehende Daten bleiben erhalten, Resync läuft…",
        )
        self.set_value(keys["error"], "")
        self.set_value(keys["status"], f"{label}: vollständiger Resync läuft…")

    def complete(self, provider: str, finished_at: str) -> None:
        keys = self.resync_keys[provider]
        self.set_value(keys["last_at"], finished_at)
        self.set_value(keys["error"], "")

    def record_failure(self, provider: str, redacted_error: str) -> None:
        self.set_value(self.resync_keys[provider]["error"], redacted_error)

    def finish(self, provider: str) -> None:
        keys = self.resync_keys[provider]
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
    """Run a provider's full refresh while retaining its last good local data.

    Each provider contributes a ``FullResyncHandler``; providers without one are
    rejected as unknown. Gates default to the registered ones, with the Garmin
    gate as the fallback for an unmapped provider.
    """

    def __init__(
        self,
        handlers: Mapping[str, FullResyncHandler],
        state_store: FullResyncStateStore,
        operation_journal: FullResyncOperationJournal,
        *,
        gates: Mapping[str, ProviderResyncGate] | None = None,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._handlers = handlers
        self._state_store = state_store
        self._operation_journal = operation_journal
        self._gates = gates
        self._registry = registry

    def provider_configured(self, provider: str) -> bool:
        return self._handler(provider).configured()

    def state(self, provider: str, db: Any | None = None) -> dict[str, Any]:
        self._handler(provider)
        return self._state_store.state(provider, self._gate(provider), db)

    def resync(self, provider: str, operation_id: str | None = None) -> dict[str, Any]:
        handler = self._handler(provider)
        if not handler.configured():
            raise handler.not_configured_error()
        gate = self._gate(provider)
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
            operation_token = self._operation_journal.set_context(resolved_operation_id)
            operation_started = self._operation_journal.monotonic()
            self._operation_journal.log_started(
                resolved_operation_id, provider, operation_started
            )
            self._state_store.start(provider, self._registry.get(provider).label)
            result = handler.run(
                resolved_operation_id, self._operation_journal.observer
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

    def _handler(self, provider: str) -> FullResyncHandler:
        if provider not in self._handlers:
            raise AppError(400, "Unbekannte Anbindung.")
        return self._handlers[provider]

    def _gate(self, provider: str) -> ProviderResyncGate:
        return resync_gate(provider, self._gates)
