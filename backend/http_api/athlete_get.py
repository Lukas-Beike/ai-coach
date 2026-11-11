"""Authenticated GET routes for athlete-facing read projections."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.athlete.profile import ProfileService
from backend.coach.context import CoachContextPreviewService
from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.planning.competition_service import CompetitionService
from backend.settings import SettingsService

ZONES_PATH = "/api/zones"
_LOGGER = logging.getLogger("intervals_coach")


class AthleteGetRoutes:
    """Dispatch authenticated athlete reads through their state owners."""

    def __init__(
        self,
        public_performance_state_service: Callable[[], PublicPerformanceStateService],
        profile_service: Callable[[], ProfileService],
        competition_service: Callable[[], CompetitionService],
        public_feedback_state_service: Callable[[], PublicFeedbackStateService],
        coach_context_preview_service: Callable[[], CoachContextPreviewService],
        settings_service: SettingsService,
        zone_service: Callable[[], Any] | None = None,
        race_results: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
        | None = None,
        first_threshold_service: Callable[[], Any] | None = None,
    ) -> None:
        self._first_threshold_service = first_threshold_service
        self._race_results = race_results
        self._public_performance_state_service = public_performance_state_service
        self._profile_service = profile_service
        self._competition_service = competition_service
        self._public_feedback_state_service = public_feedback_state_service
        self._coach_context_preview_service = coach_context_preview_service
        self._settings_service = settings_service
        self._zone_service = zone_service

    def _competitions(self) -> list[dict[str, Any]]:
        competitions = self._competition_service().list(limit=100)
        if self._race_results is None:
            return competitions
        try:
            return self._race_results(competitions)
        except Exception as exc:  # noqa: BLE001 - results are optional; never fail the profile
            _LOGGER.warning(
                "competition race results unavailable: %s", type(exc).__name__
            )
            return competitions

    @staticmethod
    def _first_threshold_estimate(
        service: Callable[[], Any],
    ) -> dict[str, Any] | None:
        try:
            return service().estimate()
        except Exception as exc:  # noqa: BLE001 - the estimate is optional; never fail the profile
            _LOGGER.warning(
                "first threshold estimate unavailable: %s", type(exc).__name__
            )
            return None

    def routes(self) -> list[Route]:
        routes = [
            Route("GET", "/api/performance", Access.SESSION, self._performance),
            Route("GET", "/api/profile", Access.SESSION, self._profile),
            Route("GET", "/api/feedback", Access.SESSION, self._feedback),
            Route("GET", "/api/context-preview", Access.SESSION, self._preview),
        ]
        if self._zone_service is not None:
            routes.append(Route("GET", ZONES_PATH, Access.SESSION, self._zones))
        return routes

    def _performance(self, handler: Any, _request: RouteRequest) -> None:
        """Performance projection."""
        handler.send_json(
            200, self._public_performance_state_service().performance_state()
        )

    def _profile(self, handler: Any, _request: RouteRequest) -> None:
        """Profile and competitions; also `first_threshold_estimate` (percent of the run threshold HR, bpm, session count, quality, date range) or null."""
        payload: dict[str, Any] = {
            "profile": self._profile_service().get(),
            "competitions": self._competitions(),
        }
        if self._first_threshold_service is not None:
            payload["first_threshold_estimate"] = self._first_threshold_estimate(
                self._first_threshold_service
            )
        handler.send_json(200, payload)

    def _feedback(self, handler: Any, _request: RouteRequest) -> None:
        """Activity feedback projection."""
        handler.send_json(200, self._public_feedback_state_service().feedback_state())

    def _zones(self, handler: Any, _request: RouteRequest) -> None:
        """Local and provider zone configurations."""
        if self._zone_service is not None:
            handler.send_json(200, self._zone_service().read())

    def _preview(self, handler: Any, _request: RouteRequest) -> None:
        """Preview of the context the Coach receives."""
        handler.send_json(200, self._coach_context_preview_service().preview())
