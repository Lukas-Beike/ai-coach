"""Authenticated GET routes for athlete-facing read projections."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.athlete.profile import ProfileService
from backend.coach.context import CoachContextPreviewService
from backend.http_api.auth import SessionAuthService
from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.planning.competition_service import CompetitionService
from backend.settings import SettingsService

ZONES_PATH = "/api/zones"
_LOGGER = logging.getLogger("intervals_coach")


class AthleteGetRoutes:
    """Dispatch authenticated athlete reads through their state owners."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
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
        self._session_auth_service = session_auth_service
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

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {
            "/api/performance",
            "/api/profile",
            "/api/feedback",
            "/api/context-preview",
            ZONES_PATH,
        }:
            return False
        if path == ZONES_PATH and self._zone_service is None:
            return False

        self._session_auth_service().require_auth(handler)
        if path == "/api/performance":
            payload = self._public_performance_state_service().performance_state()
        elif path == "/api/profile":
            payload = {
                "profile": self._profile_service().get(),
                "competitions": self._competitions(),
            }
            if self._first_threshold_service is not None:
                payload["first_threshold_estimate"] = self._first_threshold_estimate(
                    self._first_threshold_service
                )
        elif path == "/api/feedback":
            payload = self._public_feedback_state_service().feedback_state()
        elif path == ZONES_PATH and self._zone_service is not None:
            payload = self._zone_service().read()
        else:
            payload = self._coach_context_preview_service().preview()

        handler.send_json(200, payload)
        return True
