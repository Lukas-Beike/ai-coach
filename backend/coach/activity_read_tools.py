"""Read-only Coach tools for recent activities and activity details."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.activities.read_service import ActivityReadService
from backend.athlete.profile import ProfileService
from backend.coach.context import bounded_coach_context_value, coach_context_json_size
from backend.errors import AppError
from backend.sync.garmin import GarminPayloadService


class CoachActivityReadToolService:
    """Own Coach-specific validation and projections for activity read tools."""

    def __init__(
        self,
        activity_read: ActivityReadService,
        garmin_payload: GarminPayloadService,
        profile: ProfileService,
        today: Callable[[], date],
        report_service: Any = None,
    ) -> None:
        self._activity_read = activity_read
        self._garmin_payload = garmin_payload
        self._profile = profile
        self._today = today
        self._report_service = report_service

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        if name == "read_training_records":
            if self._report_service is None:
                raise AppError(503, "Trainingsprotokolle sind nicht verfügbar.")
            return {
                "ok": True,
                "records": bounded_coach_context_value(
                    self._report_service.training_records(arguments), 30000
                ),
                "scope": "Bounded projection of local equipment. Read exact current revisions before corrections.",
            }
        if name == "get_training_report":
            if self._report_service is None:
                raise AppError(503, "Trainingsberichte sind nicht verfügbar.")
            sections = arguments.get("sections", ["report"])
            allowed = {
                "report",
                "endurance",
                "power_profiles",
                "tag_impact",
                "season",
                "comparisons",
            }
            if (
                not isinstance(sections, list)
                or not 1 <= len(sections) <= 6
                or any(
                    not isinstance(section, str) or section not in allowed
                    for section in sections
                )
            ):
                raise AppError(400, "Unbekannter Analysebereich.")
            readers = {
                "report": lambda: self._report_service.read(arguments),
                "endurance": self._report_service.endurance,
                "power_profiles": self._report_service.power_profiles,
                "tag_impact": self._report_service.impact,
                "season": self._report_service.season,
                "comparisons": self._report_service.comparisons,
            }
            payload = {
                section: readers[section]() for section in dict.fromkeys(sections)
            }
            return {
                "ok": True,
                **bounded_coach_context_value(payload, 30000),
                "projection": {
                    "requested_sections": sections,
                    "complete": coach_context_json_size(payload) <= 30000,
                },
            }
        if name == "list_recent_activities":
            days = self._bounded_integer(
                arguments,
                "days",
                30,
                3660,
                "Aktivitätszeitraum oder Limit ist ungültig.",
            )
            limit = self._bounded_integer(
                arguments,
                "limit",
                100,
                500,
                "Aktivitätszeitraum oder Limit ist ungültig.",
            )
            return {
                "ok": True,
                **self._activity_read.recent(days, limit, today=self._today()),
            }
        if name == "get_activity_details":
            return self._activity_read.detail(
                arguments.get("activity_id"),
                garmin_snapshot=self._garmin_payload.snapshot(),
                profile=self._profile.get(),
                today=self._today(),
            )
        return None

    @staticmethod
    def _bounded_integer(
        arguments: dict[str, Any], key: str, default: int, maximum: int, error: str
    ) -> int:
        try:
            return max(1, min(int(arguments.get(key, default)), maximum))
        except (TypeError, ValueError) as exc:
            raise AppError(400, error, reason="invalid_list_request") from exc
