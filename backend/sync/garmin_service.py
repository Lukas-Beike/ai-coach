"""Complete Garmin read synchronization lifecycle."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Any, Protocol

from backend.athlete.profile import timezone_name
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.performance import morning_battery as performance_morning_battery
from backend.providers import garmin as garmin_adapter
from backend.providers import garmin_morning
from backend.providers import http as provider_http
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin import (
    ExternalCall,
    GarminClientFactory,
    GarminCollectionOptions,
    collect_garmin_activity_detail,
    collect_garmin_data,
)
from backend.providers.garmin_fields import GARMIN_EXTENDED_DATE_ALIASES
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver, operation_context
from backend.sync.refresh import sync_job_error_class
from backend.sync.status import SyncOperationStateWriter
from backend.sync.windows import split_date_windows

GARMIN_AUTOMATIC_SYNC_DAYS = 2

GARMIN_SYNC_LOCK = threading.Lock()


def _analysis_sources():
    return garmin_adapter.targeted_analysis_sources()


def shared_garmin_sync_lock() -> threading.Lock:
    """Return the one lock shared by normal and morning Garmin reads."""
    return GARMIN_SYNC_LOCK


class MorningBatteryRefresher(Protocol):
    """Refreshes the optional morning Body Battery, swallowing its failures."""

    def refresh(
        self,
        checkin_date: date | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool: ...


def refresh_morning_battery_after_sync(
    result: Mapping[str, Any],
    morning_battery: MorningBatteryRefresher,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Refresh the morning Body Battery once a Garmin sync stored new data.

    Queued and inline refreshes share this rule; a busy or failed run leaves
    the morning reading untouched. Returns ``False`` when a due Body Battery
    refresh failed, was busy, or was cancelled.
    """
    if result.get("status") not in {"ok", "partial"}:
        return True
    return morning_battery.refresh(cancel_event=cancel_event)


GARMIN_MFA_REQUIRED_MESSAGE = (
    "Garmin verlangt MFA. Bitte Garmin in den Zugangsdaten neu verbinden."
)


def _garmin_login_argument(config: Config, garmin_tokens: Any | None) -> str:
    """Tokens from the database when stored, else the legacy file rules."""
    if garmin_tokens is not None:
        return garmin_tokens.login_argument()
    return config.garmin_tokenstore


def _garmin_sync_configured(config: Config, garmin_tokens: Any | None) -> bool:
    """Stored tokens, or credentials not blocked by an explicit disconnect.

    After a disconnect or privacy delete a credential login is never persisted,
    so falling back to it would run a full SSO login on every sync.
    """
    if _garmin_tokenstore_present(config, garmin_tokens):
        return True
    if garmin_tokens is not None and garmin_tokens.disconnected():
        return False
    return bool(config.garmin_email)


def _garmin_tokenstore_present(config: Config, garmin_tokens: Any | None) -> bool:
    if garmin_tokens is not None:
        return garmin_tokens.connected()
    return Path(config.garmin_tokenstore).exists()


def _persist_garmin_tokens(
    garmin_tokens: Any | None, client: Any, login_argument: str
) -> None:
    """Store refreshed or first-imported tokens, even when collection failed."""
    if garmin_tokens is not None:
        garmin_tokens.write_back(client, login_argument)


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
        garmin_tokens: Any | None = None,
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
        self._garmin_tokens = garmin_tokens

    def available(self) -> bool:
        return self._client_factory.available()

    def configured(self) -> bool:
        return self.available() and _garmin_sync_configured(
            self._config, self._garmin_tokens
        )

    def fetch(
        self,
        days: int,
        end_date: date | None,
        *,
        status: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        include_recovery: bool | None = None,
    ) -> tuple[dict[str, Any], list[tuple[date, date]]]:
        today = end_date or self._local_today()
        windows = split_date_windows(
            days,
            end_date=today,
            earliest_date=self._earliest_date,
            chunk_days=self._chunk_days,
            all_days=self._all_sync_days,
        )
        call_external = self._external_call(cancel_event)
        client, login_argument = self._authenticated_client(call_external)

        try:
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
                    include_recovery=(
                        end_date is None and days != self._all_sync_days
                        if include_recovery is None
                        else include_recovery
                    ),
                    include_current_metrics=(
                        end_date is None and days != self._all_sync_days
                    ),
                ),
            )
        finally:
            # The login may already have refreshed the tokens; keep them even
            # when a later request fails.
            _persist_garmin_tokens(self._garmin_tokens, client, login_argument)
        self._raise_if_cancelled(cancel_event)
        return payload, windows

    def fetch_activity_details(
        self,
        provider_activity_ids: Sequence[str],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Generator[tuple[str, dict[str, Any]]]:
        """Collect the bounded detail sets of several Garmin activities.

        One client is authenticated for the whole batch, and the Garmin tokens are
        persisted when the generator finishes or is closed early. A payload gets
        ``rate_limited: True`` when one of its parts hit a Garmin rate limit; the
        remaining parts of that activity are then skipped without a call. The
        generator returns without a payload once the cancel event is set.
        """
        call_external = self._external_call(cancel_event)
        client, login_argument = self._authenticated_client(call_external)
        rate_limit_hits: list[str] = []

        def record_failure(capability: str, error: BaseException) -> None:
            if sync_job_error_class(error) == "rate_limited":
                rate_limit_hits.append(capability)
            self._state_service.record_capability_failure(capability, error)

        def allowed(capability: str) -> bool:
            # After a 429, no further detail request is sent for this activity.
            return not rate_limit_hits and bool(
                self._state_service.capability_allowed(capability)
            )

        try:
            for provider_activity_id in provider_activity_ids:
                if cancel_event is not None and cancel_event.is_set():
                    return
                rate_limit_hits.clear()
                detail = collect_garmin_activity_detail(
                    client,
                    provider_activity_id,
                    external_call=call_external,
                    redact=self._redactor,
                    warn=self._warn,
                    capability_allowed=allowed,
                    capability_failure=record_failure,
                    capability_success=self._state_service.record_capability_success,
                )
                if rate_limit_hits:
                    detail["rate_limited"] = True
                yield provider_activity_id, detail
        finally:
            # Keep refreshed tokens even when a detail request fails or the consumer stops early.
            _persist_garmin_tokens(self._garmin_tokens, client, login_argument)

    def fetch_activity_detail(
        self,
        provider_activity_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Collect the bounded detail sets of one Garmin activity."""
        details = self.fetch_activity_details(
            [provider_activity_id], cancel_event=cancel_event
        )
        try:
            item = next(details, None)
        finally:
            details.close()
        self._raise_if_cancelled(cancel_event)
        if item is None:
            raise RuntimeError("Garmin activity detail batch produced no payload.")
        return item[1]

    def fetch_nutrition_data(
        self, source: str, start: date, end: date
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read only daily energy or body weight for a bounded nutrition range."""
        if source not in {"daily_stats", "weight"}:
            raise ValueError("Unsupported Garmin nutrition source")
        if not self.configured():
            raise AppError(
                503, "Garmin ist nicht konfiguriert.", reason="not_configured"
            )
        call_external = self._external_call(None)
        client, login_argument = self._authenticated_client(call_external)
        try:
            try:
                return garmin_adapter.fetch_targeted_nutrition(
                    client, source, start, end, external_call=call_external
                )
            except NotImplementedError as exc:
                raise AppError(
                    503,
                    "Garmin-Daten für den Zeitraum sind nicht verfügbar.",
                    reason="not_supported",
                ) from exc
        finally:
            _persist_garmin_tokens(self._garmin_tokens, client, login_argument)

    def fetch_analysis_data(
        self, area: str, start: date, end: date
    ) -> tuple[dict[str, Any], dict[str, bool]]:
        """Read only the Garmin sources used by one Analyse subarea."""
        sources = _analysis_sources()
        if area not in sources or start > end or (end - start).days > 89:
            raise AppError(400, "Ungültiger Analyse-Aktualisierungsbereich.")
        if not self.configured():
            raise AppError(
                503, "Garmin ist nicht konfiguriert.", reason="not_configured"
            )
        call_external = self._external_call(None)
        client, login_argument = self._authenticated_client(call_external)
        try:
            return garmin_adapter.fetch_targeted_analysis(
                client,
                area,
                start,
                end,
                external_call=call_external,
                capability_allowed=self._state_service.capability_allowed,
                capability_failure=self._state_service.record_capability_failure,
                capability_success=self._state_service.record_capability_success,
                warn=self._warn,
            )
        finally:
            _persist_garmin_tokens(self._garmin_tokens, client, login_argument)

    def _external_call(self, cancel_event: threading.Event | None) -> ExternalCall:
        """Wrap SDK calls with the provider transport and cancellation checks."""

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

        return call_external

    def _authenticated_client(self, call_external: ExternalCall) -> tuple[Any, str]:
        """Create the SDK client and log in; MFA stops before any collection."""
        login_argument = _garmin_login_argument(self._config, self._garmin_tokens)
        client, mfa_status = garmin_adapter.authenticate_client(
            self._client_factory,
            self._config.garmin_email or None,
            self._config.garmin_password or None,
            login_argument,
            external_call=call_external,
            tokenstore_exists=_garmin_tokenstore_present(
                self._config, self._garmin_tokens
            ),
        )
        if mfa_status:
            self._logger.warning(
                "Garmin login requires MFA",
                extra={
                    "event": "garmin_mfa_required",
                    "context": {"service": GARMIN_ID, "operation": "login"},
                },
            )
            raise AppError(401, GARMIN_MFA_REQUIRED_MESSAGE)
        return client, login_argument

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


class GarminNutritionRefreshService:
    """Refresh only Garmin energy or body measurements for nutrition views."""

    def __init__(
        self,
        reader: GarminRemoteReader,
        database_manager: DatabaseManager,
        snapshot_writer: GarminSnapshotWriter,
        payload_service: Any,
        coordination: GarminSyncCoordination,
        utc_now: Callable[[], str],
        configured: Callable[[], bool],
    ) -> None:
        self._reader = reader
        self._database_manager = database_manager
        self._snapshot_writer = snapshot_writer
        self._payload_service = payload_service
        self._coordination = coordination
        self._utc_now = utc_now
        self._configured = configured

    def refresh(self, source: str, start: date, end: date) -> dict[str, Any]:
        if source not in {"daily_stats", "weight"} or start > end:
            raise AppError(400, "Ungültiger Ernährungs-Aktualisierungsbereich.")
        if not self._configured():
            return {"status": "partial", "reason": "not_configured"}
        with self._coordination.operation():
            if not self._coordination.acquire():
                raise AppError(
                    503, "Garmin wird bereits aktualisiert.", reason="provider_busy"
                )
            try:
                try:
                    records, complete = self._reader.fetch_nutrition_data(
                        source, start, end
                    )
                except AppError as exc:
                    if exc.reason in {
                        "not_configured",
                        "not_supported",
                        "library_unavailable",
                    }:
                        return {"status": "partial", "reason": exc.reason}
                    raise
                except Exception:  # noqa: BLE001 - provider errors stay out of HTTP responses
                    return {"status": "partial", "reason": "provider_unavailable"}
                fetched_at = self._utc_now()
                if source == "weight" and not records:
                    complete = False
                snapshot = self._payload_service.snapshot()
                self._apply_nutrition_refresh(
                    snapshot, source, start, end, records, complete, fetched_at
                )
                return {
                    "status": "ok" if complete else "partial",
                    "source": "Garmin Connect",
                    "data_source": source,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "records": len(records),
                    "synced_at": fetched_at,
                }
            finally:
                self._coordination.release()

    def _apply_nutrition_refresh(
        self,
        snapshot: dict[str, Any],
        source: str,
        start: date,
        end: date,
        records: list[dict[str, Any]],
        complete: bool,
        fetched_at: str,
    ) -> None:
        existing = snapshot.get(source)
        if complete and source == "daily_stats":
            existing = [
                row
                for row in (existing if isinstance(existing, list) else [])
                if not _record_date_in_range(row, start, end)
            ]
        if source == "weight":
            snapshot[source] = garmin_adapter.merge_weight_snapshots(records, existing)
        else:
            snapshot[source] = garmin_morning.merge_garmin_records(records, existing)
        self._mark_nutrition_freshness(
            snapshot, source, start, end, complete, fetched_at
        )
        snapshot.setdefault("provider_sync", {}).setdefault("nutrition", {})[source] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete": complete,
        }
        with self._database_manager.unit_of_work() as db:
            self._snapshot_writer.write_nutrition_refresh(
                db, snapshot, source, fetched_at, records
            )

    @staticmethod
    def _mark_nutrition_freshness(
        snapshot: dict[str, Any],
        source: str,
        start: date,
        end: date,
        complete: bool,
        fetched_at: str,
    ) -> None:
        freshness = "current" if complete else "partial"
        snapshot.setdefault("nutrition_refresh", {}).setdefault(source, {}).update(
            {
                (start + timedelta(days=offset)).isoformat(): {
                    "freshness": freshness,
                    "fetched_at": fetched_at,
                }
                for offset in range((end - start).days + 1)
            }
        )


class GarminAnalysisRefreshService:
    """Refresh only the Garmin endpoints used by one Analyse subarea."""

    def __init__(
        self,
        reader: GarminRemoteReader,
        database_manager: DatabaseManager,
        snapshot_writer: GarminSnapshotWriter,
        payload_service: Any,
        coordination: GarminSyncCoordination,
        utc_now: Callable[[], str],
        configured: Callable[[], bool],
    ) -> None:
        self._reader = reader
        self._database_manager = database_manager
        self._snapshot_writer = snapshot_writer
        self._payload_service = payload_service
        self._coordination = coordination
        self._utc_now = utc_now
        self._configured = configured

    def refresh(self, area: str, start: date, end: date) -> dict[str, Any]:
        if (
            area not in {"sessions", "load", "performance", "recovery"}
            or start > end
            or (end - start).days > 89
        ):
            raise AppError(400, "Ungültiger Analyse-Aktualisierungsbereich.")
        if not self._configured():
            return {"status": "partial", "reason": "not_configured", "area": area}
        with self._coordination.operation():
            if not self._coordination.acquire():
                raise AppError(
                    503, "Garmin wird bereits aktualisiert.", reason="provider_busy"
                )
            try:
                try:
                    fetched, sources_complete = self._reader.fetch_analysis_data(
                        area, start, end
                    )
                except AppError as exc:
                    if exc.reason in {
                        "not_configured",
                        "not_supported",
                        "library_unavailable",
                    }:
                        return {"status": "partial", "reason": exc.reason, "area": area}
                    raise
                except Exception:  # noqa: BLE001 - provider errors stay out of HTTP responses.
                    return {
                        "status": "partial",
                        "reason": "provider_unavailable",
                        "area": area,
                    }
                fetched_at = self._utc_now()
                snapshot = self._payload_service.snapshot()
                self._apply_analysis_refresh(
                    snapshot, area, start, end, fetched, sources_complete, fetched_at
                )
                complete = bool(sources_complete) and all(sources_complete.values())
                return {
                    "status": "ok" if complete else "partial",
                    "source": "Garmin Connect",
                    "area": area,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "sources": dict(sources_complete),
                    "records": sum(
                        len(value) if isinstance(value, list) else 1
                        for value in fetched.values()
                    ),
                    "synced_at": fetched_at,
                }
            finally:
                self._coordination.release()

    def _apply_analysis_refresh(
        self,
        snapshot: dict[str, Any],
        area: str,
        start: date,
        end: date,
        fetched: dict[str, Any],
        sources_complete: dict[str, bool],
        fetched_at: str,
    ) -> None:
        freshness = snapshot.setdefault("source_freshness", {})
        pagination = snapshot.setdefault("provider_sync", {}).setdefault(
            "pagination", {}
        )
        for source, is_complete in sources_complete.items():
            incoming = fetched.get(source)
            self._merge_analysis_source(
                snapshot, source, incoming, is_complete, start, end
            )
            self._record_analysis_source_status(
                freshness,
                pagination,
                source,
                incoming,
                is_complete,
                start,
                end,
                fetched_at,
            )
        snapshot.setdefault("provider_sync", {}).setdefault("analysis", {})[area] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete": bool(sources_complete) and all(sources_complete.values()),
            "sources": dict(sources_complete),
            "fetched_at": fetched_at,
        }
        with self._database_manager.unit_of_work() as db:
            self._snapshot_writer.write_analysis_refresh(
                db, snapshot, fetched_at, fetched
            )

    @staticmethod
    def _merge_analysis_source(
        snapshot: dict[str, Any],
        source: str,
        incoming: Any,
        is_complete: bool,
        start: date,
        end: date,
    ) -> None:
        if incoming is None:
            return
        old = snapshot.get(source)
        if isinstance(incoming, list):
            previous = old if isinstance(old, list) else []
            if source == "weight":
                snapshot[source] = garmin_adapter.merge_weight_snapshots(
                    incoming, previous
                )
                return
            retained = (
                [row for row in previous if not _record_date_in_range(row, start, end)]
                if is_complete
                else previous
            )
            snapshot[source] = garmin_morning.merge_garmin_records(incoming, retained)
        elif is_complete or not isinstance(old, dict):
            snapshot[source] = incoming
        else:
            snapshot[source] = {**old, **incoming}

    @staticmethod
    def _record_analysis_source_status(
        freshness: dict[str, Any],
        pagination: dict[str, Any],
        source: str,
        incoming: Any,
        is_complete: bool,
        start: date,
        end: date,
        fetched_at: str,
    ) -> None:
        previous = freshness.get(source, {})
        if incoming is None:
            freshness[source] = {**previous, "freshness": "stale"}
        else:
            freshness[source] = {
                **previous,
                "freshness": "current" if is_complete else "partial",
                "fetched_at": fetched_at,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
            }
        pagination[source] = {
            **pagination.get(source, {}),
            "complete": is_complete,
            "records": len(incoming)
            if isinstance(incoming, list)
            else int(incoming is not None),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
        }


def _record_date_in_range(record: Any, start: date, end: date) -> bool:
    if not isinstance(record, dict):
        return False
    raw = next(
        (record.get(key) for key in GARMIN_EXTENDED_DATE_ALIASES if record.get(key)),
        None,
    )
    try:
        observed = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return False
    return start <= observed <= end


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
        garmin_tokens: Any | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._profile_service = profile_service
        self._athlete_clock = athlete_clock
        self._diagnostic_capture = diagnostic_capture
        self._logger = logger
        self._garmin_tokens = garmin_tokens

    def configured(self) -> bool:
        return self._client_factory.available() and _garmin_sync_configured(
            self._config, self._garmin_tokens
        )

    def fetch(self, checkin_date: date) -> tuple[Any, Any]:
        client = self._client_factory.create(
            self._config.garmin_email or None,
            self._config.garmin_password or None,
            return_on_mfa=True,
        )
        profile_timezone = timezone_name(self._profile_service.get().get("timezone"))
        fallback_zone = self._athlete_clock.now().tzinfo or UTC
        login_argument = _garmin_login_argument(self._config, self._garmin_tokens)
        try:
            return garmin_morning.fetch_morning_body_battery(
                client,
                checkin_date,
                tokenstore=login_argument,
                email_configured=bool(self._config.garmin_email),
                tokenstore_exists=_garmin_tokenstore_present(
                    self._config, self._garmin_tokens
                ),
                profile_timezone=profile_timezone,
                fallback_zone=fallback_zone,
                external_call=self._external_call,
                sleep_bounds=performance_morning_battery.sleep_bounds,
            )
        finally:
            _persist_garmin_tokens(self._garmin_tokens, client, login_argument)

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
        return (
            self._fixture_loader.path() is not None or self._remote_reader.available()
        )

    def configured(self) -> bool:
        return (
            self._fixture_loader.path() is not None or self._remote_reader.configured()
        )

    def fixture_enabled(self) -> bool:
        return self._fixture_loader.path() is not None

    def read(
        self,
        days: int,
        end_date: date | None,
        *,
        status: Callable[[str], None],
        cancel_event: threading.Event | None,
        include_recovery: bool | None = None,
    ) -> tuple[dict[str, Any], list[tuple[date, date]] | None, str | None, str]:
        if self.fixture_enabled():
            payload = self._fixture_loader.load(days)
            return payload, None, "fixture", self._earliest_date.isoformat()
        payload, windows = self._remote_reader.fetch(
            days,
            end_date,
            status=status,
            cancel_event=cancel_event,
            include_recovery=include_recovery,
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

    def record_metric_export_status(self, message: str) -> None:
        self._set("last_garmin_metric_export_status", f"{self._utc_now()}: {message}")

    def log_configuration_skip(self, reason: str) -> None:
        self._logger.warning(
            "External Garmin call skipped",
            extra={
                "event": "external_call_skipped",
                "context": {
                    "service": GARMIN_ID,
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


def _log_backfill_failure(error: Exception) -> None:
    logging.getLogger(__name__).warning(
        "Automatic Garmin activity detail backfill failed (%s)",
        type(error).__name__,
    )


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
        metric_export: Callable[[], dict[str, Any] | None] | None = None,
        activity_detail_backfill: Callable[
            [threading.Event | None], dict[str, Any] | None
        ]
        | None = None,
    ) -> None:
        self._source = source
        self._payload_service = payload_service
        self._state_service = state_service
        self._operation_state_writer = operation_state_writer
        self._observer = observer
        self._coordination = coordination
        self._lifecycle_state = lifecycle_state
        self._metric_export = metric_export
        self._activity_detail_backfill = activity_detail_backfill

    def running(self) -> bool:
        return self._coordination.running()

    def available(self) -> bool:
        return self._source.available()

    def configured(self) -> bool:
        return self._source.configured()

    def snapshot(self) -> dict[str, Any]:
        return self._payload_service.snapshot()

    def automatic_sync_days(self, minimum_days: int) -> int:
        return self._payload_service.automatic_sync_days(minimum_days)

    def automatic_sync_window(self, minimum_days: int) -> tuple[int, date | None]:
        return self._payload_service.automatic_sync_window(minimum_days)

    def awaited_run_status(
        self, days: int, end_date: date | None, synced_at: str | None
    ) -> str | None:
        return self._payload_service.awaited_run_status(days, end_date, synced_at)

    def sync(
        self,
        days: int = 30,
        operation_id: str | None = None,
        reason: str = "background",
        end_date: date | None = None,
        wait_for_existing: bool = False,
        cancel_event: threading.Event | None = None,
        include_recovery: bool | None = None,
    ) -> dict[str, Any]:
        with (
            self._observer.observe(GARMIN_ID, "data", reason, operation_id) as scope,
            self._coordination.operation(),
        ):
            result = self._sync_inner(
                days,
                operation_id or scope.operation_id,
                reason,
                end_date,
                wait_for_existing,
                cancel_event,
                include_recovery,
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
        include_recovery: bool | None,
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
            self._configuration_error(
                "not_configured", message, message, reason="not_configured"
            )

        self._raise_if_cancelled(cancel_event)
        if not self._coordination.acquire():
            if fixture or not wait_for_existing:
                return {"status": "already_running"}
            return self._wait_for_existing(cancel_event)
        try:
            return self._execute(
                days, operation_id, end_date, cancel_event, include_recovery
            )
        except Exception as error:
            self._record_failure(operation_id, reason, error)
            raise
        finally:
            try:
                self._lifecycle_state.set_sync_status("")
            finally:
                self._coordination.release()

    def _execute(
        self,
        days: int,
        operation_id: str,
        end_date: date | None,
        cancel_event: threading.Event | None,
        include_recovery: bool | None,
    ) -> dict[str, Any]:
        self._lifecycle_state.record_sync_started()
        self._set_status(operation_id, "fetching", 10, "Garmin-Daten werden gelesen…")
        payload, windows, source, historical_cursor = self._source.read(
            days,
            end_date,
            status=self._lifecycle_state.set_sync_status,
            cancel_event=cancel_event,
            include_recovery=include_recovery,
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
        message = "Garmin-Synchronisierung abgeschlossen."
        if (
            self._metric_export is not None
            and source != "fixture"
            and end_date is None
            and result.get("status") == "ok"
            and not (cancel_event is not None and cancel_event.is_set())
        ):
            self._set_status(
                operation_id,
                "metric-export",
                90,
                "Garmin-Messwerte werden mit Intervals.icu abgeglichen…",
            )
            try:
                receipt = self._metric_export()
                if receipt is not None:
                    result["metric_export"] = receipt
                    export_message = (
                        f"Intervals.icu: {receipt['exported']} Messwerte gesendet, "
                        f"{receipt['conflicts']} Konflikte, {receipt['failed']} fehlgeschlagen."
                    )
                    self._lifecycle_state.record_metric_export_status(export_message)
                    message += f" {export_message}"
            except Exception as error:  # noqa: BLE001 - import remains successful; never expose provider errors
                logging.getLogger(__name__).warning(
                    "Automatic metric export failed (%s)", type(error).__name__
                )
                result["metric_export"] = {"exported": 0, "conflicts": 0, "failed": 1}
                export_message = "Automatischer Messwert-Abgleich mit Intervals.icu fehlgeschlagen; erneuter Versuch beim nächsten Garmin-Sync."
                self._lifecycle_state.record_metric_export_status(export_message)
                message += f" {export_message}"
        if (
            self._activity_detail_backfill is not None
            and source != "fixture"
            and end_date is None
            and result.get("status") == "ok"
            and not (cancel_event is not None and cancel_event.is_set())
        ):
            self._backfill_activity_details(
                self._activity_detail_backfill, operation_id, cancel_event, result
            )
        self._operation_state_writer.write(
            operation_id,
            "completed",
            "complete",
            100,
            message,
        )
        self._lifecycle_state.record_sync_finished()
        return result

    def _backfill_activity_details(
        self,
        backfill: Callable[[threading.Event | None], dict[str, Any] | None],
        operation_id: str,
        cancel_event: threading.Event | None,
        result: dict[str, Any],
    ) -> None:
        self._set_status(
            operation_id,
            "activity-details",
            95,
            "Garmin-Aktivitätsdetails werden geladen…",
        )
        try:
            # Runs under the sync lock and gate held by this sync.
            counts = backfill(cancel_event)
            if counts is not None:
                result["activity_details"] = counts
        except AppError as error:
            if error.reason == "chat_cancelled":
                raise
            _log_backfill_failure(error)
        except Exception as error:  # noqa: BLE001 - the sync stays successful; never expose provider errors
            _log_backfill_failure(error)
        # A cancel during the backfill ends the sync as cancelled, not completed.
        self._raise_if_cancelled(cancel_event)

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
            remaining = max(0.05, min(1.0, deadline - self._coordination.monotonic()))
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
        self,
        log_reason: str,
        stored_message: str,
        public_message: str,
        *,
        reason: str | None = None,
    ) -> None:
        self._lifecycle_state.log_configuration_skip(log_reason)
        self._state_service.persist_error(stored_message, "configuration")
        raise AppError(503, public_message, reason=reason)

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
