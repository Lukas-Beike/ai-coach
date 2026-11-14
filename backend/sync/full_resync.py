"""Own complete provider resynchronization workflows."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.sync import observation
from backend.sync.gates import ProviderResyncGate, resync_gate
from backend.sync.observation import OPERATION_CONTEXT, SyncOperationObserver
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.state import resync_key

FULL_RESYNC_LABEL = "Vollständiger Resync"
PARTIAL_RESYNC_ERROR = "Teilweise geladen. Bitte erneut starten."


@dataclass
class FullResyncStateStore:
    """Own durable full-resync state and its bounded database writes."""

    database_manager: DatabaseManager
    key_value_repository: KeyValueRepository

    def state(
        self, provider: str, gate: ProviderResyncGate, db: Any | None = None
    ) -> dict[str, Any]:
        if db is None:
            with self.database_manager.reader() as owned:
                return self.state(provider, gate, owned)
        running = (
            gate.is_resetting()
            or self.key_value_repository.get(db, resync_key(provider, "running")) == "1"
        )
        status = (
            self.key_value_repository.get(db, resync_key(provider, "status"))
            if running
            else None
        )
        last_resync_at = self.key_value_repository.get(db, resync_key(provider, "at"))
        last_error = (
            self.key_value_repository.get(db, resync_key(provider, "error")) or None
        )
        return {
            "running": running,
            "status": status,
            "last_resync_at": last_resync_at,
            "last_error": last_error,
        }

    def start(self, provider: str, label: str) -> None:
        self.set_value(resync_key(provider, "running"), "1")
        self.set_value(
            resync_key(provider, "status"),
            f"{label}: bestehende Daten bleiben erhalten, Resync läuft…",
        )
        self.set_value(resync_key(provider, "error"), "")
        self.set_value(
            resync_key(provider, "status"), f"{label}: vollständiger Resync läuft…"
        )

    def complete(self, provider: str, finished_at: str) -> None:
        self.set_value(resync_key(provider, "at"), finished_at)
        self.set_value(resync_key(provider, "error"), "")

    def record_failure(self, provider: str, redacted_error: str) -> None:
        self.set_value(resync_key(provider, "error"), redacted_error)

    def finish(self, provider: str) -> None:
        try:
            self.set_value(resync_key(provider, "running"), "0")
        finally:
            self.set_value(resync_key(provider, "status"), "")

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


def _start_thread(provider: str, target: Callable[[], None]) -> None:
    threading.Thread(target=target, name=f"full-resync-{provider}", daemon=True).start()


class FullResyncHandler(Protocol):
    """Runs a provider's full resync for one operation."""

    def configured(self) -> bool:
        """Return whether the provider can run a full resync."""

    def not_configured_error(self) -> AppError:
        """Return the error raised when the provider is not configured."""

    def run(self, operation_id: str, observer: SyncOperationObserver) -> dict[str, Any]:
        """Run the full resync and return its result."""


class FullResyncRuns:
    """Track the background full resyncs of one process.

    A run is claimed before its thread starts, so a repeated request can never
    start a second one, and it counts as running from the request on, also while
    it waits for the provider gate and while the derived passes run. The outcome
    of the latest run per provider is kept in memory for the browser to poll.
    """

    def __init__(
        self, spawn: Callable[[str, Callable[[], None]], None] = _start_thread
    ) -> None:
        self._spawn = spawn
        self._lock = threading.Lock()
        self._active: dict[str, str] = {}
        self._outcomes: dict[str, dict[str, Any]] = {}

    def claim(self, provider: str, operation_id: str) -> bool:
        with self._lock:
            if provider in self._active:
                return False
            self._active[provider] = operation_id
            return True

    def spawn(self, provider: str, target: Callable[[], None]) -> None:
        try:
            self._spawn(provider, target)
        except BaseException:
            with self._lock:
                self._active.pop(provider, None)
            raise

    def active(self, provider: str) -> str | None:
        with self._lock:
            return self._active.get(provider)

    def finish(self, provider: str, outcome: dict[str, Any]) -> None:
        # One step: the outcome is visible no later than the run stops running.
        with self._lock:
            self._outcomes[provider] = outcome
            self._active.pop(provider, None)

    def outcome(self, provider: str) -> dict[str, Any] | None:
        with self._lock:
            outcome = self._outcomes.get(provider)
            return None if outcome is None else dict(outcome)


class FullProviderResyncService:
    """Run a provider's full refresh while retaining its last good local data.

    Each provider contributes a ``FullResyncHandler``; providers without one are
    rejected as unknown. Gates default to the registered ones; a provider with a
    handler but no gate is rejected as unknown too.
    """

    def __init__(
        self,
        handlers: Mapping[str, FullResyncHandler],
        state_store: FullResyncStateStore,
        operation_journal: FullResyncOperationJournal,
        *,
        gates: Mapping[str, ProviderResyncGate] | None = None,
        after_resync: Callable[[Mapping[str, Any]], None] = lambda _job: None,
        runs: FullResyncRuns | None = None,
    ) -> None:
        self._runs = runs if runs is not None else FullResyncRuns()
        self._after_resync = after_resync
        self._handlers = handlers
        self._state_store = state_store
        self._operation_journal = operation_journal
        self._gates = gates

    def state(self, provider: str, db: Any | None = None) -> dict[str, Any]:
        self._handler(provider)
        state = self._state_store.state(provider, self._gate(provider), db)
        if self._runs.active(provider) is not None and not state["running"]:
            # Queued behind the gate or running the derived passes.
            state["running"] = True
            state["status"] = (
                f"{DEFAULT_PROVIDER_REGISTRY.get(provider).label}: vollständiger Resync läuft…"
            )
        return state

    def progress(self, provider: str) -> dict[str, Any]:
        """The state plus the outcome of the latest run of this process."""
        return {**self.state(provider), "outcome": self._runs.outcome(provider)}

    def start(self, provider: str, operation_id: str) -> dict[str, Any]:
        """Start the resync in the background; a second start is refused."""
        handler = self._handler(provider)
        if not handler.configured():
            raise handler.not_configured_error()
        if self._gate(provider).is_resetting() or not self._runs.claim(
            provider, operation_id
        ):
            return {
                "status": "already_running",
                "source": provider,
                "operation_id": self._runs.active(provider),
            }
        self._runs.spawn(
            provider, lambda: self._run_in_background(provider, operation_id)
        )
        return {"status": "started", "source": provider, "operation_id": operation_id}

    def _run_in_background(self, provider: str, operation_id: str) -> None:
        outcome: dict[str, Any] = {"operation_id": operation_id, "status": "failed"}
        try:
            result = self._resync(provider, operation_id)
            outcome["status"] = result["status"]
            try:
                self._request_derived_passes(provider, result)
            except Exception:  # noqa: BLE001 - the records are resynced; log only
                self._operation_journal.record_failure(provider)
        except Exception as exc:  # noqa: BLE001 - the state holds the redacted error
            outcome["reason"] = getattr(exc, "reason", None)
        finally:
            self._runs.finish(provider, outcome)

    def resync(self, provider: str, operation_id: str | None = None) -> dict[str, Any]:
        result = self._resync(provider, operation_id)
        self._request_derived_passes(provider, result)
        return result

    def _request_derived_passes(self, provider: str, result: Mapping[str, Any]) -> None:
        if result.get("status") in {"ok", "partial"}:
            # After the gate is released: the passes read the resynced records.
            self._after_resync({"provider": provider, "type": "refresh"})

    def _resync(self, provider: str, operation_id: str | None) -> dict[str, Any]:
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
            self._state_store.start(
                provider, DEFAULT_PROVIDER_REGISTRY.get(provider).label
            )
            result = handler.run(
                resolved_operation_id, self._operation_journal.observer
            )
            operation_result = result
            operation_succeeded = True
            if result.get("status") == "partial":
                # Only a complete read counts as a resync: no completion time.
                self._state_store.record_failure(provider, PARTIAL_RESYNC_ERROR)
                return {**result, "status": "partial", "source": provider}
            finished_at = self._operation_journal.utc_now()
            self._state_store.complete(provider, finished_at)
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
