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
        """Performance projection.

        Request: no query, no body.

        Response: 200 with `performance` (the current performance context, with
        `history` (with `first_thresholds`, the LT1 chart history) and
        `training_focus_periods` added; built by
        `PublicPerformanceStateService.performance_state`) and `garmin` (the public
        Garmin projection).

        Errors: none beyond the common ones.
        """
        handler.send_json(
            200,
            self._public_performance_state_service().performance_state(
                first_thresholds=True
            ),
        )

    def _profile(self, handler: Any, _request: RouteRequest) -> None:
        """Profile, competitions and the first threshold estimate.

        Request: no query, no body.

        Response: 200 with `profile` (every profile field as a string),
        `competitions` (up to 100; a past competition carries `result` when a
        session is linked to it) and `first_threshold_estimate`: `percent_lthr`,
        `bpm`, `sessions`, `quality`, `from`, `to`, `spread_pct`, `source`, or null
        without an estimate or when computing it fails.

        Errors: none beyond the common ones.
        """
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
        """Activity feedback projection.

        Request: no query, no body.

        Response: 200 with `checkins` (the latest 30 check-ins), `local_feedback`
        (the check-in context) and `activity_feedback` (the activity feedback
        context).

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._public_feedback_state_service().feedback_state())

    def _zones(self, handler: Any, _request: RouteRequest) -> None:
        """Local and provider zone configurations.

        Request: no query, no body.

        Response: 200 with `sports` (`ride`, `run`, `swim`), `today` (athlete-local
        date), `configurations` (each with `key`, `source` `local` or the provider,
        `label`, `sport`, `metric`, `environment`, `valid_from`, `valid_until`,
        `threshold`, `maximum`, `limits`, `percent_limits`, `percent_basis`),
        `effective` (per sport, metric and environment the configuration in effect
        today: `sport`, `metric`, `environment`, `key`) and, only when there is one,
        `threshold_warnings`.

        Errors: none beyond the common ones.
        """
        if self._zone_service is not None:
            handler.send_json(200, self._zone_service().read())

    def _preview(self, handler: Any, _request: RouteRequest) -> None:
        """Preview of the context the Coach receives.

        Request: no query, no body.

        Response: 200 with `generated_at`, `snapshot_truncated`,
        `snapshot_compacted`, `assembly`, `conversation`, `chat_prompt`,
        `structured_athlete_context`, `latest_activities`, `projection`,
        `context_text` and `local_training_library` (built by
        `CoachContextPreviewService.preview`). It changes no state.

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._coach_context_preview_service().preview())
