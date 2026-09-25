"""Complete Garmin read synchronization lifecycle."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date, timezone
from pathlib import Path
from typing import Any

from backend.athlete.profile import timezone_name
from backend.config import Config
from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.performance import morning_battery as performance_morning_battery
from backend.providers import http as provider_http
from backend.providers import garmin_morning
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


class GarminMorningRemoteReader:
    """Read the current sleep window and Body Battery through Garmin."""

    def __init__(
        self,
        config: Config,
        client_factory: GarminClientFactory,
        profile_service: Any,
        athlete_clock: Any,
        diagnostic_capture: Any,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._profile_service = profile_service
        self._athlete_clock = athlete_clock
        self._diagnostic_capture = diagnostic_capture
        self._logger = logger

    def configured(self) -> bool:
        return self._client_factory.available() and bool(
            self._config.garmin_email
            or Path(self._config.garmin_tokenstore).exists()
        )

    def fetch(self, checkin_date: date) -> tuple[Any, Any]:
        client = self._client_factory.create(
            self._config.garmin_email or None,
            self._config.garmin_password or None,
        )
        profile_timezone = timezone_name(
            self._profile_service.get().get("timezone")
        )
        fallback_zone = self._athlete_clock.now().tzinfo or timezone.utc
        return garmin_morning.fetch_morning_body_battery(
            client,
            checkin_date,
            tokenstore=self._config.garmin_tokenstore,
            email_configured=bool(self._config.garmin_email),
            tokenstore_exists=Path(self._config.garmin_tokenstore).exists(),
            profile_timezone=profile_timezone,
            fallback_zone=fallback_zone,
            external_call=self._external_call,
            sleep_bounds=performance_morning_battery.sleep_bounds,
        )

    def _external_call(
        self,
        service: str,
        operation: str,
        callback: Callable[[], Any],
        details: dict[str, Any] | None,
    ) -> Any:
        return provider_http.external_call(
            service,
            operation,
            callback,
            details,
            logger=self._logger,
            diagnostic_capture=self._diagnostic_capture,
            operation_context=operation_context(),
        )


class GarminSyncSource:
    """Choose and read the configured fixture or authenticated Garmin source."""

    def __init__(
        self,
        fixture_loader: Any,
        remote_reader: GarminRemoteReader,
        earliest_date: date,
        local_today: Callable[[], date],
    ) -> None:
        self._fixture_loader = fixture_loader
        self._remote_reader = remote_reader
        self._earliest_date = earliest_date
        self._local_today = local_today

    def available(self) -> bool:
        return self._fixture_loader.path() is not None or self._remote_reader.available()

    def configured(self) -> bool:
        return self._fixture_loader.path() is not None or self._remote_reader.configured()

    def fixture_enabled(self) -> bool:
        return self._fixture_loader.path() is not None

    def read(
        self,
        days: int,
        end_date: date | None,
        *,
        status: Callable[[str], None],
        cancel_event: threading.Event | None,
    ) -> tuple[dict[str, Any], list[tuple[date, date]] | None, str | None, str]:
        if self.fixture_enabled():
            payload = self._fixture_loader.load(days)
            return payload, None, "fixture", self._earliest_date.isoformat()
        payload, windows = self._remote_reader.fetch(
            days, end_date, status=status, cancel_event=cancel_event
        )
        return payload, windows, None, windows[0][0].isoformat()

    def fallback_end(
        self, source: str | None, windows: list[tuple[date, date]] | None
    ) -> date:
        if source == "fixture":
            return self._local_today()
        if windows is None:
            raise ValueError("Remote Garmin sync is missing its date windows.")
        return windows[-1][1]


class GarminSyncCoordination:
    """Own Garmin's shared operation gate, Morning lock, and wait policy."""

    def __init__(
        self,
        lock: Any = GARMIN_SYNC_LOCK,
        gate: ProviderResyncGate | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 120.0,
    ) -> None:
        self._lock = lock
        self._gate = gate
        self._monotonic = monotonic
        self._wait_seconds = wait_seconds

    def running(self) -> bool:
        return self._lock.locked()

    def operation(self) -> AbstractContextManager[None]:
        return self._gate.operation() if self._gate is not None else nullcontext()

    def acquire(self, *, timeout: float | None = None) -> bool:
        if timeout is None:
            return self._lock.acquire(blocking=False)
        return self._lock.acquire(timeout=timeout)

    def release(self) -> None:
        self._lock.release()

    def wait_deadline(self) -> float:
        return self._monotonic() + self._wait_seconds

    def monotonic(self) -> float:
        return self._monotonic()


class GarminSyncLifecycleState:
    """Own durable lifecycle timestamps, visible status, and lifecycle logs."""

    def __init__(
        self,
        database_manager: Any,
        key_value_repository: Any,
        utc_now: Callable[[], str],
        logger: logging.Logger,
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._utc_now = utc_now
        self._logger = logger

    def last_sync_at(self) -> str | None:
        return self._get("last_garmin_sync_at")

    def set_sync_status(self, message: str) -> None:
        self._set("garmin_sync_status", message)

    def record_sync_started(self) -> None:
        self._set("sync_operation_started_at", self._utc_now())

    def record_sync_finished(self) -> None:
        self._set("sync_operation_finished_at", self._utc_now())

    def log_configuration_skip(self, reason: str) -> None:
        self._logger.warning(
            "External Garmin call skipped",
            extra={
                "event": "external_call_skipped",
                "context": {
                    "service": "garmin",
                    "operation": "sync",
                    "reason": reason,
                },
            },
        )

    def log_failure(self, reason: str, error: Exception) -> None:
        self._logger.error(
            "Garmin synchronization failed",
            extra={"event": "garmin_sync_failed", "context": {"reason": reason}},
            exc_info=(type(error), error, error.__traceback__),
        )

    def _get(self, key: str) -> str | None:
        with self._database_manager.unit_of_work() as db:
            return self._key_value_repository.get(db, key)

    def _set(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)


class GarminSyncService:
    """Own fixture and remote Garmin synchronization from gate to cleanup."""

    def __init__(
        self,
        source: GarminSyncSource,
        payload_service: Any,
        state_service: Any,
        operation_state_writer: SyncOperationStateWriter,
        observer: SyncOperationObserver,
        coordination: GarminSyncCoordination,
        lifecycle_state: GarminSyncLifecycleState,
    ) -> None:
        self._source = source
        self._payload_service = payload_service
        self._state_service = state_service
        self._operation_state_writer = operation_state_writer
        self._observer = observer
        self._coordination = coordination
        self._lifecycle_state = lifecycle_state

    def running(self) -> bool:
        return self._coordination.running()

    def available(self) -> bool:
        return self._source.available()

    def configured(self) -> bool:
        return self._source.configured()

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
            self._coordination.operation(),
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
        fixture = self._source.fixture_enabled()
        if not self._source.available():
            self._configuration_error(
                "library_unavailable",
                "Die optionale Garmin-Bibliothek ist nicht installiert.",
                "Die optionale Garmin-Bibliothek ist nicht installiert. Für lokale "
                "Tests kann GARMIN_FIXTURE_PATH gesetzt werden.",
            )
        if not fixture and not self._source.configured():
            message = (
                "GARMIN_EMAIL oder ein bestehender GARMINTOKENS-Tokenstore ist "
                "nicht konfiguriert."
            )
            self._configuration_error("not_configured", message, message)

        self._raise_if_cancelled(cancel_event)
        if not self._coordination.acquire():
            if fixture or not wait_for_existing:
                return {"status": "already_running"}
            return self._wait_for_existing(cancel_event)
        try:
            return self._execute(days, operation_id, end_date, cancel_event)
        except Exception as error:
            self._record_failure(operation_id, reason, error)
            raise
        finally:
            self._lifecycle_state.set_sync_status("")
            self._coordination.release()

    def _execute(
        self,
        days: int,
        operation_id: str,
        end_date: date | None,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        self._lifecycle_state.record_sync_started()
        self._set_status(operation_id, "fetching", 10, "Garmin-Daten werden gelesen…")
        payload, windows, source, historical_cursor = self._source.read(
            days,
            end_date,
            status=self._lifecycle_state.set_sync_status,
            cancel_event=cancel_event,
        )
        self._raise_if_cancelled(cancel_event)
        payload = (
            self._payload_service.prepare_fixture(payload)
            if source == "fixture"
            else self._payload_service.prepare_remote(payload)
        )
        fallback_end = self._source.fallback_end(source, windows)
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
        self._lifecycle_state.record_sync_finished()
        return result

    def _set_status(
        self, operation_id: str, phase: str, progress: int, message: str
    ) -> None:
        self._lifecycle_state.set_sync_status(message)
        self._operation_state_writer.write(
            operation_id, "running", phase, progress, message
        )

    def _wait_for_existing(
        self, cancel_event: threading.Event | None
    ) -> dict[str, Any]:
        previous_sync_at = self._lifecycle_state.last_sync_at()
        deadline = self._coordination.wait_deadline()
        while self._coordination.monotonic() < deadline:
            self._raise_if_cancelled(cancel_event)
            remaining = max(
                0.05, min(1.0, deadline - self._coordination.monotonic())
            )
            if not self._coordination.acquire(timeout=remaining):
                continue
            try:
                current_sync_at = self._lifecycle_state.last_sync_at()
                if current_sync_at and current_sync_at != previous_sync_at:
                    return {
                        "status": "ok",
                        "waited_for_existing": True,
                        "synced_at": current_sync_at,
                    }
            finally:
                self._coordination.release()
            break
        raise AppError(
            503,
            "Die laufende Garmin-Synchronisierung konnte nicht abgeschlossen werden.",
            reason="provider_busy",
        )

    def _configuration_error(
        self, log_reason: str, stored_message: str, public_message: str
    ) -> None:
        self._lifecycle_state.log_configuration_skip(log_reason)
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
            self._lifecycle_state.log_failure(reason, error)
        self._lifecycle_state.record_sync_finished()

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
