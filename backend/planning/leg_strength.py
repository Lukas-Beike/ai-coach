"""Leg strength sessions of a plan: classification, weekly counts and notes.

Only the number and the intensity of leg strength sessions count. There is no
tonnage, no per-exercise volume and no planned strength load, and strength stays
out of the endurance low/moderate/high distribution and the weekly load notes.

- Leg: the session focus first (``legs``, ``full_body`` and ``plyometrics`` are
  leg, other foci not), whether set or keyword-derived (``session_focus``); no
  focus means unknown.
- Intensity: the set strength intensity, else the planned intensity
  (heavy from 0.85, moderate from 0.70), else RPE (heavy from 8, moderate from
  6), else the text; otherwise unknown.

Notes are non-blocking drafts ``(code, units, message, evidence)`` that
``plan_checks`` turns into findings. No I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import Sport
from backend.planning.season import season_plan_summary
from backend.planning.session_focus import SessionFocus, session_focus
from backend.planning.sport import planned_sport_environment

BEFORE_KEY = "leg_strength_before_key_session"
FREQUENCY = "leg_strength_frequency"
INTENSITIES: Final = ("light", "moderate", "heavy")
HEAVY_FACTOR = 0.85
MODERATE_FACTOR = 0.70
HEAVY_RPE = 8
MODERATE_RPE = 6
KEY_GAP_H = 24
SAME_DAY_GAP_H = 6
MAX_LEG_SESSIONS = 3
MAX_HEAVY_LEG_SESSIONS = 2
MIN_PLAN_WEEKS = 2
LONG_SESSION_S = 5400
NOTE = (
    "Count and intensity of strength sessions only, no tonnage and no load. "
    "Leg = legs, full body or plyometrics focus."
)
Predicate = Callable[[Mapping[str, Any]], bool]
Draft = tuple[str, list[Mapping[str, Any]], str, dict[str, Any]]
_ENDURANCE = frozenset({Sport.RUN, Sport.RIDE})
_HEAVY = re.compile(r"\b(?:heavy|schwer|[1-6]\s*rm)\b", re.IGNORECASE)
_MODERATE = re.compile(r"\b(?:moderate|moderat|mittel(?:schwer)?)\b", re.IGNORECASE)
_LIGHT = re.compile(r"\b(?:light|leicht)\b", re.IGNORECASE)
# A profile answer that says no strength is wanted.
_NO_STRENGTH = re.compile(
    r"^\s*(?:-+\s*$|(?:kein\w*|nein|no|none|ohne|nicht)\b)", re.IGNORECASE
)
_EXPECTING_PHASES = frozenset({"base", "build"})


@dataclass(frozen=True)
class StrengthClass:
    """Leg (``None`` unknown) and intensity (``None`` unknown) of a strength unit."""

    leg: bool | None
    intensity: str | None


def planned_intensity_factor(unit: Mapping[str, Any]) -> float | None:
    """Planned intensity as a factor; percent values above 1.5 are divided by 100."""
    value = number(unit.get("planned_intensity"))
    if value is None:
        return None
    return value / 100 if value > 1.5 else value


def _grade(value: float, heavy: float, moderate: float) -> str:
    if value >= heavy:
        return "heavy"
    return "moderate" if value >= moderate else "light"


def _text_intensity(unit: Mapping[str, Any]) -> str | None:
    text = f"{unit.get('name') or ''} {unit.get('description') or ''}"
    for label, pattern in (
        ("heavy", _HEAVY),
        ("moderate", _MODERATE),
        ("light", _LIGHT),
    ):
        if pattern.search(text):
            return label
    return None


def _intensity(unit: Mapping[str, Any], focus: SessionFocus) -> str | None:
    if focus.strength_intensity is not None:
        return focus.strength_intensity
    factor = planned_intensity_factor(unit)
    if factor is not None:
        return _grade(factor, HEAVY_FACTOR, MODERATE_FACTOR)
    rpe = number(unit.get("rpe"))
    if rpe is not None:
        return _grade(rpe, HEAVY_RPE, MODERATE_RPE)
    return _text_intensity(unit)


def classify(unit: Mapping[str, Any]) -> StrengthClass | None:
    """Leg and intensity of a strength unit; ``None`` for any other sport."""
    if planned_sport_environment(unit)[0] is not Sport.STRENGTH:
        return None
    focus = session_focus(unit)
    leg = None if focus.value is None else focus.is_leg_strength
    return StrengthClass(leg, _intensity(unit, focus))


def week_counts(units: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Strength sessions, leg sessions and leg sessions by intensity of units."""
    by_intensity = dict.fromkeys((*INTENSITIES, "unknown"), 0)
    sessions = leg_sessions = leg_unknown = 0
    for unit in units:
        found = classify(unit)
        if found is None:
            continue
        sessions += 1
        leg_unknown += found.leg is None
        if found.leg:
            leg_sessions += 1
            by_intensity[found.intensity or "unknown"] += 1
    return {
        "sessions": sessions,
        "leg_sessions": leg_sessions,
        "leg_unknown_sessions": leg_unknown,
        "leg_by_intensity": by_intensity,
    }


def completed_unit(row: Mapping[str, Any]) -> dict[str, Any]:
    """A completed activity summary shaped like a unit for ``classify``."""
    return {
        "sport": row.get("sport"),
        "name": row.get("name"),
        "description": row.get("description"),
        "planned_intensity": row.get("intensity"),
        "rpe": row.get("rpe"),
    }


def completed_counts(
    completed: Iterable[Mapping[str, Any]], first: str, last: str
) -> dict[str, Any]:
    """Counts of the completed strength activities from ``first`` to ``last``."""
    return week_counts(
        completed_unit(row)
        for row in completed
        if first <= iso_date_prefix(row.get("started_at_local")) <= last
    )


def _day(unit: Mapping[str, Any]) -> str:
    return iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")


def _monday(unit: Mapping[str, Any]) -> date | None:
    try:
        day = date.fromisoformat(_day(unit))
    except ValueError:
        return None
    return day - timedelta(days=day.weekday())


def _start(unit: Mapping[str, Any]) -> datetime | None:
    try:
        start = datetime.fromisoformat(str(unit.get("starts_at_local") or ""))
    except ValueError:
        return None
    start = start.replace(tzinfo=None)
    # Imported workouts without a time carry a synthetic midnight: unknown.
    return None if start.time() == time.min else start


def _by_week(
    units: Iterable[Mapping[str, Any]],
) -> dict[date, list[Mapping[str, Any]]]:
    weeks: dict[date, list[Mapping[str, Any]]] = {}
    for unit in units:
        monday = _monday(unit)
        if monday is not None:
            weeks.setdefault(monday, []).append(unit)
    return weeks


def planned_weeks(
    units: Sequence[Mapping[str, Any]], today: date
) -> list[dict[str, Any]]:
    """Strength counts per ISO week of all planned units, oldest first.

    A week that began before ``today`` is partial: its elapsed days are not in
    the planned units.
    """
    return [
        {
            "week_start": monday.isoformat(),
            "partial": monday < today,
            **week_counts(group),
        }
        for monday, group in sorted(_by_week(units).items())
    ]


def brief_strength(
    weeks: Sequence[Mapping[str, Any]], limit: int
) -> dict[str, Any] | None:
    """Planned strength counts of the next planned weeks for the planning brief."""
    if not weeks:
        return None
    return {
        "source": "derived from planned units' session focus, local plan",
        "note": NOTE,
        "weeks": list(weeks[:limit]),
    }


def strength_expected(
    profile_text: str, competitions: Sequence[Mapping[str, Any]], today: date
) -> bool:
    """Whether the profile or the season phase of the next A/B race asks for strength."""
    text = profile_text.strip()
    if text and not _NO_STRENGTH.match(text):
        return True
    upcoming = season_plan_summary(
        [dict(row) for row in competitions if str(row.get("priority") or "B") != "C"],
        today,
    )["next_event"]
    return upcoming is not None and upcoming["phase"] in _EXPECTING_PHASES


def key_sessions(
    units: Sequence[Mapping[str, Any]], is_hard: Predicate
) -> list[Mapping[str, Any]]:
    """Hard runs and rides, long-focus ones, and the week's longest 90+ min session."""
    longest: dict[tuple[Sport, date | None], Mapping[str, Any]] = {}
    endurance = [
        unit for unit in units if planned_sport_environment(unit)[0] in _ENDURANCE
    ]
    for unit in endurance:
        key = (planned_sport_environment(unit)[0], _monday(unit))
        if key not in longest or _seconds(unit) > _seconds(longest[key]):
            longest[key] = unit
    long_ids = {id(u) for u in longest.values() if _seconds(u) >= LONG_SESSION_S}
    return [
        unit
        for unit in endurance
        if is_hard(unit) or session_focus(unit).value == "long" or id(unit) in long_ids
    ]


def _seconds(unit: Mapping[str, Any]) -> float:
    seconds = number(unit.get("planned_duration_s"))
    if seconds is None:
        minutes = number(unit.get("duration_minutes"))
        seconds = None if minutes is None else minutes * 60
    return seconds or 0.0


def _gap_hours(strength: Mapping[str, Any], key: Mapping[str, Any]) -> float | None:
    first, second = _start(strength), _start(key)
    if first is None or second is None:
        return None
    return (second - first).total_seconds() / 3600


def _too_close(
    strength: Mapping[str, Any], key: Mapping[str, Any], heavy_hard: bool
) -> bool:
    """Less than about 24 h before the key session; dates alone mean the day before."""
    gap = _gap_hours(strength, key)
    if gap is None:
        try:
            days = (
                date.fromisoformat(_day(key)) - date.fromisoformat(_day(strength))
            ).days
        except ValueError:
            return False
        return days == 1
    same_day_rule = heavy_hard and _day(strength) == _day(key) and gap < SAME_DAY_GAP_H
    return 0 < gap < KEY_GAP_H and not same_day_rule


def _before_key_draft(
    strength: Mapping[str, Any],
    keys: Sequence[Mapping[str, Any]],
    is_hard: Predicate,
    is_heavy: Predicate,
) -> Draft | None:
    """The first key session that follows a moderate or heavy leg session closely."""
    found = classify(strength)
    if found is None or not found.leg or found.intensity not in {"moderate", "heavy"}:
        return None
    for key in keys:
        hard = is_hard(key)
        if not _too_close(strength, key, is_heavy(strength) and hard):
            continue
        gap = _gap_hours(strength, key)
        return (
            BEFORE_KEY,
            [strength, key],
            "Moderate or heavy leg strength less than about 24 h before a hard or long session.",
            {
                "strength_intensity": found.intensity,
                "key_session": "hard" if hard else "long",
                "strength_day": _day(strength),
                "key_day": _day(key),
                "gap_hours": None if gap is None else round(gap, 1),
                "time_known": gap is not None,
            },
        )
    return None


def before_key_session(
    units: Sequence[Mapping[str, Any]], is_hard: Predicate, is_heavy: Predicate
) -> list[Draft]:
    """Moderate or heavy leg strength shortly before a hard or long run or ride.

    Heavy leg work within 6 h of a hard session on one day belongs to
    ``strength_hard_same_day`` (``is_heavy`` is that rule's own test).
    """
    keys = key_sessions(units, is_hard)
    drafts = (_before_key_draft(unit, keys, is_hard, is_heavy) for unit in units)
    return [draft for draft in drafts if draft is not None]


def _too_many(monday: date, group: Sequence[Mapping[str, Any]]) -> Draft | None:
    counts = week_counts(group)
    heavy = counts["leg_by_intensity"]["heavy"]
    if counts["leg_sessions"] <= MAX_LEG_SESSIONS and heavy <= MAX_HEAVY_LEG_SESSIONS:
        return None
    return (
        FREQUENCY,
        [unit for unit in group if (found := classify(unit)) and found.leg],
        "More than 3 leg strength sessions or more than 2 heavy ones in a planned week.",
        {
            "reason": "too_many",
            "week_start": monday.isoformat(),
            "leg_sessions": counts["leg_sessions"],
            "heavy_leg_sessions": heavy,
            "max_leg_sessions": MAX_LEG_SESSIONS,
            "max_heavy_leg_sessions": MAX_HEAVY_LEG_SESSIONS,
        },
    )


def _consecutive(mondays: Sequence[date]) -> list[date]:
    """The run of adjacent weeks that starts at the first Monday."""
    run = list(mondays[:1])
    for monday in mondays[1:]:
        if monday - run[-1] != timedelta(weeks=1):
            break
        run.append(monday)
    return run


def _no_legs(
    weeks: Mapping[date, Sequence[Mapping[str, Any]]], today: date
) -> Draft | None:
    """Two or more full planned weeks without any leg strength session."""
    full = _consecutive(sorted(monday for monday in weeks if monday >= today))
    if len(full) < MIN_PLAN_WEEKS:
        return None
    counts = [week_counts(weeks[monday]) for monday in full]
    if any(item["leg_sessions"] or item["leg_unknown_sessions"] for item in counts):
        return None
    return (
        FREQUENCY,
        [],
        "No leg strength session in a plan of two or more weeks although strength is expected.",
        {
            "reason": "no_leg_session",
            "week_start": full[0].isoformat(),
            "weeks": [monday.isoformat() for monday in full],
        },
    )


def frequency(
    units: Sequence[Mapping[str, Any]], today: date, expects_strength: bool
) -> list[Draft]:
    """Too many leg sessions per week, or none in a plan that should have them."""
    weeks = _by_week(units)
    drafts = [
        draft
        for monday, group in sorted(weeks.items())
        if (draft := _too_many(monday, group)) is not None
    ]
    if expects_strength and (draft := _no_legs(weeks, today)) is not None:
        drafts.append(draft)
    return drafts
