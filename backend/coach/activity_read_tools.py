"""Read-only Coach tools for recent activities and activity details."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.athlete.profile import ProfileService
from backend.coach.context import (
    bounded_coach_context_value,
    coach_context_json_size,
    coach_sleep_timing_projection,
)
from backend.errors import AppError
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.sync.garmin import GarminPayloadService


class CoachActivityReadToolService:
    """Own Coach-specific validation and projections for activity read tools."""

    def __init__(
        self,
        activity_read: ActivityAnalysisReadService,
        garmin_payload: GarminPayloadService,
        profile: ProfileService,
        today: Callable[[], date],
        report_services: Any = None,
        planned_units: Any = None,
    ) -> None:
        self._activity_read = activity_read
        self._garmin_payload = garmin_payload
        self._profile = profile
        self._today = today
        self._report_services = report_services
        self._planned_units = planned_units

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
            sections = _report_sections(arguments)
            readers = {
                "progress": lambda: self._report_services.report.progress(
                    arguments, self._report_services.timezone()
                ),
                "block_review": lambda: self._report_services.report.block_review(
                    arguments, self._report_services.timezone()
                ),
                "report": lambda: self._report_services.report.read(
                    arguments, self._report_services.timezone()
                ),
                "endurance": self._report_services.records.endurance,
                "power_profiles": self._report_services.profiles.power_profiles,
                "tag_impact": lambda: self._report_services.derived.impact(
                    self._report_services.timezone()
                ),
                "season": lambda: self._report_services.season.season(
                    self._report_services.timezone()
                ),
                "comparisons": self._report_services.records.comparisons,
                "body_history": self._report_services.derived.body_history,
                # The Coach context's summary plus each series' last 14 nights.
                "sleep_timing_variability": lambda: coach_sleep_timing_projection(
                    self._report_services.derived.sleep_timing_variability(),
                    recent_nights=True,
                ),
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
            detail = self._activity_read.detail(
                arguments.get("activity_id"),
                garmin_status=self._garmin_payload.sync_status(),
                profile=self._profile.get(),
                today=self._today(),
            )
            return {**detail, "planned_units": self._planned_around(detail)}
        return None

    def _planned_around(self, detail: dict[str, Any]) -> Any:
        """Local planned units one day around the analysed session's date.

        The context window is anchored on today, so an older session would lose its
        plan; the unit comes with the session instead.
        """
        session = detail.get("session")
        if self._planned_units is None or not isinstance(session, dict):
            return None
        try:
            day = date.fromisoformat(iso_date_prefix(session.get("started_at_local")))
        except ValueError:
            return None
        first, last = day - timedelta(days=1), day + timedelta(days=1)
        units = self._planned_units.list(250, future_only=True, since=first)
        window = (first.isoformat(), last.isoformat())
        around = [
            unit
            for unit in units
            if window[0] <= iso_date_prefix(unit.get("date")) <= window[1]
        ]
        return bounded_coach_context_value(around[:10], 4000)

    @staticmethod
    def _bounded_integer(
        arguments: dict[str, Any], key: str, default: int, maximum: int, error: str
    ) -> int:
        try:
            return max(1, min(int(arguments.get(key, default)), maximum))
        except (TypeError, ValueError) as exc:
            raise AppError(400, error, reason="invalid_list_request") from exc


def _report_sections(arguments: dict[str, Any]) -> list[str]:
    """Validated report sections; progress and its long windows stand alone."""
    days = arguments.get("days")
    long_window = isinstance(days, int) and days in {42, 84}
    sections = arguments.get("sections", ["progress"] if long_window else ["report"])
    allowed = {
        "progress",
        "block_review",
        "report",
        "endurance",
        "power_profiles",
        "tag_impact",
        "season",
        "comparisons",
        "body_history",
        "sleep_timing_variability",
    }
    if (
        not isinstance(sections, list)
        or not 1 <= len(sections) <= 10
        or any(
            not isinstance(section, str) or section not in allowed
            for section in sections
        )
    ):
        raise AppError(400, "Unbekannter Analysebereich.")
    # progress uses whole ISO weeks, so it never shares a call with
    # sections that read the requested window as given.
    alone = sections in (["progress"], ["block_review"])
    if (long_window or {"progress", "block_review"} & set(sections)) and not alone:
        raise AppError(
            400, "progress, block_review und 42 oder 84 Tage nur allein abrufbar."
        )
    return sections
