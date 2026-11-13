"""Load-based plan notes for run and ride: session spike, weekly rise, unknown load.

Load = duration x intensity^2 (TSS principle), per sport:
- Planned unit: ``planned_unit_load.estimate_planned_unit`` (workout steps against
  the current thresholds).
- Completed activity: the stored local session load of card M6 (the same value
  the charts and the Coach context show); a heart-rate based value is marked less
  precise. A session without a stored value has an unknown load (#2082).
Thresholds of planned units follow the Coach precedence: locally confirmed zone configurations
first, then the source-policy provider winners (Garmin, Wahoo). Anything missing is
unknown and named as such; no number is made up. Strength has no planned session-RPE in
planned units, so it takes no part. The evidence is extrapolated from distance
and volume studies, not directly validated, and every note is non-blocking.

Functions return drafts ``(code, units, message, evidence)`` that
``plan_checks`` turns into findings.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.activities.workout_load import WorkoutEstimate, ZoneSettings
from backend.activities.zone_settings import effective_zone_configuration
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.vocabulary import (
    Environment,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
)
from backend.performance.local_tss import METHOD_ID as LOCAL_LOAD_METHOD_ID
from backend.performance.local_tss import PACE_BRANCH, POWER_BRANCH
from backend.planning.planned_unit_load import estimate_planned_unit, resolve_thresholds
from backend.planning.sport import planned_sport_environment

LOAD_EVIDENCE = "extrapolated from distance/volume studies, not directly validated"
SESSION_WINDOW_DAYS = 30
SPIKE_FACTOR = 1.10
SPIKE_WARNING_FACTOR = 1.30
WEEKLY_RISE_FACTOR = 1.20
BASELINE_WEEKS = 4
MIN_BASELINE_WEEKS = 3
SEVERITY_CODES = frozenset({"run_spike", "load_spike", "weekly_load_rise"})
LOAD_SPORTS = frozenset({Sport.RUN, Sport.RIDE})
# A stored M6 load from power or pace is precise; heart rate is less precise.
_PRECISE_BRANCHES = frozenset({POWER_BRANCH, PACE_BRANCH})

Draft = tuple[str, list[Mapping[str, Any]], str, dict[str, Any]]


@dataclass(frozen=True)
class LoadThresholds:
    """Thresholds of a sport on a day; ``unavailable`` names why none may be used."""

    unavailable: str | None = None
    resolver: Callable[[Sport, Environment, date | None], ZoneSettings] | None = None

    def for_sport(
        self,
        sport: Sport,
        environment: Environment = Environment.UNKNOWN,
        day: date | None = None,
    ) -> ZoneSettings:
        """Thresholds of a sport; indoor and virtual rides use the indoor FTP."""
        if self.resolver is None:
            return ZoneSettings()
        return self.resolver(sport, environment, day)


@dataclass(frozen=True)
class SessionLoad:
    load: float
    basis: str
    precise: bool


@dataclass(frozen=True)
class PlannedSession:
    unit: Mapping[str, Any]
    sport: Sport
    day: str
    estimate: WorkoutEstimate


def _has_configuration(
    configurations: Sequence[ZoneConfiguration], today: date
) -> bool:
    """Whether a configuration with a usable threshold applies to a load sport.

    A stored Intervals.icu configuration gives limits only, so it never counts,
    and neither does a provider configuration without a threshold.
    """
    usable = [
        item
        for item in configurations
        if item.provenance.provider is not ProviderId.INTERVALS
        and (item.provenance.provider is None or item.threshold)
    ]
    return any(
        effective_zone_configuration(usable, metric, sport, indoor=indoor, day=today)
        for sport in LOAD_SPORTS
        for metric in ZoneConfigurationMetric
        for indoor in (False, True)
    )


def load_thresholds(
    inputs: Any, today: date, configurations: Sequence[ZoneConfiguration] = ()
) -> LoadThresholds:
    """Thresholds with the Coach precedence: locally confirmed values, then providers.

    ``inputs.zone_thresholds`` are the source-policy provider winners (Garmin and
    Wahoo values within their own age limits); local values do not age. A stored
    Intervals.icu zone configuration gives its limits only, never a threshold, as
    in ``ZoneSettings``. Without any threshold the thresholds are unusable and named
    as missing.
    """
    observed = tuple(inputs.zone_thresholds)
    if not observed and not _has_configuration(configurations, today):
        return LoadThresholds(unavailable="missing_thresholds")

    def resolve(
        sport: Sport, environment: Environment, day: date | None
    ) -> ZoneSettings:
        return resolve_thresholds(
            observed, configurations, sport, environment, day or today
        )

    return LoadThresholds(resolver=resolve)


def _day(unit: Mapping[str, Any]) -> str:
    return iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")


def _unit_date(unit: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(_day(unit))
    except ValueError:
        return None


def plan_sessions(
    units: Iterable[Mapping[str, Any]], thresholds: LoadThresholds
) -> list[PlannedSession]:
    """Estimate every planned run and ride unit against the current thresholds."""
    sessions = []
    for unit in units:
        sport = planned_sport_environment(unit)[0]
        if sport in LOAD_SPORTS:
            environment = planned_sport_environment(unit)[1]
            estimate = estimate_planned_unit(
                unit, thresholds.for_sport(sport, environment, _unit_date(unit))
            )
            sessions.append(PlannedSession(unit, sport, _day(unit), estimate))
    return sessions


def completed_load(row: Mapping[str, Any]) -> SessionLoad | None:
    """The stored M6 load of a completed session; ``None`` when it has none."""
    load = row.get("training_load")
    if row.get("load_method") != LOCAL_LOAD_METHOD_ID or not isinstance(
        load, int | float
    ):
        return None
    branch = str(row.get("load_branch") or "")
    return SessionLoad(float(load), branch, branch in _PRECISE_BRANCHES)


def _completed_loads(
    completed: Iterable[Mapping[str, Any]],
) -> list[tuple[Sport, str, SessionLoad | None]]:
    """Run and ride sessions with their load, ``None`` when it is not known."""
    result = []
    for row in completed:
        sport = next((s for s in LOAD_SPORTS if s.value == row.get("sport")), None)
        if sport is not None:
            day = iso_date_prefix(row.get("started_at_local"))
            result.append((sport, day, completed_load(row)))
    return result


def _grade(planned: float, reference: float) -> str | None:
    if planned > reference * SPIKE_WARNING_FACTOR:
        return "warning"
    return "notice" if planned > reference * SPIKE_FACTOR else None


def _in_window(day: str, today: date) -> bool:
    first = (today - timedelta(days=SESSION_WINDOW_DAYS)).isoformat()
    return first <= day <= today.isoformat()


def session_spikes(
    sessions: Sequence[PlannedSession],
    completed: Iterable[Mapping[str, Any]],
    today: date,
) -> list[Draft]:
    """Planned load against the highest-load session of the sport in 30 days."""
    best: dict[Sport, SessionLoad] = {}
    for sport, day, load in _completed_loads(completed):
        if load and _in_window(day, today) and load.load > _load_of(best.get(sport)):
            best[sport] = load
    drafts: list[Draft] = []
    for session in sessions:
        draft = _spike_draft(session, best.get(session.sport))
        if draft is not None:
            drafts.append(draft)
    return drafts


def _load_of(session: SessionLoad | None) -> float:
    return 0.0 if session is None else session.load


def _spike_draft(
    session: PlannedSession, reference: SessionLoad | None
) -> Draft | None:
    planned = session.estimate.load
    if planned is None or reference is None:
        return None
    severity = _grade(planned, reference.load)
    if severity is None:
        return None
    return (
        "load_spike",
        [session.unit],
        f"Planned {session.sport.value} load is "
        + ("more than 30 % above" if severity == "warning" else "10-30 % above")
        + " the highest-load session of the last 30 days.",
        {
            "severity": severity,
            "sport": session.sport.value,
            "planned_load": round(planned),
            "highest_load_30d": round(reference.load),
            "increase_percent": round((planned / reference.load - 1) * 100),
            "planned_basis": session.estimate.load_basis,
            "reference_basis": reference.basis,
            "precision": "precise" if reference.precise else "less_precise",
        },
    )


def _monday(day: str) -> str:
    parsed = date.fromisoformat(day)
    return (parsed - timedelta(days=parsed.weekday())).isoformat()


def _weekly_totals(
    sessions: Sequence[PlannedSession],
    completed: Sequence[tuple[Sport, str, SessionLoad | None]],
    today: date,
) -> tuple[dict[tuple[Sport, str], float], set[tuple[Sport, str]]]:
    """Load per sport and ISO week, and the weeks missing a session's load.

    Completed sessions count up to today, planned ones from today. For a sport
    already done today, each of today's completed sessions replaces one planned unit.
    """
    totals: dict[tuple[Sport, str], float] = defaultdict(float)
    partial: set[tuple[Sport, str]] = set()
    now = today.isoformat()
    # One completed session of today replaces one planned unit of its sport,
    # so a second planned session of the day stays (as ``without_done_today``).
    done_today = Counter(sport for sport, day, _load in completed if day == now)
    planned = []
    for item in sessions:
        if item.day == now and done_today[item.sport] > 0:
            done_today[item.sport] -= 1
        elif item.day >= now:
            planned.append((item.sport, item.day, item.estimate.load))
    entries = [
        (sport, day, None if load is None else load.load)
        for sport, day, load in completed
        if day <= now
    ] + planned
    for sport, day, load in entries:
        key = (sport, _monday(day))
        if load is None:
            partial.add(key)
        else:
            totals[key] += load
    return totals, partial


def _baseline(
    totals: Mapping[tuple[Sport, str], float],
    partial: set[tuple[Sport, str]],
    sport: Sport,
    week: str,
) -> tuple[float, int] | None:
    first = date.fromisoformat(week)
    keys = [
        (sport, (first - timedelta(weeks=n)).isoformat())
        for n in range(1, BASELINE_WEEKS + 1)
    ]
    known = [totals[key] for key in keys if key not in partial and totals.get(key)]
    if len(known) < MIN_BASELINE_WEEKS:
        return None
    return sum(known) / len(known), len(known)


def weekly_rises(
    sessions: Sequence[PlannedSession],
    completed: Iterable[Mapping[str, Any]],
    today: date,
) -> list[Draft]:
    """Planned weekly load per sport against the mean of the previous 3-4 weeks.

    Weeks without a record, or with a session whose load is unknown, are unknown
    and not rest, so they are left out of the mean; fewer than three known weeks
    give no note. A week of the sport with such a session is not judged either.
    """
    totals, partial = _weekly_totals(sessions, _completed_loads(completed), today)
    groups: dict[tuple[Sport, str], list[PlannedSession]] = defaultdict(list)
    for session in sessions:
        if session.day >= today.isoformat():
            groups[session.sport, _monday(session.day)].append(session)
    drafts: list[Draft] = []
    for (sport, week), group in sorted(
        groups.items(), key=lambda item: (item[0][1], item[0][0].value)
    ):
        baseline = _baseline(totals, partial, sport, week)
        planned = totals.get((sport, week), 0.0)
        if (
            baseline is None
            or (sport, week) in partial
            or planned <= baseline[0] * WEEKLY_RISE_FACTOR
        ):
            continue
        drafts.append(
            (
                "weekly_load_rise",
                [item.unit for item in group],
                f"Planned {sport.value} load of the week rises more than 20 % above the mean of the previous weeks.",
                {
                    "severity": "notice",
                    "sport": sport.value,
                    "week_start": week,
                    "planned_week_load": round(planned),
                    "baseline_mean_load": round(baseline[0]),
                    "baseline_weeks": baseline[1],
                    "increase_percent": round((planned / baseline[0] - 1) * 100),
                },
            )
        )
    return drafts


def unknown_load(
    sessions: Sequence[PlannedSession], thresholds: LoadThresholds
) -> list[Draft]:
    """One note naming the planned sessions whose load cannot be computed."""
    unknown = [
        item
        for item in sessions
        if item.estimate.load is None or thresholds.unavailable
    ]
    if not unknown:
        return []
    reasons = (
        {thresholds.unavailable}
        if thresholds.unavailable
        else {reason for item in unknown for reason in item.estimate.unknown}
    )
    return [
        (
            "load_unknown",
            [item.unit for item in unknown],
            "Load of planned run/ride sessions is unknown; no load comparison was made for them.",
            {
                "severity": "notice",
                "sessions": len(unknown),
                "reasons": sorted(str(reason) for reason in reasons),
            },
        )
    ]


def run_distance_spikes(
    sessions: Sequence[PlannedSession],
    completed: Iterable[Mapping[str, Any]],
    today: date,
) -> list[Draft]:
    """Planned run distance against the longest run of the last 30 days.

    Frandsen et al. 2025 measured single-session distance, so this stays apart
    from the load notes.
    """
    longest = max(
        (
            number(row.get("distance_m")) or 0.0
            for row in completed
            if row.get("sport") == Sport.RUN.value
            and _in_window(iso_date_prefix(row.get("started_at_local")), today)
        ),
        default=0.0,
    )
    drafts: list[Draft] = []
    for session in sessions:
        planned = session.estimate.distance_m
        if session.sport is not Sport.RUN or not planned or longest <= 0:
            continue
        severity = _grade(planned, longest)
        if severity is None:
            continue
        drafts.append(
            (
                "run_spike",
                [session.unit],
                "Planned run is more than 30 % longer than the longest run of the last 30 days."
                if severity == "warning"
                else "Planned run is 10-30 % longer than the longest run of the last 30 days.",
                {
                    "severity": severity,
                    "planned_km": round(planned / 1000, 1),
                    "longest_run_30d_km": round(longest / 1000, 1),
                    "increase_percent": round((planned / longest - 1) * 100),
                },
            )
        )
    return drafts
