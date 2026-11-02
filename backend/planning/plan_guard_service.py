"""Server-side plan checks and the planning brief for Coach plan writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.errors import AppError
from backend.planning import plan_checks

BRIEF_WEEKS = 6
BRIEF_SPORTS = ("run", "ride", "strength")
BRIEF_COMPETITIONS = 3
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
    return result


def _competition_day(row: Mapping[str, Any]) -> str:
    day = plan_checks.competition_day(row)
    return "" if day is None else day.isoformat()


def build_planning_brief(
    *,
    progress: Mapping[str, Any],
    completed: Sequence[Mapping[str, Any]],
    competitions: Sequence[Mapping[str, Any]],
    training_model: str,
    today: date,
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
    ) -> None:
        self._planned_units = planned_units
        self._completed = completed_activities
        self._competitions = competitions
        self._illness = illness
        self._progress = progress
        self._training_model = training_model
        self._today = today

    def _recent(self, today: date) -> list[Mapping[str, Any]]:
        first = (today - timedelta(days=HISTORY_DAYS)).isoformat()
        return [
            row
            for row in self._completed()
            if iso_date_prefix(row.get("started_at_local")) >= first
        ]

    def findings(self) -> list[dict[str, Any]]:
        today = self._today()
        return plan_checks.check_plan(
            today=today,
            units=self._planned_units(),
            completed=self._recent(today),
            competitions=self._competitions(),
            illness=self._illness(),
        )

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
        return build_planning_brief(
            progress=self._progress(),
            completed=self._recent(today),
            competitions=self._competitions(),
            training_model=self._training_model(),
            today=today,
        )
