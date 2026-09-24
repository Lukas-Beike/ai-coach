"""Authenticated GET routes for athlete-facing read projections."""

from __future__ import annotations

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
    ) -> None:
        self._session_auth_service = session_auth_service
        self._public_performance_state_service = public_performance_state_service
        self._profile_service = profile_service
        self._competition_service = competition_service
        self._public_feedback_state_service = public_feedback_state_service
        self._coach_context_preview_service = coach_context_preview_service
        self._settings_service = settings_service

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {
            "/api/performance",
            "/api/profile",
            "/api/feedback",
            "/api/context-preview",
        }:
            return False

        self._session_auth_service().require_auth(handler)
        if path == "/api/performance":
            payload = self._public_performance_state_service().performance_state()
        elif path == "/api/profile":
            payload = {
                "profile": self._profile_service().get(),
                "competitions": self._competition_service().list(limit=100),
            }
        elif path == "/api/feedback":
            payload = self._public_feedback_state_service().feedback_state()
        else:
            provider = self._settings_service.selected_ai_provider()
            payload = self._coach_context_preview_service().preview(provider)

        handler.send_json(200, payload)
        return True
