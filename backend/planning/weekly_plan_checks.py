"""Non-blocking notes against the athlete's structured weekly plan.

Fixed sessions, rest days, explicit windows and the daily maximum come from the
profile ``weekly_plan``. Windows of the built-in fallback never produce a note, also not a free-time one.
Drafts are ``(code, units, message, evidence)`` as in ``leg_strength``; a unit
that only carries a ``date`` stands for a missing session. No I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Final

from backend.athlete import weekly_plan
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.planning import free_time
from backend.planning.session_focus import session_focus
from backend.planning.sport import planned_sport_environment

FIXED_MISSING: Final = "fixed_session_missing"
REST_DAY: Final = "rest_day_session"
OUTSIDE_WINDOWS: Final = "outside_windows"
OVER_MAX: Final = "over_max_minutes"
NO_FREE_WINDOW: Final = "no_free_window"
CODES: Final = (FIXED_MISSING, REST_DAY, OUTSIDE_WINDOWS, OVER_MAX, NO_FREE_WINDOW)
MAX_SPAN_DAYS: Final = 120
Draft = tuple[str, list[Mapping[str, Any]], str, dict[str, Any]]


def _day(unit: Mapping[str, Any]) -> str:
    return iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _minutes(unit: Mapping[str, Any]) -> float:
    seconds = number(unit.get("planned_duration_s"))
    if seconds is None:
        minutes = number(unit.get("duration_minutes"))
        return minutes or 0.0
    return seconds / 60


def _start_minute(unit: Mapping[str, Any]) -> int | None:
    """Minute of the day of a set start time; midnight counts as not set."""
    try:
        start = datetime.fromisoformat(str(unit.get("starts_at_local") or ""))
    except ValueError:
        return None
    minute = start.hour * 60 + start.minute
    return minute or None


def _sport(unit: Mapping[str, Any]) -> str:
    return planned_sport_environment(unit)[0].value


def _matches(fixed: Mapping[str, Any], unit: Mapping[str, Any]) -> bool:
    if fixed["sport"] != _sport(unit):
        return False
    focus = session_focus(unit)
    return fixed.get("focus") is None or focus.value in (None, fixed["focus"])


def _span(units: Sequence[Mapping[str, Any]], today: date) -> list[date]:
    """Days of the weeks the plan touches, from its first week's start (not before today)."""
    days = sorted(day for day in (_date(_day(unit)) for unit in units) if day)
    days = [day for day in days if day >= today]
    if not days:
        return []
    first = max(_week_start(days[0]), today)
    last = days[-1] + timedelta(days=6 - days[-1].weekday())
    count = min((last - first).days + 1, MAX_SPAN_DAYS)
    return [first + timedelta(days=offset) for offset in range(count)]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _missing_fixed(
    week: Sequence[weekly_plan.EffectiveDay],
    units: Sequence[Mapping[str, Any]],
    today: date,
) -> tuple[list[Draft], dict[int, Mapping[str, Any]]]:
    """Notes for fixed sessions without a unit; also the ids of matched units."""
    by_day: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for unit in units:
        by_day[_day(unit)].append(unit)
    matched: dict[int, Mapping[str, Any]] = {}
    drafts: list[Draft] = []
    for day in _span(units, today):
        missing = _unmatched(week, day, by_day[day.isoformat()], matched)
        if missing:
            drafts.append(_missing_draft(day, missing, units))
    return drafts, matched


def _unmatched(
    week: Sequence[weekly_plan.EffectiveDay],
    day: date,
    day_units: Sequence[Mapping[str, Any]],
    matched: dict[int, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    missing: list[Mapping[str, Any]] = []
    for fixed in week[day.weekday()].fixed_sessions:
        unit = next(
            (
                item
                for item in day_units
                if id(item) not in matched and _matches(fixed, item)
            ),
            None,
        )
        if unit is None:
            missing.append(fixed)
        else:
            matched[id(unit)] = fixed
    return missing


def _missing_draft(
    day: date, missing: Sequence[Mapping[str, Any]], units: Sequence[Mapping[str, Any]]
) -> Draft:
    week = _week_start(day)
    elsewhere = sorted(
        {
            _day(unit)
            for unit in units
            if _day(unit) != day.isoformat()
            and (when := _date(_day(unit))) is not None
            and _week_start(when) == week
            and any(item["sport"] == _sport(unit) for item in missing)
        }
    )
    return (
        FIXED_MISSING,
        [{"date": day.isoformat()}],
        "A fixed session of the weekly plan is not planned on its day.",
        {"fixed_sessions": [dict(item) for item in missing], "other_days": elsewhere},
    )


def _window_note(unit: Mapping[str, Any], windows: Sequence[str]) -> Draft | None:
    start = _start_minute(unit)
    if start is None or not windows:
        return None
    end = start + round(_minutes(unit))
    for text in windows:
        parsed = weekly_plan.parse_window(text)
        if parsed and parsed[0] <= start and end <= parsed[1]:
            return None
    return (
        OUTSIDE_WINDOWS,
        [unit],
        "A unit lies outside the time windows of the weekly plan.",
        {
            "windows": list(windows),
            "start": weekly_plan.clock(start),
            "planned_minutes": round(_minutes(unit)),
        },
    )


def _unit_windows(
    unit: Mapping[str, Any],
    effective: weekly_plan.EffectiveDay,
    matched: Mapping[int, Mapping[str, Any]],
) -> Sequence[str]:
    """Windows a unit must lie in: a fixed session's own window, else the day's.

    A fixed session without a window and the built-in fallback have none.
    """
    fixed = matched.get(id(unit))
    if fixed is not None:
        return [fixed["window"]] if fixed.get("window") else []
    return [] if effective.source == "fallback" else effective.windows


def _free_notes(
    effective: weekly_plan.EffectiveDay,
    day: date,
    day_units: Sequence[Mapping[str, Any]],
    matched: Mapping[int, Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> list[Draft]:
    """Units longer than the free time left in the day's explicit windows."""
    if effective.source == "fallback":
        return []
    free = free_time.free_minutes(day, effective.windows, events)
    return [
        (
            NO_FREE_WINDOW,
            [unit],
            "A unit does not fit the free time of the day's weekly-plan windows.",
            {
                "free_minutes": free,
                "planned_minutes": round(_minutes(unit)),
                "source": effective.source,
            },
        )
        for unit in day_units
        if round(_minutes(unit)) > free
        and not (matched.get(id(unit)) or {}).get("window")
    ]


def _day_notes(
    week: Sequence[weekly_plan.EffectiveDay],
    day: date,
    day_units: Sequence[Mapping[str, Any]],
    matched: dict[int, Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]] = (),
) -> list[Draft]:
    effective = week[day.weekday()]
    if effective.rest_day:
        return [
            (
                REST_DAY,
                list(day_units),
                "Training is planned on a rest day of the weekly plan.",
                {"day": effective.day},
            )
        ]
    drafts: list[Draft] = [
        note
        for unit in day_units
        if (note := _window_note(unit, _unit_windows(unit, effective, matched)))
    ]
    drafts += _free_notes(effective, day, day_units, matched, events)
    total = round(sum(_minutes(unit) for unit in day_units))
    if effective.max_minutes is not None and total > effective.max_minutes:
        drafts.append(
            (
                OVER_MAX,
                list(day_units),
                "Planned training exceeds the maximum duration of the day.",
                {"planned_minutes": total, "max_minutes": effective.max_minutes},
            )
        )
    return drafts


def check(
    plan: Any,
    units: Sequence[Mapping[str, Any]],
    today: date,
    events: Sequence[Mapping[str, Any]] = (),
) -> list[Draft]:
    """Drafts for the future units; none when the weekly plan is empty."""
    if not str(plan or "").strip():
        return []
    week = weekly_plan.effective_week(plan)
    drafts, matched = _missing_fixed(week, units, today)
    by_day: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for unit in units:
        by_day[_day(unit)].append(unit)
    for text, day_units in sorted(by_day.items()):
        day = _date(text)
        if day is not None and day >= today:
            drafts += _day_notes(week, day, day_units, matched, events)
    return drafts
