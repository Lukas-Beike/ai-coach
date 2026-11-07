"""Authenticated local settings PUT routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.settings import SettingsService
from backend.sync.intervals_ingest import INGEST_PROVIDER_ID


class SettingsPutRoutes:
    """Dispatch local settings writes through the settings state owner."""

    def __init__(
        self,
        settings: SettingsService,
        *,
        intervals_ingest: Callable[[], Any] | None = None,
        resume_provider_schedule: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._intervals_ingest = intervals_ingest
        self._resume_provider_schedule = resume_provider_schedule

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/settings/model":
            result = self._settings.save_model(handler.read_json().get("model"))
        elif path == "/api/settings/service-tier":
            result = self._settings.save_service_tier(
                handler.read_json().get("service_tier")
            )
        elif path == "/api/settings/thinking-level":
            result = self._settings.save_thinking_level(
                handler.read_json().get("thinking_level")
            )
        elif path == "/api/settings/calendar-display":
            result = self._settings.save_calendar_display_settings(handler.read_json())
        elif path == "/api/settings/activity-detail-floor":
            result = self._settings.save_activity_detail_prefetch_floor(
                handler.read_json()
            )
        elif (
            path == "/api/settings/intervals-ingest"
            and self._intervals_ingest is not None
        ):
            result = self._intervals_ingest().save(handler.read_json())
            if result.get("enabled") and self._resume_provider_schedule is not None:
                # Turning the ingest on restores the startup refresh and backfill.
                self._resume_provider_schedule(INGEST_PROVIDER_ID)
        else:
            return False

        handler.send_json(200, result)
        return True
