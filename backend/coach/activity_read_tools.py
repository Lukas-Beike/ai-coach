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
        report_services: Any = None,
    ) -> None:
        self._activity_read = activity_read
        self._garmin_payload = garmin_payload
        self._profile = profile
        self._today = today
        self._report_services = report_services

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        if name == "read_training_records":
            if self._report_services is None:
                raise AppError(503, "Trainingsprotokolle sind nicht verfügbar.")
            return {
                "ok": True,
                "records": bounded_coach_context_value(
                    self._report_services.records.training_records(arguments), 30000
                ),
                "scope": "Bounded projection of local equipment. Read exact current revisions before corrections.",
            }
        if name == "get_training_report":
            if self._report_services is None:
                raise AppError(503, "Trainingsberichte sind nicht verfügbar.")
            sections = arguments.get("sections", ["report"])
            allowed = {
                "report",
                "endurance",
                "power_profiles",
                "tag_impact",
                "season",
                "comparisons",
                "body_history",
                "sleep_regularity",
            }
            if (
                not isinstance(sections, list)
                or not 1 <= len(sections) <= 8
                or any(
                    not isinstance(section, str) or section not in allowed
                    for section in sections
                )
            ):
                raise AppError(400, "Unbekannter Analysebereich.")
            readers = {
                "report": lambda: self._report_services.report.read(
                    arguments, self._report_services.timezone()
                ),
                "endurance": self._report_services.records.endurance,
                "power_profiles": lambda: self._report_services.profiles.power_profiles(
                    self._report_services.records.observations()
                ),
                "tag_impact": lambda: self._report_services.derived.impact(
                    self._report_services.timezone()
                ),
                "season": lambda: self._report_services.season.season(
                    self._report_services.timezone()
                ),
                "comparisons": self._report_services.records.comparisons,
                "body_history": self._report_services.derived.body_history,
                "sleep_regularity": self._report_services.derived.sleep_regularity,
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
