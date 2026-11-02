"""Load-based plan notes for run and ride: session spike, weekly rise, unknown load.

Load = duration x intensity^2 (TSS principle), per sport:
- Planned unit: ``planned_unit_load.estimate_planned_unit`` (workout steps against
  the current thresholds).
- Completed activity: ride normalized power (else average power) over FTP; run
  weighted (grade-adjusted) pace, else average pace, over threshold pace; without
  both, a heart-rate fallback over LTHR that is marked less precise.
Thresholds come from the latest Intervals.icu sync and count only when it is at
most ``THRESHOLD_MAX_AGE_DAYS`` old. Anything missing or stale is unknown and
named as such; no number is made up. Strength has no planned session-RPE in
planned units, so it takes no part. The evidence is extrapolated from distance
and volume studies, not directly validated, and every note is non-blocking.

Functions return drafts ``(code, units, message, evidence)`` that
``plan_checks`` turns into findings.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.activities.workout_load import AthleteThresholds, WorkoutEstimate
from backend.activities.zone_settings import ZoneSettings
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import Environment, Sport
from backend.planning.planned_unit_load import (
    estimate_planned_unit,
    sport_threshold_speed,
)
from backend.planning.sport import planned_sport_environment

LOAD_EVIDENCE = "extrapolated from distance/volume studies, not directly validated"
THRESHOLD_MAX_AGE_DAYS = 30
SESSION_WINDOW_DAYS = 30
SPIKE_FACTOR = 1.10
SPIKE_WARNING_FACTOR = 1.30
WEEKLY_RISE_FACTOR = 1.20
BASELINE_WEEKS = 4
MIN_BASELINE_WEEKS = 3
HARD_ZONE = 4
HARD_STEP_SECONDS = 300
SEVERITY_CODES = frozenset({"run_spike", "load_spike", "weekly_load_rise"})
LOAD_SPORTS = frozenset({Sport.RUN, Sport.RIDE})

Draft = tuple[str, list[Mapping[str, Any]], str, dict[str, Any]]


@dataclass(frozen=True)
class LoadThresholds:
    """Per-sport thresholds; ``unavailable`` names why none may be used."""

    by_sport: Mapping[Sport, AthleteThresholds] = field(default_factory=dict)
    unavailable: str | None = None
    indoor_ride: AthleteThresholds | None = None

    def for_sport(
        self, sport: Sport, environment: Environment = Environment.UNKNOWN
    ) -> AthleteThresholds:
        """Thresholds of a sport; indoor and virtual rides use the indoor FTP."""
        indoor = environment in {Environment.INDOOR, Environment.VIRTUAL}
        if sport is Sport.RIDE and indoor and self.indoor_ride is not None:
            return self.indoor_ride
        return self.by_sport.get(sport, AthleteThresholds())


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


def _sport_thresholds(
    inputs: Any, sport: Sport, environment: Environment = Environment.UNKNOWN
) -> AthleteThresholds:
    zones = ZoneSettings.from_thresholds(inputs.zone_thresholds, sport, environment)
    speed = sport_threshold_speed(inputs.zone_thresholds, sport)
    return AthleteThresholds(zones=zones, threshold_speed_mps=speed)


def load_thresholds(inputs: Any, today: date) -> LoadThresholds:
    """Thresholds of the latest Intervals.icu sync, unusable when absent or stale."""
    synced = inputs.synced_at
    if synced is None:
        return LoadThresholds(unavailable="missing_thresholds")
    if (today - synced.date()).days > THRESHOLD_MAX_AGE_DAYS:
        return LoadThresholds(unavailable="stale_thresholds")
    return LoadThresholds(
        {sport: _sport_thresholds(inputs, sport) for sport in LOAD_SPORTS},
        indoor_ride=_sport_thresholds(inputs, Sport.RIDE, Environment.INDOOR),
    )


def _day(unit: Mapping[str, Any]) -> str:
    return iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")


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
                unit, thresholds.for_sport(sport, environment)
            )
            sessions.append(PlannedSession(unit, sport, _day(unit), estimate))
    return sessions


def computed_hard(estimate: WorkoutEstimate) -> bool | None:
    """Hard by computed zone; ``None`` when any step's intensity is unknown.

    Hard is at least five minutes in steps of zone 4 or higher (power, pace or
    heart-rate zones, like the Z4-Z7 text rule), so a hard interval set inside
    an easy session counts.
    """
    if not estimate.steps or estimate.intensity_factor is None:
        return None
    hard_s = sum(
        step.duration_s or 0.0
        for step in estimate.steps
        if (step.zone or 0) >= HARD_ZONE
    )
    return hard_s >= HARD_STEP_SECONDS


def _intensity_load(hours: float, intensity: float) -> float:
    return hours * intensity**2 * 100


def _ride_intensity(
    row: Mapping[str, Any], thresholds: AthleteThresholds
) -> tuple[float, str, bool] | None:
    ftp = thresholds.zones.ftp
    normalized = number(row.get("normalized_power"))
    power = normalized or number(row.get("avg_power"))
    if not (ftp and power):
        return None
    basis = "normalized_power_over_ftp" if normalized else "average_power_over_ftp"
    return power / ftp, basis, bool(normalized)


def _run_intensity(
    row: Mapping[str, Any], thresholds: AthleteThresholds
) -> tuple[float, str, bool] | None:
    reference = thresholds.threshold_speed_mps
    weighted = number(row.get("weighted_avg_speed_mps"))
    speed = weighted or number(row.get("avg_speed_mps"))
    if not (reference and speed):
        return None
    basis = (
        "grade_adjusted_pace_over_threshold_pace"
        if weighted
        else "average_pace_over_threshold_pace"
    )
    return speed / reference, basis, bool(weighted)


def _heart_rate_intensity(
    row: Mapping[str, Any], thresholds: AthleteThresholds
) -> tuple[float, str, bool] | None:
    heart_rate = number(row.get("avg_hr"))
    lthr = thresholds.zones.lthr
    if not (heart_rate and lthr):
        return None
    return heart_rate / lthr, "heart_rate_over_lthr_fallback", False


def completed_load(
    row: Mapping[str, Any], sport: Sport, thresholds: AthleteThresholds
) -> SessionLoad | None:
    """Load of a completed run or ride; ``None`` when no intensity is computable."""
    seconds = number(row.get("moving_duration_s")) or 0.0
    primary = _ride_intensity if sport is Sport.RIDE else _run_intensity
    found = primary(row, thresholds) or _heart_rate_intensity(row, thresholds)
    if seconds <= 0 or found is None:
        return None
    intensity, basis, precise = found
    return SessionLoad(_intensity_load(seconds / 3600, intensity), basis, precise)


def _environment(row: Mapping[str, Any]) -> Environment:
    try:
        return Environment(str(row.get("environment") or ""))
    except ValueError:
        return Environment.UNKNOWN


def _completed_loads(
    completed: Iterable[Mapping[str, Any]], thresholds: LoadThresholds
) -> list[tuple[Sport, str, SessionLoad | None]]:
    """Run and ride sessions with their load, ``None`` when it is not computable."""
    result = []
    for row in completed:
        sport = next((s for s in LOAD_SPORTS if s.value == row.get("sport")), None)
        if sport is not None:
            found = thresholds.for_sport(sport, _environment(row))
            day = iso_date_prefix(row.get("started_at_local"))
            result.append((sport, day, completed_load(row, sport, found)))
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
    thresholds: LoadThresholds,
    today: date,
) -> list[Draft]:
    """Planned load against the highest-load session of the sport in 30 days."""
    best: dict[Sport, SessionLoad] = {}
    for sport, day, load in _completed_loads(completed, thresholds):
        if (
            load
            and _in_window(day, today)
            and load.load > (best[sport].load if sport in best else 0.0)
        ):
            best[sport] = load
    drafts: list[Draft] = []
    for session in sessions:
        reference = best.get(session.sport)
        planned = session.estimate.load
        if planned is None or reference is None:
            continue
        severity = _grade(planned, reference.load)
        if severity is None:
            continue
        drafts.append(
            (
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
        )
    return drafts


def _monday(day: str) -> str:
    parsed = date.fromisoformat(day)
    return (parsed - timedelta(days=parsed.weekday())).isoformat()


def _weekly_totals(
    sessions: Sequence[PlannedSession],
    completed: Sequence[tuple[Sport, str, SessionLoad | None]],
    today: date,
) -> tuple[dict[tuple[Sport, str], float], set[tuple[Sport, str]]]:
    """Load per sport and ISO week, and the weeks missing a session's load.

    Completed sessions count before today, planned ones from today.
    """
    totals: dict[tuple[Sport, str], float] = defaultdict(float)
    partial: set[tuple[Sport, str]] = set()
    entries = [
        (sport, day, None if load is None else load.load)
        for sport, day, load in completed
        if day < today.isoformat()
    ] + [
        (item.sport, item.day, item.estimate.load)
        for item in sessions
        if item.day >= today.isoformat()
    ]
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
    thresholds: LoadThresholds,
    today: date,
) -> list[Draft]:
    """Planned weekly load per sport against the mean of the previous 3-4 weeks.

    Weeks without a record, or with a session whose load is unknown, are unknown
    and not rest, so they are left out of the mean; fewer than three known weeks
    give no note. A week of the sport with such a session is not judged either.
    """
    totals, partial = _weekly_totals(
        sessions, _completed_loads(completed, thresholds), today
    )
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
