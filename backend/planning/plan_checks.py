"""Pure checks of a proposed future plan against five training-science rules.

The Coach tool write runs these on the resulting plan. Only illness_hard stops
the write until the model corrects the plan or names the accepted deviation;
the other findings are saved and returned as notes. No I/O.

Rules (references are observational or practice-based, not individual advice):
- run_spike: a planned run is more than 10 % longer (distance) than the longest
  completed run of the last 30 days (Frandsen et al. 2025, BJSM). The planned
  distance comes from the workout steps; unknown distance or no run in 30 days:
  no finding.
- load_spike, weekly_load_rise, load_unknown: load = duration x intensity^2 per
  sport (``load_checks``). A planned run or ride more than 10 % (warning: 30 %)
  above the highest-load session of its sport in 30 days; a planned weekly load
  more than 20 % above the mean of the previous 3-4 weeks; load that cannot be
  computed (missing or stale thresholds, unparsed steps) is named, not guessed.
  Only with thresholds passed to ``check_plan``.
- back_to_back_hard: hard run/ride sessions on consecutive days. Hard means a
  set session focus (threshold, sweet_spot, vo2max, anaerobic, race, test), else a
  computed workout zone (at least five minutes in zone 4+ steps,
  ``load_checks.computed_hard``), else a planned intensity key of at least 0.85 (percent values above 1.5 are
  divided by 100) or workout text with a Z4-Z7 / zone 4-7 target, else a keyword-derived hard focus. Unknown is not
  hard.
- strength_hard_same_day: heavy strength (set or structure-derived strength_intensity, else planned intensity >= 0.85 or text
  naming heavy, schwer, maximal or a 1-6 RM) and a hard run/ride on one date
  with less than 6 h between start times, or an unknown start time
  (Robineau et al. 2016).
- missing_taper: a priority A/B competition whose final 14 days carry less
  than 20 % less duration than the 14 days before them (completed activities
  before today, planned units from today). Only judged when the plan reaches
  into the final 14 days (Bosquet et al. 2007: cut volume 40-60 %).
- intensity_distribution: computed in ``intensity_distribution`` and added by
  the plan guard, not by ``check_plan``; see that module.
- leg_strength_before_key_session, leg_strength_frequency: counted and graded in
  ``leg_strength`` (number and intensity of leg sessions only); see that module.
- illness_hard: the latest check-in reports illness and a hard session or a
  session of 90 minutes or more is planned within the next 3 days. During the
  stepwise return after an approved pause (``illness_return``) it also flags a
  session above the current stage's level (stage 1 easy, stage 2 up to moderate)
  today and tomorrow.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.athlete.checkins import reports_complaint
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.planning_fields import HR_CAP, STRENGTH_STRUCTURE
from backend.canonical.vocabulary import Sport
from backend.errors import AppError
from backend.planning import (
    calendar,
    calendar_load,
    illness_return,
    leg_strength,
    load_checks,
    run_hr_cap,
    strength_structure,
)
from backend.planning.local_start import known_start
from backend.planning.session_focus import (
    FOCUS_KEY,
    INTENSITY_KEY,
    allowed_foci,
    session_focus,
)
from backend.planning.sport import planned_sport_environment

ALL_DAY_EVENT = "all_day_event"
FINDING_CODES = (
    "run_spike",
    "load_spike",
    "weekly_load_rise",
    "load_unknown",
    "back_to_back_hard",
    "strength_hard_same_day",
    "missing_taper",
    "illness_hard",
    "strength_incomplete",
    "focus_missing",
    "hr_cap_invalid",
    "intensity_distribution",
    leg_strength.BEFORE_KEY,
    leg_strength.FREQUENCY,
    "calendar_load",
    ALL_DAY_EVENT,
)
# Only the health rule blocks a write. The load rules are notes the Coach must
# name: their evidence is observational or practice-based, or (taper) the
# evidence is strong but the 20 % floor is a local choice, not a proven limit.
BLOCKING_CODES = ("illness_hard",)
# Data the Coach must write, not a training rule: a strength unit it creates,
# moves or changes needs its structure, focus and intensity, any other unit with
# a focus vocabulary (run, ride) its focus, and a capped run unit its heart-rate
# cap. It blocks like the health rule but can never be accepted, so it is not in
# BLOCKING_CODES.
REQUIRED_CODES = ("strength_incomplete", "focus_missing", "hr_cap_invalid")
EVIDENCE = {
    "run_spike": "observational, moderate (Frandsen 2025)",
    "load_spike": load_checks.LOAD_EVIDENCE,
    "weekly_load_rise": load_checks.LOAD_EVIDENCE,
    "load_unknown": load_checks.LOAD_EVIDENCE,
    "back_to_back_hard": "practice-based (hard/easy principle)",
    "strength_hard_same_day": "limited, performance studies (Robineau 2016)",
    "missing_taper": "meta-analysis, strong (Bosquet 2007); 20 % floor is a local choice",
    "illness_hard": "medical caution",
    "strength_incomplete": "data completeness for the watch and the plan checks",
    "focus_missing": "data completeness for the plan checks and the calendar",
    "hr_cap_invalid": "data completeness for the watch and the analysis; the caps are the athlete's decision",
    "intensity_distribution": "practice-based reference ranges; pyramidal/polarized after Seiler 2010, Stoeggl & Sperlich 2014",
    leg_strength.BEFORE_KEY: "limited, residual fatigue after lower-body resistance training (Doma et al.)",
    leg_strength.FREQUENCY: "Ronnestad & Mujika 2014, Blagrove 2018 (2x/week build, 1x/week maintenance); thresholds practice-based",
    "calendar_load": "calendar overlap and locally chosen eight-hour busy-day threshold",
    ALL_DAY_EVENT: "calendar all-day event; soft context, not a block",
}
_RULE_TEXT = {
    "run_spike": "planned run more than 10 % (warning above 30 %) longer than the longest run of the last 30 days.",
    "load_spike": "planned run or ride load more than 10 % (warning above 30 %) above the highest-load session of its sport in 30 days.",
    "weekly_load_rise": "planned weekly run or ride load more than 20 % above the mean of the previous 3-4 weeks.",
    "load_unknown": "load of a planned run or ride cannot be computed (missing or stale thresholds or steps).",
    "back_to_back_hard": "hard run or ride on consecutive days.",
    "strength_hard_same_day": "heavy strength and a hard run or ride less than 6 h apart.",
    "missing_taper": "final 14 days before an A/B competition less than 20 % lighter than the 14 days before.",
    "illness_hard": "hard or 90+ minute session within 5 days of a reported illness (today included), or a session above the current stage of the return after an illness pause (today and tomorrow).",
    "strength_incomplete": "a strength unit the Coach created, moved or changed without strength_structure, session_focus and strength_intensity.",
    "focus_missing": "a run or ride unit the Coach created, moved or changed without session_focus.",
    "hr_cap_invalid": "a recovery, easy or long run unit the Coach created or changed without a heart-rate cap (percentages and source) within the effective cap.",
    "intensity_distribution": "planned low/moderate/high time of a week clearly outside the training model's reference range (unknown time is uncovered, strength excluded).",
    leg_strength.BEFORE_KEY: "moderate or heavy leg strength less than about 24 h before a hard run or ride or the week's long one.",
    leg_strength.FREQUENCY: "more than 3 leg strength sessions or more than 2 heavy ones in a week, or none in a plan of 2+ weeks when strength is expected.",
    "calendar_load": "long or hard unit overlaps a calendar event or falls on a day with at least eight hours of events.",
    ALL_DAY_EVENT: "a hard or long unit on a day with an all-day calendar event (soft note; calendar markers still apply).",
}
RULE_SUMMARY = {
    code: f"{'Blocks' if code in (*BLOCKING_CODES, *REQUIRED_CODES) else 'Note'}: {text}"
    for code, text in _RULE_TEXT.items()
}
HARD_INTENSITY = 0.85
MIN_STRENGTH_GAP_H = 6
TAPER_DAYS = 14
TAPER_MIN_REDUCTION = 0.20
# Days of caution after a reported illness, today included; the approved pause
# forecast shares it (today .. today + ILLNESS_DAYS - 1).
ILLNESS_DAYS = 5
LONG_SESSION_S = 5400
RUN_WINDOW_DAYS = 30
# Key check_plan sets on a unit copy whose steps give a computed intensity.
COMPUTED_HARD = "_computed_hard"
_ENDURANCE = frozenset({Sport.RUN, Sport.RIDE})
# A Z4+ target counts unless a negation such as "unter Z4" or "kein Z5" precedes it.
_HARD_ZONE = re.compile(
    r"(?<!unter )(?<!kein )(?<!keine )(?<!nicht )(?<!below )(?<!under )(?<!no )"
    r"\b(?:z|zone\s*)[4-7]\b",
    re.IGNORECASE,
)
# "maximal" is left out: in German it mostly means "at most".
_HEAVY = re.compile(r"\b(?:heavy|schwer|[1-6]\s*rm)\b", re.IGNORECASE)


def intensity_factor(unit: Mapping[str, Any]) -> float | None:
    return leg_strength.planned_intensity_factor(unit)


def _text(unit: Mapping[str, Any]) -> str:
    return f"{unit.get('name') or ''} {unit.get('description') or ''}"


def _sport(unit: Mapping[str, Any]) -> Sport:
    return planned_sport_environment(unit)[0]


def _day(unit: Mapping[str, Any]) -> str:
    return iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")


def _duration_s(unit: Mapping[str, Any]) -> float:
    seconds = number(unit.get("planned_duration_s"))
    if seconds is None:
        minutes = number(unit.get("duration_minutes"))
        seconds = None if minutes is None else minutes * 60
    return seconds or 0.0


def is_hard(unit: Mapping[str, Any]) -> bool:
    """Whether a planned run or ride is hard: computed intensity, else key or text."""
    if _sport(unit) not in _ENDURANCE:
        return False
    focus = session_focus(unit)
    if focus.origin == "set":
        return bool(focus.is_hard)
    computed = unit.get(COMPUTED_HARD)
    if isinstance(computed, bool):
        return computed
    factor = intensity_factor(unit)
    return (
        (factor is not None and factor >= HARD_INTENSITY)
        or bool(_HARD_ZONE.search(_text(unit)))
        or bool(focus.is_hard)
    )


def is_heavy_strength(unit: Mapping[str, Any]) -> bool:
    if _sport(unit) is not Sport.STRENGTH:
        return False
    focus = session_focus(unit)
    if focus.strength_intensity is not None:
        return focus.strength_intensity == "heavy"
    factor = intensity_factor(unit)
    return (factor is not None and factor >= HARD_INTENSITY) or bool(
        _HEAVY.search(_text(unit))
    )


def _finding(
    code: str,
    units: Sequence[Mapping[str, Any]],
    message: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "code": code,
        "blocking": code in BLOCKING_CODES or code in REQUIRED_CODES,
        "evidence_strength": EVIDENCE[code],
        "dates": sorted({_day(unit) for unit in units}),
        "local_ids": sorted(
            str(unit.get("local_id") or unit.get("id"))
            for unit in units
            if unit.get("local_id") or unit.get("id")
        ),
        "message": message,
        "evidence": dict(evidence),
    }


def longest_completed_run_s(
    completed: Iterable[Mapping[str, Any]], today: date
) -> float | None:
    """Longest moving duration of a completed run in the last 30 days."""
    first = (today - timedelta(days=RUN_WINDOW_DAYS)).isoformat()
    durations = [
        number(row.get("moving_duration_s")) or 0.0
        for row in completed
        if row.get("sport") == Sport.RUN.value
        # A run completed earlier today already counts.
        and first <= iso_date_prefix(row.get("started_at_local")) <= today.isoformat()
    ]
    longest = max(durations, default=0.0)
    return longest or None


def _back_to_back(units: Sequence[Mapping[str, Any]]) -> list[dict]:
    by_day: dict[str, list[Mapping[str, Any]]] = {}
    for unit in units:
        if is_hard(unit):
            by_day.setdefault(_day(unit), []).append(unit)
    findings = []
    for day in sorted(by_day):
        following = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        if following in by_day:
            findings.append(
                _finding(
                    "back_to_back_hard",
                    [*by_day[day], *by_day[following]],
                    "Hard sessions on consecutive days.",
                    {"days": [day, following]},
                )
            )
    return findings


def _gap_too_short(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    start_a, start_b = known_start(first), known_start(second)
    if start_a is None or start_b is None:
        return True
    return abs(start_a - start_b) < timedelta(hours=MIN_STRENGTH_GAP_H)


def _strength_same_day(units: Sequence[Mapping[str, Any]]) -> list[dict]:
    findings = []
    heavy = [unit for unit in units if is_heavy_strength(unit)]
    hard = [unit for unit in units if is_hard(unit)]
    for strength in heavy:
        close = [
            unit
            for unit in hard
            if _day(unit) == _day(strength) and _gap_too_short(strength, unit)
        ]
        if close:
            findings.append(
                _finding(
                    "strength_hard_same_day",
                    [strength, *close],
                    "Heavy strength and a hard session on one day less than 6 h apart or without start times.",
                    {"day": _day(strength), "min_gap_hours": MIN_STRENGTH_GAP_H},
                )
            )
    return findings


def _window_seconds(
    start: date,
    end: date,
    units: Sequence[Mapping[str, Any]],
    completed: Iterable[Mapping[str, Any]],
    today: date,
) -> float:
    """Duration in [start, end]: completed before today, planned from today."""
    first, last = start.isoformat(), end.isoformat()
    done = sum(
        number(row.get("moving_duration_s")) or 0.0
        for row in completed
        if first <= iso_date_prefix(row.get("started_at_local")) <= last
        and iso_date_prefix(row.get("started_at_local")) < today.isoformat()
    )
    planned = sum(
        _duration_s(unit)
        for unit in units
        if first <= _day(unit) <= last and _day(unit) >= today.isoformat()
    )
    return done + planned


def competition_day(row: Mapping[str, Any]) -> date | None:
    """Day of a stored competition (event_date, else its local start)."""
    raw = row.get("event_date") or row.get("starts_at_local") or row.get("date")
    try:
        return date.fromisoformat(iso_date_prefix(raw))
    except ValueError:
        return None


def _taper_for(
    day: date,
    units: Sequence[Mapping[str, Any]],
    completed: Sequence[Mapping[str, Any]],
    today: date,
) -> dict[str, Any] | None:
    final_start = day - timedelta(days=TAPER_DAYS)
    reaching = [unit for unit in units if final_start.isoformat() <= _day(unit)]
    if not reaching:
        return None
    before_start = final_start - timedelta(days=TAPER_DAYS)
    previous = _window_seconds(
        before_start, final_start - timedelta(days=1), units, completed, today
    )
    final = _window_seconds(
        final_start, day - timedelta(days=1), units, completed, today
    )
    if previous <= 0 or final <= previous * (1 - TAPER_MIN_REDUCTION):
        return None
    return _finding(
        "missing_taper",
        [unit for unit in reaching if _day(unit) < day.isoformat()],
        "The final 14 days before the competition are not at least 20 % lighter than the 14 days before.",
        {
            "competition_date": day.isoformat(),
            "previous_14d_minutes": round(previous / 60),
            "final_14d_minutes": round(final / 60),
        },
    )


def _missing_taper(
    units: Sequence[Mapping[str, Any]],
    completed: Sequence[Mapping[str, Any]],
    competitions: Iterable[Mapping[str, Any]],
    today: date,
) -> list[dict]:
    findings = []
    for row in competitions:
        day = competition_day(row)
        if day is None or day < today or str(row.get("priority") or "B") == "C":
            continue
        finding = _taper_for(day, units, completed, today)
        if finding is not None:
            findings.append(finding)
    return findings


def _illness_hard(
    units: Sequence[Mapping[str, Any]], illness: str, today: date
) -> list[dict]:
    if not reports_complaint(illness):
        return []
    last = (today + timedelta(days=ILLNESS_DAYS - 1)).isoformat()
    # One finding per session, so making a flagged session harder or longer
    # is a new finding and blocks again.
    return [
        _finding(
            "illness_hard",
            [unit],
            "Illness is reported; no hard or long session in the next 5 days.",
            {
                "through": last,
                "planned_minutes": round(_duration_s(unit) / 60),
                "hard": is_hard(unit),
            },
        )
        for unit in units
        if today.isoformat() <= _day(unit) <= last
        and (is_hard(unit) or _duration_s(unit) >= LONG_SESSION_S)
    ]


# Easy focus values of a unit, besides light strength and explicitly easy text.
_RETURN_EASY_FOCI = frozenset({"recovery", "easy", "mobility", "core"})


def session_level(unit: Mapping[str, Any]) -> int:
    """Intensity level of a planned unit: 0 easy, 1 moderate, 2 hard (or heavy)."""
    if is_hard(unit) or is_heavy_strength(unit):
        return 2
    focus = session_focus(unit)
    if focus.value is None and focus.strength_intensity is None:
        easy = calendar.workout_is_explicitly_easy(dict(unit))
    else:
        easy = focus.value in _RETURN_EASY_FOCI or focus.strength_intensity == "light"
    return 0 if easy and _duration_s(unit) < LONG_SESSION_S else 1


def _return_stage_hard(
    units: Sequence[Mapping[str, Any]],
    stage: int | None,
    today: date,
    skip: set[str],
) -> list[dict]:
    """Sessions above the return stage within the stage horizon (#2042)."""
    if stage is None:
        return []
    last = (today + timedelta(days=illness_return.RETURN_HORIZON_DAYS - 1)).isoformat()
    allowed = illness_return.STAGE_MAX_LEVEL[stage]
    return [
        _finding(
            "illness_hard",
            [unit],
            f"Return after illness, stage {stage}: only "
            f"{illness_return.STAGE_LABELS[stage]} until the stage advances.",
            {
                "through": last,
                "planned_minutes": round(_duration_s(unit) / 60),
                "hard": is_hard(unit),
                "return_stage": stage,
                "session_level": session_level(unit),
            },
        )
        for unit in units
        if str(unit.get("local_id") or unit.get("id")) not in skip
        and today.isoformat() <= _day(unit) <= last
        and session_level(unit) > allowed
    ]


_HR_CAP_CONTENT = (
    "name",
    "description",
    "date",
    "starts_at_local",
    "duration_minutes",
    "planned_duration_s",
    FOCUS_KEY,
    HR_CAP,
)
_STRENGTH_CONTENT = (
    "name",
    "description",
    "date",
    "starts_at_local",
    "duration_minutes",
    "planned_duration_s",
    FOCUS_KEY,
    INTENSITY_KEY,
    STRENGTH_STRUCTURE,
)


def _missing_strength_fields(unit: Mapping[str, Any]) -> list[str]:
    missing = [
        key
        for key in (FOCUS_KEY, INTENSITY_KEY)
        if not str(unit.get(key) or "").strip()
    ]
    try:
        structure = strength_structure.normalize_structure(unit.get(STRENGTH_STRUCTURE))
    except AppError:
        structure = None
    if not structure:
        missing.insert(0, STRENGTH_STRUCTURE)
    return missing


def _content_digest(unit: Mapping[str, Any], keys: Sequence[str]) -> str:
    content = json.dumps(
        {key: unit.get(key) for key in keys},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def hr_cap_invalid(
    units: Sequence[Mapping[str, Any]],
    first_threshold_pct: float | None = None,
    estimated: bool = False,
) -> list[dict]:
    """One finding per capped run unit with a missing or wrong cap, keyed by content.

    Only Coach writes run it (``PlanGuardService``). The content fingerprint
    makes a write that creates, moves or edits the unit a new finding, so an
    untouched older unit
    never blocks an unrelated write and is never rewritten silently.
    """
    findings = []
    for unit, problem in run_hr_cap.problems(units, first_threshold_pct, estimated):
        findings.append(
            _finding(
                "hr_cap_invalid",
                [unit],
                run_hr_cap.message(problem),
                {
                    "name": str(unit.get("name") or ""),
                    **problem,
                    "content": _content_digest(unit, _HR_CAP_CONTENT),
                },
            )
        )
    return findings


def strength_incomplete(units: Sequence[Mapping[str, Any]]) -> list[dict]:
    """One finding per incomplete strength unit, keyed by its content.

    Only Coach writes run it (``PlanGuardService``), not the plan notes.

    The content fingerprint makes a Coach write that creates, moves or edits
    the unit a new finding, while an untouched older free-text unit stays the
    same finding and never blocks an unrelated write.
    """
    findings = []
    for unit in units:
        if planned_sport_environment(unit)[0] is not Sport.STRENGTH:
            continue
        missing = _missing_strength_fields(unit)
        if not missing:
            continue
        findings.append(
            _finding(
                "strength_incomplete",
                [unit],
                "Strength unit without "
                + ", ".join(missing)
                + ": write the exercises in order with sets, reps, load and their "
                "Garmin catalogue name (garmin_exercise), plus session_focus and "
                "strength_intensity. Ask the athlete for anything missing or "
                "ambiguous.",
                {
                    "name": str(unit.get("name") or ""),
                    "missing": missing,
                    "content": _content_digest(unit, _STRENGTH_CONTENT),
                },
            )
        )
    return findings


_FOCUS_CONTENT = (
    "name",
    "description",
    "date",
    "starts_at_local",
    "duration_minutes",
    "planned_duration_s",
    "target",
    FOCUS_KEY,
)
# Units with a focus vocabulary other than strength, which has its own check.
_FOCUS_SPORTS = frozenset({Sport.RUN, Sport.RIDE})


def focus_missing(units: Sequence[Mapping[str, Any]]) -> list[dict]:
    """One finding per run or ride unit without a stored ``session_focus``.

    Keyed by content like ``strength_incomplete``: a Coach write that creates,
    moves or edits the unit is a new finding, an untouched older unit never
    blocks an unrelated write. Sports without a focus vocabulary are exempt.
    """
    findings = []
    for unit in units:
        sport = planned_sport_environment(unit)[0]
        if sport not in _FOCUS_SPORTS or str(unit.get(FOCUS_KEY) or "").strip():
            continue
        findings.append(
            _finding(
                "focus_missing",
                [unit],
                "Unit without session_focus: set the type of the session ("
                + ", ".join(allowed_foci(sport))
                + ") on every unit you create, move or change.",
                {
                    "name": str(unit.get("name") or ""),
                    "sport": sport.value,
                    "content": _content_digest(unit, _FOCUS_CONTENT),
                },
            )
        )
    return findings


def _with_computed_hard(
    units: Sequence[Mapping[str, Any]], sessions: Sequence[load_checks.PlannedSession]
) -> list[Mapping[str, Any]]:
    """Unit copies carrying the hardness computed from their workout steps."""
    computed = {
        id(session.unit): load_checks.computed_hard(session.estimate)
        for session in sessions
    }
    return [
        {**unit, COMPUTED_HARD: computed[id(unit)]}
        if computed.get(id(unit)) is not None
        else unit
        for unit in units
    ]


def _drafted(drafts: Iterable[load_checks.Draft]) -> list[dict[str, Any]]:
    return [
        _finding(code, units, message, evidence)
        for code, units, message, evidence in drafts
    ]


def _load_findings(
    sessions: Sequence[load_checks.PlannedSession],
    completed: Sequence[Mapping[str, Any]],
    thresholds: load_checks.LoadThresholds,
    today: date,
) -> list[dict[str, Any]]:
    drafts = load_checks.unknown_load(sessions, thresholds)
    if not thresholds.unavailable:
        drafts += load_checks.session_spikes(sessions, completed, thresholds, today)
        drafts += load_checks.weekly_rises(sessions, completed, thresholds, today)
    return _drafted(drafts)


def _calendar_findings(
    units: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    today: date,
) -> list[dict[str, Any]]:
    """Calendar notes for hard or long units."""
    occupied = calendar_load.busy_minutes(events, today, 56)
    findings: list[dict[str, Any]] = []
    for unit in units:
        if not (is_hard(unit) or _duration_s(unit) >= LONG_SESSION_S):
            continue
        overlap, minutes = calendar_load.calendar_risk(unit, events, occupied)
        if overlap or minutes >= calendar_load.HEAVY_DAY_MINUTES:
            findings.append(
                _finding(
                    "calendar_load",
                    [unit],
                    "Calendar event overlaps or day is heavily booked",
                    {"overlap": overlap, "busy_minutes": minutes},
                )
            )
        try:
            day = date.fromisoformat(_day(unit))
        except ValueError:
            continue
        if all_day := calendar_load.all_day_events(events, day):
            findings.append(
                _finding(
                    ALL_DAY_EVENT,
                    [unit],
                    "A hard or long unit falls on a day with an all-day calendar event.",
                    {"events": all_day},
                )
            )
    return findings


def check_plan(
    *,
    today: date,
    units: Sequence[Mapping[str, Any]],
    completed: Sequence[Mapping[str, Any]],
    competitions: Sequence[Mapping[str, Any]],
    illness: str = "",
    thresholds: load_checks.LoadThresholds | None = None,
    expects_strength: bool = False,
    calendar_events: Sequence[Mapping[str, Any]] = (),
    return_stage: int | None = None,
) -> list[dict[str, Any]]:
    """Return all findings for the resulting future planned units.

    Without ``thresholds`` only the threshold-free checks run: no load notes.
    """
    sessions = load_checks.plan_sessions(
        units, thresholds or load_checks.LoadThresholds()
    )
    units = _with_computed_hard(units, sessions)
    calendar_notes = _calendar_findings(units, calendar_events, today)
    illness_findings = _illness_hard(units, illness, today)
    flagged = {item for found in illness_findings for item in found["local_ids"]}
    return [
        *calendar_notes,
        *_drafted(load_checks.run_distance_spikes(sessions, completed, today)),
        *(
            _load_findings(sessions, completed, thresholds, today)
            if thresholds is not None
            else []
        ),
        *_back_to_back(units),
        *_strength_same_day(units),
        *_drafted(leg_strength.before_key_session(units, is_hard, is_heavy_strength)),
        *_drafted(leg_strength.frequency(units, today, expects_strength, completed)),
        *_missing_taper(units, completed, competitions, today),
        *illness_findings,
        *_return_stage_hard(units, return_stage, today, flagged),
    ]


def finding_key(finding: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identity of a finding across a write.

    A taper is one per competition, a weekly rise one per sport and week, and
    the unknown-load note one per plan.
    """
    if finding["code"] == "missing_taper":
        return (finding["code"], finding["evidence"]["competition_date"])
    if finding["code"] == "intensity_distribution":
        return (finding["code"], finding["evidence"]["week_start"])
    if finding["code"] == leg_strength.FREQUENCY:
        evidence = finding["evidence"]
        if evidence["reason"] == "no_leg_session":
            # One note for the plan: unrelated edits must not repeat it.
            return (finding["code"], evidence["reason"])
        return (finding["code"], evidence["reason"], evidence["week_start"])
    if finding["code"] == "weekly_load_rise":
        evidence = finding["evidence"]
        return (finding["code"], evidence["sport"], evidence["week_start"])
    if finding["code"] in {"strength_incomplete", "focus_missing", "hr_cap_invalid"}:
        evidence = finding["evidence"]
        return (finding["code"], tuple(finding["local_ids"]), evidence["content"])
    if finding["code"] == "load_unknown":
        # One note for the plan: unrelated edits must not repeat it.
        return (finding["code"],)
    return (finding["code"], tuple(finding["dates"]), tuple(finding["local_ids"]))


def _risk(finding: Mapping[str, Any]) -> tuple[Any, ...]:
    """Comparable risk of one finding; higher means riskier."""
    evidence = finding["evidence"]
    if finding["code"] in load_checks.SEVERITY_CODES:
        return (evidence.get("severity") == "warning",)
    if finding["code"] == "illness_hard":
        return (bool(evidence.get("hard")), evidence.get("planned_minutes") or 0)
    if finding["code"] == leg_strength.FREQUENCY:
        return (
            evidence.get("leg_sessions") or 0,
            evidence.get("heavy_leg_sessions") or 0,
        )
    if finding["code"] == "intensity_distribution":
        return (max(evidence["deviating_bands"].values()),)
    if finding["code"] == "calendar_load":
        return (bool(evidence.get("overlap")), evidence.get("busy_minutes") or 0)
    return ()


def new_findings(
    before: Sequence[Mapping[str, Any]], after: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Findings of ``after`` that are new or riskier than in ``before``.

    A run spike growing into a warning, or an illness-time session made harder
    or longer, is new; shortening or easing it is not.
    """
    previous = {finding_key(item): _risk(item) for item in before}
    result = []
    for item in after:
        known = previous.get(finding_key(item))
        # Riskier in any dimension (harder, or longer) is new, not lexicographic.
        if known is None or any(now > then for now, then in zip(_risk(item), known)):
            result.append(item)
    return result
