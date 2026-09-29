"""Composition for bounded Coach context and preview services."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from backend.coach.context import (
    CoachContextPreviewLimits,
    CoachContextPreviewService,
    CoachPerformanceContextReader,
    CoachPlanningContextReader,
    CoachStructuredContextService,
    CoachTrainingContextService,
)
from backend.coach.request_payload import CoachRequestPayloadService
from backend.settings import SettingsService


@dataclass(frozen=True)
class CoachContextPerformanceSources:
    sync_state_repository: Callable[[], Any]
    weather_service: Callable[[], Any]
    garmin_payload_service: Callable[[], Any]
    garmin_projection_service: Callable[[], Any]
    activity_feedback_service: Callable[[], Any]
    today: Callable[[], Any]
    local_date: Callable[[], Any]
    utc_now: Callable[[], datetime]


@dataclass(frozen=True)
class CoachContextPlanningSources:
    checkin_service: Callable[[], Any]
    planned_unit_service: Callable[[], Any]
    daily_context_service: Callable[[], Any]
    external_calendar_reader: Callable[[], Any]
    competition_service: Callable[[], Any]
    training_plan_service: Callable[[], Any]
    adaptive_preview_service: Callable[[], Any]
    workout_library_service: Callable[[], Any]


@dataclass(frozen=True)
class CoachContextDialogueSources:
    profile_service: Callable[[], Any]
    message_service: Callable[[], Any]
    settings: SettingsService
    limits: Callable[[], Mapping[str, Any]]
    default_max_output_tokens: Callable[[], int]


class CoachContextAssembly:
    """Create the fresh structured, prompt, request, and preview contexts."""

    @dataclass(frozen=True)
    class Inputs:
        performance: CoachContextPerformanceSources
        planning: CoachContextPlanningSources
        dialogue: CoachContextDialogueSources

    def __init__(self, *, dependencies: "CoachContextAssembly.Inputs") -> None:
        performance = dependencies.performance
        planning = dependencies.planning
        dialogue = dependencies.dialogue
        self._sync_state_repository = performance.sync_state_repository
        self._weather_service = performance.weather_service
        self._garmin_payload_service = performance.garmin_payload_service
        self._garmin_projection_service = performance.garmin_projection_service
        self._activity_feedback_service = performance.activity_feedback_service
        self._today = performance.today
        self._local_date = performance.local_date
        self._utc_now = performance.utc_now
        self._checkin_service = planning.checkin_service
        self._planned_unit_service = planning.planned_unit_service
        self._daily_context_service = planning.daily_context_service
        self._external_calendar_reader = planning.external_calendar_reader
        self._competition_service = planning.competition_service
        self._training_plan_service = planning.training_plan_service
        self._adaptive_preview_service = planning.adaptive_preview_service
        self._workout_library_service = planning.workout_library_service
        self._profile_service = dialogue.profile_service
        self._message_service = dialogue.message_service
        self._settings = dialogue.settings
        self._limits = dialogue.limits
        self._default_max_output_tokens = dialogue.default_max_output_tokens

    def structured_context_service(self) -> CoachStructuredContextService:
        return CoachStructuredContextService(
            self._sync_state_repository(),
            self._checkin_service(),
            self._weather_service(),
            self._activity_feedback_service(),
            CoachPlanningContextReader(
                self._planned_unit_service(),
                self._daily_context_service(),
                self._external_calendar_reader(),
                self._competition_service(),
                self._training_plan_service(),
                self._adaptive_preview_service(),
                self._today,
            ),
            CoachPerformanceContextReader(
                self._profile_service(),
                self._garmin_payload_service(),
                self._garmin_projection_service(),
                self._local_date,
            ),
        )

    def training_context_service(self) -> CoachTrainingContextService:
        limits = self._limits()
        return CoachTrainingContextService(
            self._sync_state_repository(),
            self.structured_context_service(),
            self._workout_library_service(),
            local_planned_limit=limits["local_planned_limit"],
            library_limit=limits["library_limit"],
            library_description_limit=limits["library_description_limit"],
            section_limits=limits["section_limits"],
            total_char_limit=limits["total_char_limit"],
            activity_limit_per_sport=limits["activity_limit_per_sport"],
            planned_event_limit=limits["planned_event_limit"],
        )

    def request_payload_service(self) -> CoachRequestPayloadService:
        return CoachRequestPayloadService(
            self.training_context_service(), self._settings, self._default_max_output_tokens()
        )

    def preview_service(self) -> CoachContextPreviewService:
        limits = self._limits()
        return CoachContextPreviewService(
            self._sync_state_repository(),
            self._message_service(),
            self.training_context_service(),
            self.structured_context_service(),
            self._workout_library_service(),
            CoachContextPreviewLimits(
                library_limit=limits["library_limit"],
                library_description_limit=limits["library_description_limit"],
                section_limits=limits["section_limits"],
                total_char_limit=limits["total_char_limit"],
                local_planned_limit=limits["local_planned_limit"],
                activity_limit_per_sport=limits["activity_limit_per_sport"],
                planned_event_limit=limits["planned_event_limit"],
            ),
            utc_now=self._utc_now,
        )
