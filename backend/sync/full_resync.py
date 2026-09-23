"""Own complete provider resynchronization workflows."""

from __future__ import annotations

import logging
from collections.abc import Callable
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


class FullProviderResyncService:
    """Run a provider's full refresh while retaining its last good local data."""

    def __init__(
        self,
        config: Config,
        intervals_service: IntervalsSyncService,
        garmin_service: GarminSyncService,
        competition_service: CompetitionSyncService,
        observer: SyncOperationObserver,
        intervals_gate: ProviderResyncGate,
        garmin_gate: ProviderResyncGate,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        redactor: Callable[[str], str],
        logger: logging.Logger,
        utc_now: Callable[[], str],
        monotonic: Callable[[], float],
        operation_id_factory: Callable[[], str],
        all_sync_days: int,
    ) -> None:
        self._config = config
        self._intervals_service = intervals_service
        self._garmin_service = garmin_service
        self._competition_service = competition_service
        self._observer = observer
        self._intervals_gate = intervals_gate
        self._garmin_gate = garmin_gate
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._redactor = redactor
        self._logger = logger
        self._utc_now = utc_now
        self._monotonic = monotonic
        self._operation_id_factory = operation_id_factory
        self._all_sync_days = all_sync_days

    def state(self, provider: str, db: Any | None = None) -> dict[str, Any]:
        self._validate_provider(provider)
        keys = PROVIDER_RESYNC_KEYS[provider]
        gate = self._gate(provider)
        if db is None:
            with self._database_manager.reader() as owned:
                return self.state(provider, owned)
        running = (
            gate.is_resetting()
            or self._key_value_repository.get(db, keys["running"]) == "1"
        )
        status = self._key_value_repository.get(db, keys["status"]) if running else None
        last_resync_at = self._key_value_repository.get(db, keys["last_at"])
        last_error = self._key_value_repository.get(db, keys["error"]) or None
        return {
            "running": running,
            "status": status,
            "last_resync_at": last_resync_at,
            "last_error": last_error,
        }

    def resync(self, provider: str, operation_id: str | None = None) -> dict[str, Any]:
        self._validate_provider(provider)
        self._validate_configuration(provider)
        gate = self._gate(provider)
        if not gate.begin_reset():
            return {"status": "already_running", "source": provider}

        keys = PROVIDER_RESYNC_KEYS[provider]
        operation_token = None
        operation_started: float | None = None
        operation_result: Any = None
        operation_succeeded = False
        operation_failure_code: str | None = None
        try:
            resolved_operation_id = operation_id or self._operation_id_factory()
            operation_token = OPERATION_CONTEXT.set(
                {"operation_id": resolved_operation_id, "trigger": "full_resync"}
            )
            operation_started = self._monotonic()
            observation.log_operation_event(
                self._logger,
                "operation_started",
                resolved_operation_id,
                "full_resync",
                provider,
                "resync",
                operation_started,
                monotonic=self._monotonic,
            )
            self._start(keys, self._label(provider))
            result = self._run(provider, resolved_operation_id)
            finished_at = self._complete(keys)
            operation_result = result
            operation_succeeded = True
            return {
                "status": "ok",
                "source": provider,
                "resynced_at": finished_at,
                **result,
            }
        except Exception as exc:
            operation_failure_code = observation.operation_error_code(exc)
            self._record_failure(keys, provider, exc)
            raise
        finally:
            try:
                if operation_started is not None:
                    self._finish(
                        keys,
                        provider,
                        operation_id or resolved_operation_id,
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

    def _validate_configuration(self, provider: str) -> None:
        if provider == "intervals" and not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR)
        if provider == "garmin" and not self._garmin_service.configured():
            raise AppError(503, GARMIN_NOT_CONFIGURED_ERROR)

    def _gate(self, provider: str) -> ProviderResyncGate:
        return self._intervals_gate if provider == "intervals" else self._garmin_gate

    def _label(self, provider: str) -> str:
        return PROVIDER_INTERVALS_NAME if provider == "intervals" else "Garmin"

    def _run(self, provider: str, operation_id: str) -> dict[str, Any]:
        if provider == "garmin":
            return self._garmin_service.sync(
                days=self._all_sync_days,
                operation_id=operation_id,
                reason=FULL_RESYNC_LABEL,
            )

        result = self._intervals_service.sync(
            FULL_RESYNC_LABEL,
            activity_days=self._all_sync_days,
            operation_id=operation_id,
        )
        with (
            self._observer.observe(
                "intervals", "competitions", FULL_RESYNC_LABEL, operation_id
            ) as scope,
            self._intervals_gate.operation(),
        ):
            competitions = self._competition_service.sync(
                reason=FULL_RESYNC_LABEL, push_local=False
            )
            scope.result = competitions
        return {**result, "competitions": competitions}

    def _set_value(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)

    def _start(self, keys: dict[str, str], label: str) -> None:
        self._set_value(keys["running"], "1")
        self._set_value(
            keys["status"],
            f"{label}: bestehende Daten bleiben erhalten, Resync läuft…",
        )
        self._set_value(keys["error"], "")
        self._set_value(keys["status"], f"{label}: vollständiger Resync läuft…")

    def _complete(self, keys: dict[str, str]) -> str:
        finished_at = self._utc_now()
        self._set_value(keys["last_at"], finished_at)
        self._set_value(keys["error"], "")
        return finished_at

    def _record_failure(
        self, keys: dict[str, str], provider: str, error: Exception
    ) -> None:
        self._set_value(keys["error"], self._redactor(str(error))[:1000])
        self._logger.exception(
            "Full provider resynchronization failed",
            extra={
                "event": "provider_full_resync_failed",
                "context": {"provider": provider},
            },
        )

    def _finish(
        self,
        keys: dict[str, str],
        provider: str,
        operation_id: str,
        operation_started: float,
        operation_succeeded: bool,
        operation_result: Any,
        operation_failure_code: str | None,
    ) -> None:
        try:
            self._set_value(keys["running"], "0")
        finally:
            try:
                self._set_value(keys["status"], "")
            finally:
                if operation_succeeded:
                    observation.log_operation_event(
                        self._logger,
                        "operation_completed",
                        operation_id,
                        "full_resync",
                        provider,
                        "resync",
                        operation_started,
                        count=observation.operation_result_count(operation_result),
                        monotonic=self._monotonic,
                    )
                else:
                    observation.log_operation_event(
                        self._logger,
                        "operation_failed",
                        operation_id,
                        "full_resync",
                        provider,
                        "resync",
                        operation_started,
                        error_code=operation_failure_code or "internal_error",
                        monotonic=self._monotonic,
                    )
