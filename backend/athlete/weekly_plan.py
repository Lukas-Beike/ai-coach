"""Structured weekly plan of the athlete profile: windows, limits, fixed sessions.

Stored as one canonical JSON string in the profile field ``weekly_plan`` (no
schema change). Per weekday everything is optional: time windows, a maximum
duration, fixed sessions and an explicit rest day. A day without windows falls
back to the profile-wide default, then to the built-in working-hours windows
(prompt rule 8b). An empty plan keeps the free-text behaviour. No I/O.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.errors import AppError
from backend.planning.session_focus import ENDURANCE_FOCI, RIDE_FOCI, STRENGTH_FOCI

DAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SPORTS: Final = ("run", "ride", "strength")
FOCI: Final = {"run": ENDURANCE_FOCI, "ride": RIDE_FOCI, "strength": STRENGTH_FOCI}
MAX_WINDOWS: Final = 4
MAX_FIXED: Final = 4
MAX_DAY_MINUTES: Final = (15, 600)
FIXED_MINUTES: Final = (10, 600)
SOURCES: Final = ("profile", "default", "fallback")
FALLBACK_WINDOWS: Final = {
    "mon": ("00:00-06:00", "12:00-13:00", "15:30-24:00"),
    "tue": ("00:00-06:00", "12:00-13:00", "15:30-24:00"),
    "wed": ("00:00-06:00", "12:00-13:00", "15:30-24:00"),
    "thu": ("00:00-06:00", "12:00-13:00", "15:30-24:00"),
    "fri": ("14:00-24:00",),
    "sat": ("00:00-24:00",),
    "sun": ("00:00-24:00",),
}
_INVALID = "Der Wochenplan ist ungültig: "


@dataclass(frozen=True)
class EffectiveDay:
    """What applies on one weekday after the window fallback."""

    day: str
    windows: tuple[str, ...]
    source: str
    max_minutes: int | None
    rest_day: bool
    fixed_sessions: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "windows": list(self.windows),
            "source": self.source,
            "max_minutes": self.max_minutes,
            "rest_day": self.rest_day,
            "fixed_sessions": [dict(item) for item in self.fixed_sessions],
        }


def parse_window(text: Any) -> tuple[int, int] | None:
    """Minutes of ``HH:MM-HH:MM`` (end may be 24:00); ``None`` when invalid."""
    parts = str(text or "").strip().split("-")
    if len(parts) != 2:
        return None
    start, end = _minutes(parts[0]), _minutes(parts[1])
    if start is None or end is None or not 0 <= start < end <= 1440:
        return None
    return start, end


def _minutes(text: str) -> int | None:
    hours, separator, minutes = text.strip().partition(":")
    if not separator or not (hours.isdigit() and minutes.isdigit()):
        return None
    if len(minutes) != 2 or len(hours) > 2:
        return None
    return int(hours) * 60 + int(minutes)


def clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def format_window(start: int, end: int) -> str:
    return f"{clock(start)}-{clock(end)}"


def _fail(message: str) -> AppError:
    return AppError(400, _INVALID + message)


def _windows(value: Any, *, strict: bool) -> list[str]:
    """Valid windows sorted by start, overlapping or touching ones merged."""
    items = value if isinstance(value, list) else []
    parsed = [parse_window(item) for item in items]
    if strict and (None in parsed or len(items) > MAX_WINDOWS):
        raise _fail("Zeitfenster als HH:MM-HH:MM, höchstens vier pro Tag.")
    merged: list[list[int]] = []
    for start, end in sorted(window for window in parsed if window):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [format_window(start, end) for start, end in merged[:MAX_WINDOWS]]


def _bounded(value: Any, limits: tuple[int, int], *, strict: bool) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except TypeError, ValueError:
        number = limits[0] - 1
    if limits[0] <= number <= limits[1] and not isinstance(value, bool):
        return number
    if strict:
        raise _fail(f"Dauer zwischen {limits[0]} und {limits[1]} Minuten.")
    return None


def _fixed_session(value: Any, *, strict: bool) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or value.get("sport") not in SPORTS:
        if strict:
            raise _fail("Feste Einheit braucht Laufen, Rad oder Kraft.")
        return None
    sport = str(value["sport"])
    result: dict[str, Any] = {"sport": sport}
    focus = value.get("focus")
    if focus in FOCI[sport]:
        result["focus"] = focus
    elif focus and strict:
        raise _fail("Unbekannter Schwerpunkt der festen Einheit.")
    minutes = _bounded(value.get("minutes"), FIXED_MINUTES, strict=strict)
    if minutes is not None:
        result["minutes"] = minutes
    window = _windows([value["window"]], strict=strict) if value.get("window") else []
    if window:
        result["window"] = window[0]
    return result


def _fixed_sessions(value: Any, *, strict: bool) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    if strict and len(items) > MAX_FIXED:
        raise _fail("Höchstens vier feste Einheiten pro Tag.")
    sessions = (_fixed_session(item, strict=strict) for item in items[:MAX_FIXED])
    return [item for item in sessions if item]


def _day(value: Any, *, strict: bool) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    fixed = _fixed_sessions(source.get("fixed"), strict=strict)
    if source.get("rest_day") is True:
        if fixed and strict:
            raise _fail("Ein Ruhetag kann keine feste Einheit haben.")
        return {"rest_day": True} if not fixed else {"fixed": fixed}
    result: dict[str, Any] = {}
    windows = _windows(source.get("windows"), strict=strict)
    if windows:
        result["windows"] = windows
    minutes = _bounded(source.get("max_minutes"), MAX_DAY_MINUTES, strict=strict)
    if minutes is not None:
        result["max_minutes"] = minutes
    if fixed:
        result["fixed"] = fixed
    return result


def _load_payload(value: Any, *, strict: bool) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            value = None
    if isinstance(value, Mapping):
        return value
    if strict:
        raise _fail("Das Format ist unbekannt.")
    return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def normalize(value: Any, *, strict: bool = False) -> str:
    """Canonical JSON of a weekly plan, or ``""`` when nothing is set.

    ``strict`` rejects invalid input; otherwise invalid parts are dropped.
    """
    payload = _load_payload(value, strict=strict)
    given_days = _mapping(payload.get("days"))
    given_default = _mapping(payload.get("default"))
    days = {}
    default = {}
    for name in DAYS:
        content = _day(given_days.get(name), strict=strict)
        if content:
            days[name] = content
        windows = _windows(given_default.get(name), strict=strict)
        if windows:
            default[name] = windows
    result = {key: item for key, item in (("default", default), ("days", days)) if item}
    return (
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) if result else ""
    )


def effective_week(value: Any) -> list[EffectiveDay]:
    """The seven weekdays with effective windows and their source label."""
    payload = _load_payload(normalize(value), strict=False)
    days = payload.get("days", {})
    default = payload.get("default", {})
    return [_effective(name, days.get(name, {}), default.get(name)) for name in DAYS]


def _effective(name: str, day: Mapping[str, Any], default: Any) -> EffectiveDay:
    if day.get("windows"):
        windows, source = day["windows"], "profile"
    elif day.get("rest_day"):
        windows, source = [], "profile"
    elif default:
        windows, source = default, "default"
    else:
        windows, source = FALLBACK_WINDOWS[name], "fallback"
    return EffectiveDay(
        day=name,
        windows=tuple(windows),
        source=source,
        max_minutes=day.get("max_minutes"),
        rest_day=bool(day.get("rest_day")),
        fixed_sessions=tuple(day.get("fixed", ())),
    )


def effective_for_date(value: Any, when: date) -> EffectiveDay:
    """Effective windows, limit and fixed sessions on one calendar date."""
    return effective_week(value)[when.weekday()]


def brief(value: Any) -> list[dict[str, Any]]:
    """Per weekday effective windows with source, limits and fixed sessions."""
    return [item.as_dict() for item in effective_week(value)]
