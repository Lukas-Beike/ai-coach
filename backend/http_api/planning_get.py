"""Authenticated public planning GET routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.http_api.auth import SessionAuthService
from backend.http_api.library_page import LibraryPageService
from backend.http_api.public_plan import PublicPlanStateService
from backend.http_api.public_weather import PublicWeatherStateService


class PlanningGetRoutes:
    """Dispatch planning reads through their existing state owners."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        public_plan_state_service: Callable[[], PublicPlanStateService],
        public_weather_state_service: Callable[[], PublicWeatherStateService],
        library_page_service: Callable[[], LibraryPageService],
    ) -> None:
        self._session_auth_service = session_auth_service
        self._public_plan_state_service = public_plan_state_service
        self._public_weather_state_service = public_weather_state_service
        self._library_page_service = library_page_service

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {"/api/plan", "/api/weather", "/api/library"}:
            return False

        self._session_auth_service().require_auth(handler)
        query = parse_qs(urlparse(handler.path).query)
        if path == "/api/plan":
            payload = self._public_plan_state_service().read(
                local_only=query.get("local", ["0"])[0] == "1"
            )
        elif path == "/api/weather":
            payload = self._public_weather_state_service().state(
                local_only=query.get("local", ["0"])[0] == "1"
            )
        else:
            payload = self._library_page_service().page(
                query.get("cursor", [None])[0], query.get("limit", [None])[0]
            )

        handler.send_json(200, payload)
        return True
