"""Authenticated local settings PUT routes."""

from __future__ import annotations

from typing import Any

from backend.settings import SettingsService


class SettingsPutRoutes:
    """Dispatch local settings writes through the settings state owner."""

    def __init__(self, settings: SettingsService) -> None:
        self._settings = settings

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/settings/model":
            result = self._settings.save_model(handler.read_json().get("model"))
        elif path == "/api/settings/ai-provider":
            result = self._settings.save_ai_provider(handler.read_json().get("provider"))
        elif path == "/api/settings/thinking-level":
            result = self._settings.save_thinking_level(handler.read_json().get("thinking_level"))
        elif path == "/api/settings/calendar-display":
            result = self._settings.save_calendar_display_settings(handler.read_json())
        else:
            return False

        handler.send_json(200, result)
        return True
