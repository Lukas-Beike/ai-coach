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
        """Planning projection.

        Request: query `local` (`1` skips the weather refresh and answers from
        stored data; any other value or none first refreshes the weather when it is stale).

        Response: 200 with `plans`, `planned`, `training_calendar`, `calendar`,
        `planning_view`, `planning_compliance`, `parallel_cycling`, `weather`,
        `external_calendar`, `daily_planning_context`, `planning` and
        `coach_quick_actions`, composed by `PublicPlanStateService.read_public`
        from one database snapshot.

        Errors: none beyond the common ones.
        """
        handler.send_json(
            200,
            self._public_plan_state_service().read_public(
                local_only=request.query.get("local", ["0"])[0] == "1"
            ),
        )

    def _weather(self, handler: Any, request: RouteRequest) -> None:
        """Weather projection.

        Request: query `local` (`1` answers from the stored forecast without
        contacting the weather provider; any other value or none refreshes it
        when it is stale).

        Response: 200 with `configured`, `state` (`not_configured`, `loading`,
        `ready`, `stale` or `error`), `provider`, `days` and `recommendations`;
        a ready or stale forecast adds `attribution`, `model`, `location`,
        `fetched_at`, and a stale one `stale` and `error`. Without a configured
        location it carries `message` instead; `error` and `loading` states
        carry `error` or `loading` and `message`.

        Errors: none beyond the common ones.
        """
        handler.send_json(
            200,
            self._public_weather_state_service().state(
                local_only=request.query.get("local", ["0"])[0] == "1"
            ),
        )

    def _library(self, handler: Any, request: RouteRequest) -> None:
        """Workout library page.

        Request: query `cursor` (opaque `next_cursor` of the previous page; an
        invalid cursor is ignored and starts at the first page) and `limit`
        (1 to 100, default 100; an unparsable value gives 100).

        Response: 200 with `workouts` (active, undated library templates ordered
        by sport, name and id, each with the derived `type` and, when Wahoo state
        exists, `wahoo_state`), `next_cursor` (null on the last page) and
        `limit` (the applied page size).

        Errors: none beyond the common ones.
        """
        query = request.query
        handler.send_json(
            200,
            self._library_page_service().page(
                query.get("cursor", [None])[0], query.get("limit", [None])[0]
            ),
        )
