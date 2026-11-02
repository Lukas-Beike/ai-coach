"""Pure checks of a proposed future plan against five training-science rules.

The Coach tool write runs these on the resulting plan; findings stop the write
until the model corrects the plan or names the accepted deviation. No I/O.

Rules (references are observational or practice-based, not individual advice):
- run_spike: a planned run is more than 10 % longer than the longest completed
  run of the last 30 days (Frandsen et al. 2025, BJSM). Compared by duration;
  planned distance has no fixed unit. No run in 30 days: no finding.
- back_to_back_hard: hard run/ride sessions on consecutive days. Hard means a
  planned intensity of at least 0.85 (percent values above 1.5 are divided by
  100) or workout text with a Z4-Z7 / zone 4-7 target. Unknown is not hard.
- strength_hard_same_day: heavy strength (planned intensity >= 0.85 or text
  naming heavy, schwer, maximal or a 1-6 RM) and a hard run/ride on one date
  with less than 6 h between start times, or an unknown start time
  (Robineau et al. 2016).
- missing_taper: a priority A/B competition whose final 14 days carry less
  than 20 % less duration than the 14 days before them (completed activities
  before today, planned units from today). Only judged when the plan reaches
  into the final 14 days (Bosquet et al. 2007: cut volume 40-60 %).
- illness_hard: the latest check-in reports illness and a hard session or a
  session of 90 minutes or more is planned within the next 3 days.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import Sport
from backend.planning.sport import planned_sport_environment

FINDING_CODES = (
    "run_spike",
    "back_to_back_hard",
    "strength_hard_same_day",
    "missing_taper",
    "illness_hard",
)
RULE_SUMMARY = {
    "run_spike": "Planned run at most 10 % longer than the longest run of the last 30 days.",
    "back_to_back_hard": "No hard run or ride on consecutive days.",
    "strength_hard_same_day": "Heavy strength and a hard run or ride at least 6 h apart.",
    "missing_taper": "Final 14 days before an A/B competition at least 20 % lighter than the 14 days before.",
    "illness_hard": "No hard or 90+ minute session within 3 days of a reported illness.",
}
SPIKE_FACTOR = 1.10
HARD_INTENSITY = 0.85
MIN_STRENGTH_GAP_H = 6
TAPER_DAYS = 14
TAPER_MIN_REDUCTION = 0.20
ILLNESS_DAYS = 3
LONG_SESSION_S = 5400
RUN_WINDOW_DAYS = 30
_ENDURANCE = frozenset({Sport.RUN, Sport.RIDE})
# A Z4+ target counts unless a negation such as "unter Z4" or "kein Z5" precedes it.
_HARD_ZONE = re.compile(
    r"(?<!unter )(?<!kein )(?<!keine )(?<!nicht )(?<!below )(?<!under )(?<!no )"
    r"\b(?:z|zone\s*)[4-7]\b",
    re.IGNORECASE,
)
# "maximal" is left out: in German it mostly means "at most".
_HEAVY = re.compile(r"\b(?:heavy|schwer|[1-6]\s*rm)\b", re.IGNORECASE)
# Check-in answers that report no illness.
_NO_ILLNESS = frozenset(
    {"", "-", "keine", "kein", "nein", "nichts", "gesund", "none", "no", "n/a"}
)


def intensity_factor(unit: Mapping[str, Any]) -> float | None:
    value = number(unit.get("planned_intensity"))
    if value is None:
        return None
    return value / 100 if value > 1.5 else value


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
    """Whether a planned run or ride is hard by its intensity key or Z4+ text."""
    if _sport(unit) not in _ENDURANCE:
        return False
    factor = intensity_factor(unit)
    return (factor is not None and factor >= HARD_INTENSITY) or bool(
        _HARD_ZONE.search(_text(unit))
    )


def is_heavy_strength(unit: Mapping[str, Any]) -> bool:
    if _sport(unit) is not Sport.STRENGTH:
        return False
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
        "dates": sorted({_day(unit) for unit in units}),
        "local_ids": sorted(
            str(unit.get("local_id") or unit.get("id")) for unit in units
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
        and first <= iso_date_prefix(row.get("started_at_local")) < today.isoformat()
    ]
    longest = max(durations, default=0.0)
    return longest or None


def _run_spike(units: Sequence[Mapping[str, Any]], longest: float | None) -> list[dict]:
    if longest is None:
        return []
    return [
        _finding(
            "run_spike",
            [unit],
            "Planned run is more than 10 % longer than the longest run of the last 30 days.",
            {
                "planned_minutes": round(_duration_s(unit) / 60),
                "longest_run_30d_minutes": round(longest / 60),
                "limit_minutes": round(longest * SPIKE_FACTOR / 60),
            },
        )
        for unit in units
        if _sport(unit) is Sport.RUN and _duration_s(unit) > longest * SPIKE_FACTOR
    ]


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


def _start(unit: Mapping[str, Any]) -> datetime | None:
    """Local wall-clock start; an offset is dropped so aware and naive starts compare."""
    try:
        start = datetime.fromisoformat(str(unit.get("starts_at_local") or ""))
    except ValueError:
        return None
    return start.replace(tzinfo=None)


def _gap_too_short(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    start_a, start_b = _start(first), _start(second)
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
    if illness.strip().casefold() in _NO_ILLNESS:
        return []
    last = (today + timedelta(days=ILLNESS_DAYS)).isoformat()
    risky = [
        unit
        for unit in units
        if today.isoformat() <= _day(unit) <= last
        and (is_hard(unit) or _duration_s(unit) >= LONG_SESSION_S)
    ]
    if not risky:
        return []
    return [
        _finding(
            "illness_hard",
            risky,
            "Illness is reported; no hard or long session in the next 3 days.",
            {"through": last},
        )
    ]


def check_plan(
    *,
    today: date,
    units: Sequence[Mapping[str, Any]],
    completed: Sequence[Mapping[str, Any]],
    competitions: Sequence[Mapping[str, Any]],
    illness: str = "",
) -> list[dict[str, Any]]:
    """Return all findings for the resulting future planned units."""
    return [
        *_run_spike(units, longest_completed_run_s(completed, today)),
        *_back_to_back(units),
        *_strength_same_day(units),
        *_missing_taper(units, completed, competitions, today),
        *_illness_hard(units, illness, today),
    ]


def finding_key(finding: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identity of a finding across a write; a taper is one finding per competition."""
    if finding["code"] == "missing_taper":
        return (finding["code"], finding["evidence"]["competition_date"])
    return (finding["code"], tuple(finding["dates"]), tuple(finding["local_ids"]))
