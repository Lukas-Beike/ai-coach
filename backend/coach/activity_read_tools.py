"""Read-only Coach tools for recent activities and activity details."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Final

from backend.activities.workout_text import WorkoutTextError, structured_steps
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.profile import ProfileService
from backend.canonical.activity_summary import (
    stored_activity_key,
    summary_is_electric,
)
from backend.coach.context import (
    bounded_coach_context_value,
    coach_context_json_size,
    coach_sleep_timing_projection,
)
from backend.coach.session_checks import matched_focus
from backend.errors import AppError
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.comparable_sessions import comparable_sessions
from backend.performance.pace_at_hr import COMPARE_DAYS, session_comparison
from backend.performance.planned_targets import planned_target_execution
from backend.performance.report_service import PROFILE_WINDOW_DAYS
from backend.planning import leg_strength
from backend.planning.sport import planned_sport_environment
from backend.sync.garmin import GarminPayloadService

# Per-field source labels and zone-time arrays stay in get_activity_details;
# the list keeps each session's scalar values and its primary source label.
_LIST_OMITTED_KEYS: Final = frozenset(
    {"sources", "power_zone_times", "heart_rate_zone_times", "pace_zone_times"}
)


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
        unit_thresholds: Any = None,
        session_corrections: Any = None,
    ) -> None:
        self._activity_read = activity_read
        self._garmin_payload = garmin_payload
        self._profile = profile
        self._today = today
        self._report_services = report_services
        self._planned_units = planned_units
        self._unit_thresholds = unit_thresholds
        self._session_corrections = session_corrections

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
            recent = self._activity_read.recent(days, limit, today=self._today())
            return {
                "ok": True,
                **recent,
                "activities": [
                    {
                        key: value
                        for key, value in activity.items()
                        if key not in _LIST_OMITTED_KEYS
                    }
                    for activity in recent["activities"]
                ],
            }
        if name == "get_activity_details":
            detail = self._activity_read.detail(
                arguments.get("activity_id"),
                garmin_status=self._garmin_payload.sync_status(),
                profile=self._profile.get(),
                today=self._today(),
            )
            result = self._with_session_context(detail)
            session = detail.get("session")
            if self._session_corrections is not None and isinstance(session, dict):
                # Local session IDs and merge candidates for the session tools.
                result["session_bundle"] = self._session_corrections.bundle(
                    session.get("activity_id")
                )
            return result
        return None

    def _session_day(self, detail: dict[str, Any]) -> date | None:
        session = detail.get("session")
        if not isinstance(session, dict):
            return None
        try:
            return date.fromisoformat(iso_date_prefix(session.get("started_at_local")))
        except ValueError:
            return None

    def _units_since(self, day: date | None) -> list[dict[str, Any]] | None:
        """Local planned units from two days before the session's date on."""
        if self._planned_units is None or day is None:
            return None
        return self._planned_units.list(
            250, future_only=True, since=day - timedelta(days=2)
        )

    @staticmethod
    def _units_around(
        units: list[dict[str, Any]] | None, day: date | None
    ) -> list[dict[str, Any]] | None:
        """Units one day around the session's date.

        The context window is anchored on today, so an older session would lose its
        plan; the unit comes with the session instead.
        """
        if units is None or day is None:
            return None
        first, last = day - timedelta(days=1), day + timedelta(days=1)
        return [
            unit
            for unit in units
            if first.isoformat()
            <= iso_date_prefix(unit.get("date"))
            <= last.isoformat()
        ]

    def _with_session_context(self, detail: dict[str, Any]) -> dict[str, Any]:
        """The detail with its planned units and the session checks.

        Focus, pace at heart rate and leg strength before a run or ride come
        with the tool result, not the base context.
        """
        day = self._session_day(detail)
        units = self._units_since(day)
        around = self._units_around(units, day)
        result = {
            **detail,
            "planned_units": None
            if around is None
            else bounded_coach_context_value(around[:10], 4000),
        }
        session = detail.get("session")
        if isinstance(session, dict) and day is not None:
            result.update(self._session_checks(session, day, around, units))
            targets = self._planned_targets(
                detail, session, result.get("focus"), around
            )
            if targets is not None:
                result["planned_targets"] = targets
        return result

    def _session_checks(
        self,
        session: dict[str, Any],
        day: date,
        around: list[dict[str, Any]] | None,
        units: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        checks: dict[str, Any] = {"focus": matched_focus(session, around)}
        if session.get("sport") not in ("run", "ride"):
            return checks
        nearby = self._activity_read.summaries_between(
            day - timedelta(days=3), day + timedelta(days=1)
        )
        checks["strength_before"] = self._strength_before(session, nearby, units)
        own = next(
            (
                row
                for row in nearby or ()
                if row.get("id") == session.get("activity_id")
            ),
            None,
        )
        covered_from = self._covered_from()
        # A session before the curve window has no curve; nothing is read for it.
        inside = own is not None and day >= covered_from
        records = self._curve_records() if inside else None
        if session.get("sport") == "run":
            checks["pace_at_heart_rate"] = self._pace_at_heart_rate(own, records, day)
        if own is None or (inside and records is None):
            checks["comparable_sessions"] = _unavailable()
        elif summary_is_electric(own):
            # Curve records leave e-bike sessions out; say why, not "no streams".
            checks["comparable_sessions"] = {
                "status": "not_covered",
                "reason": "E-Bike-Einheiten werden nicht verglichen (Motorunterstützung).",
            }
        elif records is None:
            checks["comparable_sessions"] = {
                "status": "not_covered",
                "reason": f"Die Einheit liegt außerhalb des Auswertungsfensters von {PROFILE_WINDOW_DAYS[-1]} Tagen.",
            }
        else:
            checks["comparable_sessions"] = comparable_sessions(
                records, stored_activity_key(own), covered_from=covered_from
            )
        return checks

    def _covered_from(self) -> date:
        """First day of the curve window that the session comparisons read."""
        return self._today() - timedelta(days=PROFILE_WINDOW_DAYS[-1] - 1)

    def _curve_records(self) -> list[dict[str, Any]] | None:
        """Sessions of the curve window with their curves and executions, read once."""
        if self._report_services is None:
            return None
        try:
            return self._report_services.profiles.curve_records()
        except RuntimeError:
            return None

    def _planned_targets(
        self,
        detail: dict[str, Any],
        session: dict[str, Any],
        focus: Any,
        around: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        """Work laps against the matched planned unit's steps, for runs and rides."""
        if session.get("sport") not in ("run", "ride") or self._unit_thresholds is None:
            return None
        unit = _matched_unit(session, focus, around)
        unit_id = None if unit is None else unit.get("id")
        analysis = detail.get("analysis")
        execution = analysis.get("execution") if isinstance(analysis, dict) else None
        if unit is None or not isinstance(execution, dict):
            return None
        description = unit.get("description")
        if not isinstance(description, str) or len(description) > 20000:
            return None
        try:
            steps = structured_steps(description, str(unit.get("target") or "AUTO"))
        except WorkoutTextError as error:
            return {
                "status": "not_covered",
                "planned_unit_id": unit_id,
                "reason": error.reason,
            }
        return planned_target_execution(
            execution,
            steps,
            self._unit_thresholds.thresholds(unit),
            str(session.get("sport")),
            planned_unit_id=str(unit_id),
            streams=detail.get("streams"),
        )

    @staticmethod
    def _strength_before(
        session: dict[str, Any], nearby: Any, units: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        try:
            start = datetime.fromisoformat(str(session.get("started_at_local")))
        except ValueError:
            return {"status": "not_covered", "reason": "Startzeit unbekannt."}
        return leg_strength.strength_before(start, nearby, lambda: units)

    def _pace_at_heart_rate(
        self,
        own: Mapping[str, Any] | None,
        records: list[dict[str, Any]] | None,
        day: date,
    ) -> dict[str, Any]:
        if (
            own is not None
            and day - timedelta(days=COMPARE_DAYS) < self._covered_from()
        ):
            return {
                "status": "not_covered",
                "reason": f"Die Läufe der letzten {COMPARE_DAYS} Tage vor dieser Aktivität liegen außerhalb des Auswertungsfensters von {PROFILE_WINDOW_DAYS[-1]} Tagen.",
            }
        if own is None or records is None:
            return _unavailable()
        return session_comparison(records, stored_activity_key(own))

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
    long_window = isinstance(days, int) and days in {42, 56, 84}
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
            400, "progress, block_review und 42, 56 oder 84 Tage nur allein abrufbar."
        )
    return sections


def _matched_unit(
    session: Mapping[str, Any], focus: Any, around: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """The focus's planned unit, else the one unit of the session's day and sport.

    A unit without a session focus still has steps to compare, so the same
    unique day-and-sport rule as the focus applies without needing a focus.
    """
    units = around or []
    unit_id = focus.get("planned_unit_id") if isinstance(focus, dict) else None
    if unit_id:
        return next((unit for unit in units if unit.get("id") == unit_id), None)
    day = iso_date_prefix(session.get("started_at_local"))
    same = [
        unit
        for unit in units
        if iso_date_prefix(unit.get("date")) == day
        and planned_sport_environment(unit)[0].value == session.get("sport")
    ]
    return same[0] if len(same) == 1 else None


def _unavailable() -> dict[str, Any]:
    return {
        "status": "not_covered",
        "reason": "Auswertung der Messreihen nicht verfügbar.",
    }
