"""Authenticated local settings PUT routes."""

from __future__ import annotations

from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.settings import SettingsService


class SettingsPutRoutes:
    """Dispatch local settings writes through the settings state owner."""

    def __init__(self, settings: SettingsService) -> None:
        self._settings = settings

    def routes(self) -> list[Route]:
        return [
            Route("PUT", "/api/settings/model", Access.SESSION_CSRF, self._model),
            Route(
                "PUT",
                "/api/settings/service-tier",
                Access.SESSION_CSRF,
                self._service_tier,
            ),
            Route(
                "PUT",
                "/api/settings/thinking-level",
                Access.SESSION_CSRF,
                self._thinking_level,
            ),
            Route(
                "PUT",
                "/api/settings/calendar-display",
                Access.SESSION_CSRF,
                self._calendar,
            ),
        ]

    def _model(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(
            200, self._settings.save_model(handler.read_json().get("model"))
        )

    def _service_tier(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(
            200,
            self._settings.save_service_tier(handler.read_json().get("service_tier")),
        )

    def _thinking_level(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(
            200,
            self._settings.save_thinking_level(
                handler.read_json().get("thinking_level")
            ),
        )

    def _calendar(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(
            200, self._settings.save_calendar_display_settings(handler.read_json())
        )
