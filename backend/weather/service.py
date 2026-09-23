"""Stateful weather refresh and cache orchestration."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from backend.errors import AppError
from backend.weather import cache, history


class WeatherService:
    """Own weather refresh serialization and its durable cache state."""

    def __init__(
        self,
        database_manager: Any,
        key_values: Any,
        profile_service: Any,
        client_factory: Callable[[], Any],
        refresh_tracker: Any,
        maintenance_gate: Any,
        now: Callable[[], datetime],
        today: Callable[[], date],
        operation_context: Any,
        operation_id_factory: Callable[[], str],
        logger: Any,
        *,
        cache_seconds: int = 10800,
        retry_base_seconds: int = 900,
        retry_max_seconds: int = 21600,
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._profile_service = profile_service
        self._client_factory = client_factory
        self._refresh_tracker = refresh_tracker
        self._maintenance_gate = maintenance_gate
        self._now = now
        self._today = today
        self._operation_context = operation_context
        self._operation_id_factory = operation_id_factory
        self._logger = logger
        self._cache_seconds = cache_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
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
        with self._database_manager.unit_of_work() as db:
            query = (
                self._profile_service.get_from_db(db)
                .get("weather_location", "")
                .strip()[:200]
            )
            cached_value = self._key_values.get(db, cache.CACHE_KEY)
            failure_value = self._key_values.get(db, cache.FAILURE_KEY)
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
            cache_seconds=self._cache_seconds,
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
            force or not state.cache_matches or state.cache_age >= self._cache_seconds
        ):
            return False
        if cache.retry_wait(state.failure, now=self._now()) > 0 and not force:
            state.error = "Wetterdaten konnten nach einem Fehler noch nicht erneut geladen werden."
            return False

        refresh_id = self._start_refresh() if track_refresh else None
        try:
            with self._refresh_lock:
                refreshed_cache = self._client_factory().fetch(state.query)
                location_changed = self._store_refresh(state, refreshed_cache)
            if location_changed:
                if refresh_id:
                    self._refresh_tracker.finish(
                        refresh_id, "skipped", "location_changed"
                    )
                return True
            if refresh_id:
                self._refresh_tracker.finish(refresh_id, "success", "complete")
        except Exception as exc:  # noqa: BLE001 - provider boundary normalizes failures
            self._record_failure(state, exc, refresh_id)
        return False

    def _start_refresh(self) -> str:
        operation = self._operation_context.get() or {}
        return self._refresh_tracker.start(
            "weather",
            "forecast",
            operation.get("operation_id") or self._operation_id_factory(),
            operation.get("trigger") or "background",
        )

    def _store_refresh(
        self,
        state: cache.WeatherCacheState,
        refreshed_cache: dict[str, Any],
    ) -> bool:
        with self._database_manager.unit_of_work() as db:
            current_query = (
                self._profile_service.get_from_db(db)
                .get("weather_location", "")
                .strip()[:200]
            )
            if current_query != state.query:
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
        state.cached = refreshed_cache
        state.cache_matches = True
        state.refreshed = True
        state.error = None
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
            base_seconds=self._retry_base_seconds,
            max_seconds=self._retry_max_seconds,
        )
        with self._database_manager.unit_of_work() as db:
            self._key_values.set(
                db,
                cache.FAILURE_KEY,
                json.dumps(failure, ensure_ascii=False),
            )
        if refresh_id:
            self._refresh_tracker.finish(
                refresh_id,
                "error",
                "failed",
                error_code=self._refresh_tracker.error_code(error),
            )
        self._logger.warning(
            "Weather synchronization failed",
            extra={
                "event": "weather_sync_failed",
                "context": {"error_type": type(error).__name__},
            },
        )
