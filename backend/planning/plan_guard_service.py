"""Server-side plan checks and the planning brief for Coach plan writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import Sport
from backend.errors import AppError
from backend.performance.canonical_current import read_current_inputs
from backend.performance.canonical_inputs import resolve_reader
from backend.planning import intensity_distribution, leg_strength, plan_checks
from backend.planning.load_checks import LoadThresholds, load_thresholds
from backend.planning.session_focus import session_focus
from backend.planning.sport import planned_sport_environment

BRIEF_WEEKS = 6
BRIEF_SPORTS = ("run", "ride", "strength")
BRIEF_COMPETITIONS = 3
BRIEF_FOCUS_DAYS = 14
BRIEF_FOCUS_UNITS = 40
HISTORY_DAYS = 60
BRIEF_SOURCE = (
    "Local activity records (weekly-progress-v1), local planning and "
    "confirmed profile; derived, not provider-measured"
)


class PlanCheckError(AppError):
    """A proposed plan breaks a blocking check; carries the findings for the model."""

    def __init__(self, findings: list[dict[str, Any]]) -> None:
        codes = ", ".join(sorted({item["code"] for item in findings}))
        super().__init__(
            409,
            f"Nicht gespeichert: Der Plan verletzt Planungsregeln ({codes}).",
            reason="plan_check_failed",
        )
        self.findings = findings


def read_completed(database_manager: Any, activities: Any, today: date) -> Any:
    """Activity summaries of the 60-day check window, in the caller's transaction."""
    with database_manager.reader() as db:
        return activities.activity_summaries(db, start=today - timedelta(days=60))


def read_load_thresholds(
    database_manager: Any, observations: Any, today: date
) -> LoadThresholds:
    """Thresholds of the latest Intervals.icu sync, read with a short reader."""
    with database_manager.reader() as db:
        current = read_current_inputs(resolve_reader(observations, db), db, as_of=today)
    return load_thresholds(current, today)


def read_progress(reports: Any) -> Mapping[str, Any]:
    """The 42-day weekly progress projection (six ISO weeks, all sports).

    The brief never uses mean-max curves, so they are not read.
    """
    return reports.report.progress({"days": 42}, reports.timezone(), with_curves=False)


def recent_illness(checkins: Sequence[Mapping[str, Any]], today: date) -> str:
    """Illness text of the newest check-in of today or the last two days."""
    first = (today - timedelta(days=2)).isoformat()
    latest = max(
        (row for row in checkins if str(row.get("checkin_date") or "") >= first),
        key=lambda row: str(row["checkin_date"]),
        default=None,
    )
    return str((latest or {}).get("illness") or "")


def _hard_completed(row: Mapping[str, Any]) -> bool:
    factor = plan_checks.intensity_factor({"planned_intensity": row.get("intensity")})
    return factor is not None and factor >= plan_checks.HARD_INTENSITY


def _hard_count(
    completed: Sequence[Mapping[str, Any]], sport: str, first: str, last: str
) -> int:
    return sum(
        1
        for row in completed
        if row.get("sport") == sport
        and first <= iso_date_prefix(row.get("started_at_local")) <= last
        and _hard_completed(row)
    )


def _brief_week(
    week: Mapping[str, Any], completed: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "week_start": week.get("week_start"),
        "status": week.get("status"),
    }
    sports = week.get("sports") or {}
    for sport in BRIEF_SPORTS:
        bucket = sports.get(sport)
        if not bucket:
            continue
        result[sport] = {
            "sessions": bucket["sessions"],
            "duration_s": bucket["duration_s"]["value"],
            "training_load": bucket["training_load"]["value"],
            "hard_sessions": _hard_count(
                completed, sport, str(week["week_start"]), str(week["week_end"])
            ),
            "intensity_3zone_s": bucket["intensity_3zone"]["seconds"],
        }
    if "strength" in result:
        counts = leg_strength.completed_counts(
            completed, str(week["week_start"]), str(week["week_end"])
        )
        result["strength"].update(
            {key: counts[key] for key in counts if key != "sessions"}
        )
    return result


def _competition_day(row: Mapping[str, Any]) -> str:
    day = plan_checks.competition_day(row)
    return "" if day is None else day.isoformat()


def planned_focus(
    units: Sequence[Mapping[str, Any]],
    estimate: intensity_distribution.Estimator,
    today: date,
) -> list[dict[str, Any]]:
    """Session focus of the next planned units; ``derived`` marks a guess."""
    last = (today + timedelta(days=BRIEF_FOCUS_DAYS)).isoformat()
    rows = []
    for unit in sorted(units, key=_unit_day):
        day = _unit_day(unit)
        if not today.isoformat() <= day <= last:
            continue
        focus = session_focus(unit, _focus_estimate(unit, estimate))
        rows.append(
            {
                "local_id": unit.get("local_id") or unit.get("id"),
                "date": day,
                "sport": planned_sport_environment(unit)[0].value,
                **focus.as_dict(),
            }
        )
    return rows[:BRIEF_FOCUS_UNITS]


def _unit_day(unit: Mapping[str, Any]) -> str:
    return iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")


def _focus_estimate(
    unit: Mapping[str, Any], estimate: intensity_distribution.Estimator
) -> Any:
    """Workout estimate for the focus fallback; run and ride units only."""
    if planned_sport_environment(unit)[0] not in {Sport.RUN, Sport.RIDE}:
        return None
    return estimate(unit)


def build_planning_brief(
    *,
    progress: Mapping[str, Any],
    completed: Sequence[Mapping[str, Any]],
    competitions: Sequence[Mapping[str, Any]],
    training_model: str,
    today: date,
    planned_weeks: Sequence[Mapping[str, Any]] = (),
    planned_sessions: Sequence[Mapping[str, Any]] = (),
    planned_strength: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Compact deterministic brief for plan_week and plan_block turns."""
    weeks = [
        item for item in progress.get("week_list", []) if item.get("status") != "future"
    ][-BRIEF_WEEKS:]
    longest = plan_checks.longest_completed_run_s(completed, today)
    upcoming = sorted(
        (row for row in competitions if _competition_day(row) >= today.isoformat()),
        key=_competition_day,
    )[:BRIEF_COMPETITIONS]
    return {
        "source": BRIEF_SOURCE,
        "training_model": training_model,
        "weeks": [_brief_week(week, completed) for week in weeks],
        "weeks_note": "Weeks without records are unknown, not rest; the running week is incomplete.",
        "longest_run_30d_minutes": None if longest is None else round(longest / 60),
        "next_competitions": [
            {
                "date": _competition_day(row),
                "name": str(row.get("name") or "")[:120],
                "priority": row.get("priority"),
                "sport": row.get("sport"),
            }
            for row in upcoming
        ],
        "planned_distribution": intensity_distribution.brief_distribution(
            training_model, planned_weeks, BRIEF_WEEKS
        ),
        "strength": leg_strength.brief_strength(planned_strength, BRIEF_WEEKS),
        "planned_sessions": list(planned_sessions),
        "plan_checks": plan_checks.RULE_SUMMARY,
    }


class PlanGuardService:
    """Read the plan inputs and run the checks inside the caller's transaction."""

    def __init__(
        self,
        *,
        planned_units: Callable[[], list[dict[str, Any]]],
        completed_activities: Callable[[], Sequence[Mapping[str, Any]]],
        competitions: Callable[[], list[dict[str, Any]]],
        illness: Callable[[], str],
        progress: Callable[[], Mapping[str, Any]],
        training_model: Callable[[], str],
        today: Callable[[], date],
        estimate_unit: intensity_distribution.Estimator,
        thresholds: Callable[[], LoadThresholds | None] = lambda: None,
        expects_strength: Callable[[], bool] = lambda: False,
    ) -> None:
        self._planned_units = planned_units
        self._completed = completed_activities
        self._competitions = competitions
        self._illness = illness
        self._progress = progress
        self._training_model = training_model
        self._today = today
        self._estimate_unit = estimate_unit
        self._thresholds = thresholds
        self._expects_strength = expects_strength
        self._threshold_cache: tuple[LoadThresholds | None] | None = None

    def _planned_weeks(
        self, units: Sequence[Mapping[str, Any]], today: date
    ) -> list[dict]:
        return intensity_distribution.planned_weeks(units, self._estimate_unit, today)

    def _recent(self, today: date) -> list[Mapping[str, Any]]:
        first = (today - timedelta(days=HISTORY_DAYS)).isoformat()
        return [
            row
            for row in self._completed()
            if iso_date_prefix(row.get("started_at_local")) >= first
        ]

    def findings(self) -> list[dict[str, Any]]:
        today = self._today()
        units = self._planned_units()
        return [
            *plan_checks.check_plan(
                today=today,
                units=units,
                completed=self._recent(today),
                competitions=self._competitions(),
                illness=self._illness(),
                thresholds=self._load_thresholds(),
                expects_strength=self._expects_strength(),
            ),
            *intensity_distribution.distribution_findings(
                self._training_model(), self._planned_weeks(units, today)
            ),
        ]

    def _load_thresholds(self) -> LoadThresholds | None:
        """One snapshot per service, so before and after a write compare alike."""
        if self._threshold_cache is None:
            self._threshold_cache = (self._thresholds(),)
        return self._threshold_cache[0]

    def verify(
        self, before: Sequence[Mapping[str, Any]], accepted: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Raise on new blocking findings that are not accepted; return the notes.

        Notes are the new non-blocking findings plus accepted blocking ones; the
        Coach names and justifies them in its answer.
        """
        new = plan_checks.new_findings(before, self.findings())
        blocking = [
            item
            for item in new
            if item["code"] in plan_checks.BLOCKING_CODES
            and item["code"] not in accepted
        ]
        if blocking:
            raise PlanCheckError(blocking)
        return [
            {
                key: item[key]
                for key in (
                    "code",
                    "blocking",
                    "dates",
                    "message",
                    "evidence_strength",
                    "evidence",
                )
            }
            for item in new
        ]

    def brief(self) -> dict[str, Any]:
        today = self._today()
        units = self._planned_units()
        return build_planning_brief(
            progress=self._progress(),
            completed=self._recent(today),
            competitions=self._competitions(),
            training_model=self._training_model(),
            today=today,
            planned_weeks=self._planned_weeks(units, today),
            planned_sessions=planned_focus(units, self._estimate_unit, today),
            planned_strength=leg_strength.planned_weeks(units, today),
        )
