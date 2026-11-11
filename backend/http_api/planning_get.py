"""Authenticated public planning GET routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.library_page import LibraryPageService
from backend.http_api.public_plan import PublicPlanStateService
from backend.http_api.public_weather import PublicWeatherStateService
from backend.http_api.route_table import Access, Route, RouteRequest


class PlanningGetRoutes:
    """Dispatch planning reads through their existing state owners."""

    def __init__(
        self,
        public_plan_state_service: Callable[[], PublicPlanStateService],
        public_weather_state_service: Callable[[], PublicWeatherStateService],
        library_page_service: Callable[[], LibraryPageService],
    ) -> None:
        self._public_plan_state_service = public_plan_state_service
        self._public_weather_state_service = public_weather_state_service
        self._library_page_service = library_page_service

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/plan", Access.SESSION, self._plan),
            Route("GET", "/api/weather", Access.SESSION, self._weather),
            Route("GET", "/api/library", Access.SESSION, self._library),
        ]

    def _plan(self, handler: Any, request: RouteRequest) -> None:
        handler.send_json(
            200,
            self._public_plan_state_service().read_public(
                local_only=request.query.get("local", ["0"])[0] == "1"
            ),
        )

    def _weather(self, handler: Any, request: RouteRequest) -> None:
        handler.send_json(
            200,
            self._public_weather_state_service().state(
                local_only=request.query.get("local", ["0"])[0] == "1"
            ),
        )

    def _library(self, handler: Any, request: RouteRequest) -> None:
        query = request.query
        handler.send_json(
            200,
            self._library_page_service().page(
                query.get("cursor", [None])[0], query.get("limit", [None])[0]
            ),
        )
