"""Observed weather refresh orchestration."""

from __future__ import annotations

import logging
from typing import Any

from backend.errors import AppError
from backend.sync.observation import SyncOperationObserver


class WeatherSyncService:
    """Refresh weather state and update the adaptive planning preview."""

    def __init__(
        self,
        profile_service: Any,
        weather_service: Any,
        adaptive_preview_service: Any,
        observer: SyncOperationObserver,
        logger: logging.Logger,
    ) -> None:
        self._profile_service = profile_service
        self._weather_service = weather_service
        self._adaptive_preview_service = adaptive_preview_service
        self._observer = observer
        self._logger = logger

    def sync(
        self,
        reason: str = "background",
        force: bool = False,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        with self._observer.observe(
            "weather", "forecast", reason, operation_id
        ) as scope:
            result = self._sync_inner(reason, force)
            scope.result = result
            return result

    def _sync_inner(self, reason: str, force: bool) -> dict[str, Any]:
        if not self._profile_service.get().get("weather_location", "").strip():
            return {"status": "not_configured"}
        weather = self._weather_service.state(
            refresh=True,
            force=force,
            track_refresh=False,
        )
        if weather.get("error") and not weather.get("days"):
            raise AppError(502, str(weather["error"]))
        replan = (
            self._refresh_adaptive_preview()
            if weather.get("_refreshed")
            else self._adaptive_preview_service.status()
        )
        return {
            "status": "stale" if weather.get("stale") else "ok",
            "reason": reason,
            "fetched_at": weather.get("fetched_at"),
            **replan,
        }

    def _refresh_adaptive_preview(self) -> dict[str, Any]:
        try:
            preview = self._adaptive_preview_service.preview()
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
                    "context": {"reason": "weather"},
                },
                exc_info=True,
            )
            return self._adaptive_preview_service.status()
