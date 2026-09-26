"""Stateful weather refresh and cache orchestration."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.errors import AppError
from backend.weather import cache, history


@dataclass(frozen=True)
class WeatherRetryPolicy:
    """Cache freshness and bounded retry delays for weather refreshes."""

    cache_seconds: int = 10800
    retry_base_seconds: int = 900
    retry_max_seconds: int = 21600


class WeatherCacheStore:
    """Own weather profile reads and atomic cache/history/failure persistence."""

    def __init__(self, database_manager: Any, key_values: Any, profile_service: Any):
        self._database_manager = database_manager
        self._key_values = key_values
        self._profile_service = profile_service

    def read(self) -> tuple[str, Any, Any]:
        with self._database_manager.unit_of_work() as db:
            query = self._location(db)
            return (
                query,
                self._key_values.get(db, cache.CACHE_KEY),
                self._key_values.get(db, cache.FAILURE_KEY),
            )

    def store_refresh(
        self, state: cache.WeatherCacheState, refreshed_cache: dict[str, Any]
    ) -> bool:
        """Return true if the location changed before the atomic writes."""
        with self._database_manager.unit_of_work() as db:
            if self._location(db) != state.query:
                return True
            archived = history.remember_forecasts(
                history.decode_history(self._key_values.get(db, cache.HISTORY_KEY)),
                state.cached if state.cache_matches else {},
                refreshed_cache,
            )
            self._key_values.set(
                db,
                cache.HISTORY_KEY,
                json.dumps(archived, ensure_ascii=False, separators=(",", ":")),
            )
            self._key_values.set(
                db,
                cache.CACHE_KEY,
                json.dumps(refreshed_cache, ensure_ascii=False, separators=(",", ":")),
            )
            self._key_values.set(db, cache.FAILURE_KEY, "")
        return False

    def store_failure(self, failure: dict[str, Any]) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_values.set(
                db, cache.FAILURE_KEY, json.dumps(failure, ensure_ascii=False)
            )

    def _location(self, db: Any) -> str:
        return (
            self._profile_service.get_from_db(db)
            .get("weather_location", "")
            .strip()[:200]
        )


class WeatherRefreshJournal:
    """Own tracked refresh lifecycle, operation context, and safe failure logs."""

    def __init__(
        self,
        refresh_tracker: Any,
        operation_context: Any,
        operation_id_factory: Callable[[], str],
        logger: Any,
    ):
        self._refresh_tracker = refresh_tracker
        self._operation_context = operation_context
        self._operation_id_factory = operation_id_factory
        self._logger = logger

    def start(self) -> str:
        operation = self._operation_context.get() or {}
        return self._refresh_tracker.start(
            "weather",
            "forecast",
            operation.get("operation_id") or self._operation_id_factory(),
            operation.get("trigger") or "background",
        )

    def finish(
        self,
        refresh_id: str | None,
        status: str,
        phase: str,
        *,
        error: Exception | None = None,
    ) -> None:
        if not refresh_id:
            return
        self._refresh_tracker.finish(
            refresh_id,
            status,
            phase,
            error_code=self._refresh_tracker.error_code(error) if error else None,
        )

    def log_failure(self, error: Exception) -> None:
        self._logger.warning(
            "Weather synchronization failed",
            extra={
                "event": "weather_sync_failed",
                "context": {"error_type": type(error).__name__},
            },
        )


class WeatherService:
    """Own weather refresh serialization and coordinate its domain owners."""

    def __init__(
        self,
        cache_store: WeatherCacheStore,
        client_factory: Callable[[], Any],
        refresh_journal: WeatherRefreshJournal,
        maintenance_gate: Any,
        now: Callable[[], datetime],
        today: Callable[[], date],
        retry_policy: WeatherRetryPolicy | None = None,
    ) -> None:
        self._cache_store = cache_store
        self._client_factory = client_factory
        self._refresh_journal = refresh_journal
        self._maintenance_gate = maintenance_gate
        self._now = now
        self._today = today
        self._retry_policy = retry_policy or WeatherRetryPolicy()
        self._refresh_lock = threading.Lock()

    def state(
        self,
        planned: list[dict[str, Any]] | None = None,
        refresh: bool = True,
        force: bool = False,
        *,
        track_refresh: bool = True,
    ) -> dict[str, Any]:
        with self._maintenance_gate.operation():
            return self._state(planned, refresh, force, track_refresh)

    def _state(
        self,
        planned: list[dict[str, Any]] | None,
        refresh: bool,
        force: bool,
        track_refresh: bool,
    ) -> dict[str, Any]:
        query, cached_value, failure_value = self._cache_store.read()
        if not query:
            return {
                "configured": False,
                "state": "not_configured",
                "provider": "Open-Meteo",
                "days": [],
                "recommendations": [],
                "message": "Hinterlege im Profil einen Wetterort (Stadt oder PLZ).",
            }
        state = cache.cache_state(
            query,
            cached_value,
            failure_value,
            now=self._now(),
            cache_seconds=self._retry_policy.cache_seconds,
        )
        if refresh and self._refresh(state, force, track_refresh):
            return self._state(planned, False, force, track_refresh)
        if not state.cache_matches:
            return cache.unavailable_state(refresh, state.error)
        return cache.ready_state(state, planned, today=self._today())

    def _refresh(
        self,
        state: cache.WeatherCacheState,
        force: bool,
        track_refresh: bool,
    ) -> bool:
        if not (
            force
            or not state.cache_matches
            or state.cache_age >= self._retry_policy.cache_seconds
        ):
            return False
        if cache.retry_wait(state.failure, now=self._now()) > 0 and not force:
            state.error = (
                "Wetterdaten konnten nach einem Fehler noch nicht erneut geladen werden."
            )
            return False

        refresh_id = self._refresh_journal.start() if track_refresh else None
        try:
            with self._refresh_lock:
                refreshed_cache = self._client_factory().fetch(state.query)
                location_changed = self._cache_store.store_refresh(
                    state, refreshed_cache
                )
            if location_changed:
                self._refresh_journal.finish(refresh_id, "skipped", "location_changed")
                return True
            state.cached = refreshed_cache
            state.cache_matches = True
            state.refreshed = True
            state.error = None
            self._refresh_journal.finish(refresh_id, "success", "complete")
        except Exception as exc:  # noqa: BLE001 - provider boundary normalizes failures
            self._record_failure(state, exc, refresh_id)
        return False

    def _record_failure(
        self,
        state: cache.WeatherCacheState,
        error: Exception,
        refresh_id: str | None,
    ) -> None:
        state.error = (
            error.message
            if isinstance(error, AppError) and error.status == 400
            else "Wetterdaten konnten derzeit nicht aktualisiert werden."
        )
        failure = cache.failure_record(
            state.previous_failure_count,
            now=self._now(),
            base_seconds=self._retry_policy.retry_base_seconds,
            max_seconds=self._retry_policy.retry_max_seconds,
        )
        self._cache_store.store_failure(failure)
        self._refresh_journal.finish(refresh_id, "error", "failed", error=error)
        self._refresh_journal.log_failure(error)


class WeatherServiceCache:
    """Keep weather orchestration bound to the active database manager."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._manager: Any = None
        self._service: WeatherService | None = None

    def get(
        self,
        manager: Any,
        cache_store: WeatherCacheStore,
        client_factory: Callable[[], Any],
        refresh_journal: WeatherRefreshJournal,
        maintenance_gate: Any,
        now: Callable[[], datetime],
        today: Callable[[], date],
    ) -> WeatherService:
        with self._lock:
            if self._service is None or self._manager is not manager:
                self._service = WeatherService(
                    cache_store,
                    client_factory,
                    refresh_journal,
                    maintenance_gate,
                    now,
                    today,
                )
                self._manager = manager
            return self._service


WEATHER_SERVICE_CACHE = WeatherServiceCache()
