"""Read and persist the bounded external iCalendar feed."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import timedelta, timezone
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError, provider_error
from backend.providers import calendar as calendar_provider
from backend.runtime.events import StateEventBuffer
from backend.sync.daily import DailySyncMarkerService
from backend.sync.observation import SyncOperationObserver

EXTERNAL_CALENDAR_SYNC_LOCK = threading.Lock()


def shared_external_calendar_sync_lock() -> threading.Lock:
    """Return the process-wide lock used by the external-calendar sync."""
    return EXTERNAL_CALENDAR_SYNC_LOCK


class ExternalCalendarSyncService:
    """Own the read-only external-calendar synchronization lifecycle."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        daily_sync_marker_service: DailySyncMarkerService,
        observer: SyncOperationObserver,
        adaptive_replan_preview_service: Any,
        state_event_buffer: StateEventBuffer,
        logger: logging.Logger,
        redactor: Callable[[str], str],
        local_now: Callable[[], Any],
        utc_now: Callable[[], str],
        app_version: str,
        lock: Any | None = None,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._daily_sync_marker_service = daily_sync_marker_service
        self._observer = observer
        self._adaptive_replan_preview_service = adaptive_replan_preview_service
        self._state_event_buffer = state_event_buffer
        self._logger = logger
        self._redactor = redactor
        self._local_now = local_now
        self._utc_now = utc_now
        self._app_version = app_version
        self._lock = lock if lock is not None else EXTERNAL_CALENDAR_SYNC_LOCK

    def running(self) -> bool:
        return self._lock.locked()

    def sync(
        self, reason: str = "manual", operation_id: str | None = None
    ) -> dict[str, Any]:
        with self._observer.observe(
            "calendar", "events", reason, operation_id
        ) as scope:
            if not self._config.calendar_ical_url:
                raise AppError(503, "CALENDAR_ICAL_URL ist nicht konfiguriert.")
            if not self._lock.acquire(blocking=False):
                result = {"status": "already_running"}
                scope.result = result
                return result
            try:
                try:
                    result = self._sync_locked()
                except AppError as exc:
                    self._record_error(self._redactor(exc.message)[:1000])
                    self._logger.exception(
                        "External calendar synchronization failed",
                        extra={
                            "event": "external_calendar_sync_failed",
                            "context": {"reason": reason},
                        },
                        exc_info=True,  # noqa: G202 - retain the existing explicit traceback contract
                    )
                    raise
                except Exception as exc:
                    safe_error = provider_error("calendar", "client")
                    self._record_error(safe_error.message)
                    self._logger.exception(
                        "External calendar synchronization failed",
                        extra={
                            "event": "external_calendar_sync_failed",
                            "context": {
                                "reason": reason,
                                "error_type": type(exc).__name__,
                            },
                        },
                        exc_info=True,  # noqa: G202 - retain the existing explicit traceback contract
                    )
                    raise safe_error from exc
                scope.result = result
                return result
            finally:
                try:
                    self._set_value("external_calendar_sync_status", "")
                finally:
                    self._lock.release()

    def _sync_locked(self) -> dict[str, Any]:
        self._set_value(
            "external_calendar_sync_status", "Kalender: Synchronisierung läuft…"
        )
        url = calendar_provider.external_calendar_url(self._config.calendar_ical_url)
        payload = calendar_provider.fetch_calendar_feed(
            url, app_version=self._app_version
        )
        current_local = self._local_now()
        today = current_local.date()
        events = calendar_provider.parse_ical_calendar(
            payload,
            local_zone=current_local.tzinfo or timezone.utc,
            today=today,
            window_start=today,
            window_end=today
            + timedelta(days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS),
        )
        synced_at = self._utc_now()
        with self._database_manager.unit_of_work() as db:
            db.execute("DELETE FROM external_calendar_events")
            for event in events:
                db.execute(
                    "INSERT INTO external_calendar_events "
                    "(id, uid, name, event_date, start_local, end_local, "
                    "duration_minutes, all_day, training_relevant, no_intensity, "
                    "short_only, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event["id"],
                        event["uid"],
                        event["name"],
                        event["event_date"],
                        event["start_local"],
                        event["end_local"],
                        event["duration_minutes"],
                        int(event["all_day"]),
                        int(event.get("training_relevant", True)),
                        int(event.get("no_intensity", False)),
                        int(event.get("short_only", False)),
                        synced_at,
                    ),
                )

        self._set_value("last_external_calendar_sync_at", synced_at)
        self._daily_sync_marker_service.mark("calendar")
        self._set_value("last_external_calendar_sync_error", "")
        self._state_event_buffer.publish("coach", {"status": "changed"})
        replan = self._replan_projection("external calendar")
        return {
            "status": "ok",
            "synced_at": synced_at,
            "events": len(events),
            "window_days": calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
            **replan,
        }

    def _replan_projection(self, reason: str) -> dict[str, Any]:
        try:
            preview = self._adaptive_replan_preview_service.preview()
            changes = preview.get("changes", []) if isinstance(preview, dict) else []
            return {
                "needs_replan": bool(changes),
                "replan_changes": len(changes) if isinstance(changes, list) else 0,
            }
        except Exception:
            self._logger.warning(
                "Adaptive preview after provider sync failed",
                extra={
                    "event": "adaptive_replan_preview_failed",
                    "context": {"reason": reason},
                },
                exc_info=True,
            )
            return self._adaptive_replan_preview_service.status()

    def _set_value(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)

    def _record_error(self, message: str) -> None:
        self._set_value("last_external_calendar_sync_error", message)
