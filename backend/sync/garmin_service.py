"""Complete Garmin read synchronization lifecycle."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers import http as provider_http
from backend.providers.garmin import (
    GarminClientFactory,
    GarminCollectionOptions,
    collect_garmin_data,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver, operation_context
from backend.sync.status import SyncOperationStateWriter
from backend.sync.windows import split_date_windows

GARMIN_AUTOMATIC_SYNC_DAYS = 2

GARMIN_SYNC_LOCK = threading.Lock()


def shared_garmin_sync_lock() -> threading.Lock:
    """Return the one lock shared by normal and morning Garmin reads."""
    return GARMIN_SYNC_LOCK


class GarminRemoteReader:
    """Authenticate and collect one bounded Garmin SDK snapshot."""

    def __init__(
        self,
        config: Config,
        client_factory: GarminClientFactory,
        state_service: Any,
        diagnostic_capture: Any,
        redactor: Callable[[str], str],
        logger: logging.Logger,
        utc_now: Callable[[], str],
        local_today: Callable[[], date],
        earliest_date: date,
        chunk_days: int,
        all_sync_days: int,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._state_service = state_service
        self._diagnostic_capture = diagnostic_capture
        self._redactor = redactor
        self._logger = logger
        self._utc_now = utc_now
        self._local_today = local_today
        self._earliest_date = earliest_date
        self._chunk_days = chunk_days
        self._all_sync_days = all_sync_days

    def available(self) -> bool:
        return self._client_factory.available()

    def configured(self) -> bool:
        return self.available() and bool(
            self._config.garmin_email or Path(self._config.garmin_tokenstore).exists()
        )

    def fetch(
        self,
        days: int,
        end_date: date | None,
        *,
        status: Callable[[str], None],
        cancel_event: threading.Event | None = None,
    ) -> tuple[dict[str, Any], list[tuple[date, date]]]:
        today = end_date or self._local_today()
        windows = split_date_windows(
            days,
            end_date=today,
            earliest_date=self._earliest_date,
            chunk_days=self._chunk_days,
            all_days=self._all_sync_days,
        )
        client = self._client_factory.create(
            self._config.garmin_email or None,
            self._config.garmin_password or None,
        )

        def call_external(
            service: str,
            operation: str,
            call: Callable[[], Any],
            details: dict[str, Any] | None,
        ) -> Any:
            self._raise_if_cancelled(cancel_event)
            result = provider_http.external_call(
                service,
                operation,
                call,
                details,
                logger=self._logger,
                diagnostic_capture=self._diagnostic_capture,
                operation_context=operation_context(),
            )
            self._raise_if_cancelled(cancel_event)
            return result

        mfa_status, _ = call_external(
            "garmin",
            "login",
            lambda: client.login(self._config.garmin_tokenstore),
            {
                "email_configured": bool(self._config.garmin_email),
                "tokenstore_exists": Path(self._config.garmin_tokenstore).exists(),
            },
        )
        if mfa_status:
            self._logger.warning(
                "Garmin login requires MFA",
                extra={
                    "event": "garmin_mfa_required",
                    "context": {"service": "garmin", "operation": "login"},
                },
            )
            raise AppError(
                401,
                "Garmin verlangt MFA. Ein Tokenstore muss einmalig außerhalb "
                "des Servers eingerichtet werden.",
            )

        payload = collect_garmin_data(
            client,
            windows,
            start=windows[0][0],
            today=today,
            synced_at=self._utc_now(),
            external_call=call_external,
            redact=self._redactor,
            warn=self._warn,
            status=status,
            capability_allowed=self._state_service.capability_allowed,
            capability_failure=self._state_service.record_capability_failure,
            capability_success=self._state_service.record_capability_success,
            options=GarminCollectionOptions(
                include_recovery=end_date is None and days != self._all_sync_days,
                include_current_metrics=(
                    end_date is None and days != self._all_sync_days
                ),
            ),
        )
        self._raise_if_cancelled(cancel_event)
        return payload, windows

    def _warn(self, source: str, _message: str, error: BaseException) -> None:
        self._logger.warning(
            "Garmin data request failed",
            extra={
                "event": "garmin_request_failed",
                "context": {"source": source},
            },
            exc_info=(type(error), error, error.__traceback__),
        )

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


class GarminSyncService:
    """Own fixture and remote Garmin synchronization from gate to cleanup."""

    def __init__(
        self,
        config: Config,
        fixture_loader: Any,
        remote_reader: GarminRemoteReader,
        payload_service: Any,
        state_service: Any,
        operation_state_writer: SyncOperationStateWriter,
        observer: SyncOperationObserver,
        provider_resync_gate: ProviderResyncGate,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        logger: logging.Logger,
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
        earliest_date: date,
        all_sync_days: int,
        *,
        lock: Any = GARMIN_SYNC_LOCK,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 120.0,
    ) -> None:
        self._config = config
        self._fixture_loader = fixture_loader
        self._remote_reader = remote_reader
        self._payload_service = payload_service
        self._state_service = state_service
        self._operation_state_writer = operation_state_writer
        self._observer = observer
        self._provider_resync_gate = provider_resync_gate
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._logger = logger
        self._utc_now = utc_now
        self._local_now = local_now
        self._earliest_date = earliest_date
        self._all_sync_days = all_sync_days
        self._lock = lock
        self._monotonic = monotonic
        self._wait_seconds = wait_seconds

    def running(self) -> bool:
        return self._lock.locked()

    def available(self) -> bool:
        return (
            self._fixture_loader.path() is not None or self._remote_reader.available()
        )

    def configured(self) -> bool:
        return (
            self._fixture_loader.path() is not None or self._remote_reader.configured()
        )

    def snapshot(self) -> dict[str, Any]:
        return self._payload_service.snapshot()

    def sync(
        self,
        days: int = 30,
        operation_id: str | None = None,
        reason: str = "background",
        end_date: date | None = None,
        wait_for_existing: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        with (
            self._observer.observe("garmin", "data", reason, operation_id) as scope,
            self._provider_resync_gate.operation(),
        ):
            result = self._sync_inner(
                days,
                operation_id or scope.operation_id,
                reason,
                end_date,
                wait_for_existing,
                cancel_event,
            )
            scope.result = result
            return result

    def _sync_inner(
        self,
        days: int,
        operation_id: str,
        reason: str,
        end_date: date | None,
        wait_for_existing: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        fixture = self._fixture_loader.path()
        if not self._remote_reader.available() and fixture is None:
            self._configuration_error(
                "library_unavailable",
                "Die optionale Garmin-Bibliothek ist nicht installiert.",
                "Die optionale Garmin-Bibliothek ist nicht installiert. Für lokale "
                "Tests kann GARMIN_FIXTURE_PATH gesetzt werden.",
            )
        if fixture is None and not self._remote_reader.configured():
            message = (
                "GARMIN_EMAIL oder ein bestehender GARMINTOKENS-Tokenstore ist "
                "nicht konfiguriert."
            )
            self._configuration_error("not_configured", message, message)

        self._raise_if_cancelled(cancel_event)
        if not self._lock.acquire(blocking=False):
            if fixture is not None or not wait_for_existing:
                return {"status": "already_running"}
            return self._wait_for_existing(cancel_event)
        try:
            return self._execute(
                days, operation_id, reason, end_date, fixture is not None, cancel_event
            )
        except Exception as error:
            self._record_failure(operation_id, reason, error)
            raise
        finally:
            self._set_value("garmin_sync_status", "")
            self._lock.release()

    def _execute(
        self,
        days: int,
        operation_id: str,
        reason: str,
        end_date: date | None,
        fixture: bool,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        self._set_value("sync_operation_started_at", self._utc_now())
        self._set_status(operation_id, "fetching", 10, "Garmin-Daten werden gelesen…")
        if fixture:
            payload = self._fixture_loader.load(days)
            self._raise_if_cancelled(cancel_event)
            payload = self._payload_service.prepare_fixture(payload)
            fallback_end = self._local_now().date()
            source = "fixture"
            historical_cursor = self._earliest_date.isoformat()
        else:
            payload, windows = self._remote_reader.fetch(
                days,
                end_date,
                status=lambda message: self._set_value("garmin_sync_status", message),
                cancel_event=cancel_event,
            )
            payload = self._payload_service.prepare_remote(payload)
            fallback_end = windows[-1][1]
            source = None
            historical_cursor = windows[0][0].isoformat()
        self._raise_if_cancelled(cancel_event)
        self._set_status(
            operation_id, "storing", 75, "Lokale Garmin-Daten werden aktualisiert…"
        )
        result = self._state_service.persist_payload(
            payload,
            end_date,
            fallback_end,
            source=source,
            historical_cursor=historical_cursor,
        )
        self._operation_state_writer.write(
            operation_id,
            "completed",
            "complete",
            100,
            "Garmin-Synchronisierung abgeschlossen.",
        )
        self._set_value("sync_operation_finished_at", self._utc_now())
        return result

    def _set_status(
        self, operation_id: str, phase: str, progress: int, message: str
    ) -> None:
        self._set_value("garmin_sync_status", message)
        self._operation_state_writer.write(
            operation_id, "running", phase, progress, message
        )

    def _wait_for_existing(
        self, cancel_event: threading.Event | None
    ) -> dict[str, Any]:
        previous_sync_at = self._get_value("last_garmin_sync_at")
        deadline = self._monotonic() + self._wait_seconds
        while self._monotonic() < deadline:
            self._raise_if_cancelled(cancel_event)
            remaining = max(0.05, min(1.0, deadline - self._monotonic()))
            if not self._lock.acquire(timeout=remaining):
                continue
            try:
                current_sync_at = self._get_value("last_garmin_sync_at")
                if current_sync_at and current_sync_at != previous_sync_at:
                    return {
                        "status": "ok",
                        "waited_for_existing": True,
                        "synced_at": current_sync_at,
                    }
            finally:
                self._lock.release()
            break
        raise AppError(
            503,
            "Die laufende Garmin-Synchronisierung konnte nicht abgeschlossen werden.",
            reason="provider_busy",
        )

    def _configuration_error(
        self, log_reason: str, stored_message: str, public_message: str
    ) -> None:
        self._logger.warning(
            "External Garmin call skipped",
            extra={
                "event": "external_call_skipped",
                "context": {
                    "service": "garmin",
                    "operation": "sync",
                    "reason": log_reason,
                },
            },
        )
        self._state_service.persist_error(stored_message, "configuration")
        raise AppError(503, public_message)

    def _record_failure(self, operation_id: str, reason: str, error: Exception) -> None:
        if isinstance(error, AppError) and error.reason == "chat_cancelled":
            self._operation_state_writer.write(
                operation_id,
                "cancelled",
                "cancelled",
                100,
                "Garmin-Synchronisierung abgebrochen.",
            )
        else:
            self._state_service.persist_error(error)
            self._operation_state_writer.write(
                operation_id,
                "error",
                "error",
                100,
                "Garmin-Synchronisierung fehlgeschlagen.",
                str(error),
            )
            self._logger.error(
                "Garmin synchronization failed",
                extra={
                    "event": "garmin_sync_failed",
                    "context": {"reason": reason},
                },
                exc_info=(type(error), error, error.__traceback__),
            )
        self._set_value("sync_operation_finished_at", self._utc_now())

    def _get_value(self, key: str) -> str | None:
        with self._database_manager.unit_of_work() as db:
            return self._key_value_repository.get(db, key)

    def _set_value(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
