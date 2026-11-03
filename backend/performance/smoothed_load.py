"""Short- and long-term session-RPE load (M5): exponentially smoothed M1 AU.

Evidence card: ``docs/performance-methods/m5-smoothed-session-load.md``. The
input is the athlete's own M1 session-RPE load per local day; the recursion is
``E_t = exp(-1/tau) * E_(t-1) + (1 - exp(-1/tau)) * L_t`` with tau 7 and 42
days. The curve always starts at 0 AU on the day before the first recorded
session; a provider CTL/ATL never initialises it. A day without any session is
a rest day (0 AU) once it has passed; a day with an unrated or invalid session
is a gap: its load is unknown, the state is held and no value is shown. Values
are withheld during a warm-up of two tau from the first session and rounded
only for output. The result is a smoothed load, not measured fitness, form or
injury risk; no ratio of the two curves is formed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from backend.canonical.activity_summary import (
    ActivitySummary,
    stored_activity_key,
    summary_local_date,
)
from backend.performance.session_rpe_load import session_load

METRIC_ID: Final = "smoothed_session_load"
METHOD_ID: Final = "smoothed-session-load"
METHOD_VERSION: Final = 1
UNIT: Final = "AU"
EVIDENCE_CARD: Final = "docs/performance-methods/m5-smoothed-session-load.md"
SHORT_TAU_DAYS: Final = 7
LONG_TAU_DAYS: Final = 42
WARMUP_TAUS: Final = 2
# History before a period: the warm-up plus as many days again, so an established
# athlete has values from the first day and the start error is below 2 %.
LOOKBACK_DAYS: Final = 2 * WARMUP_TAUS * LONG_TAU_DAYS
METHOD_NOTE: Final = (
    "Short-term (tau 7 d) and long-term (tau 42 d) exponentially smoothed "
    "session-RPE load, from the athlete's daily AU. Starts at 0 AU at the "
    "first recorded session; values appear after a warm-up of two tau."
)
LIMITS: Final = (
    "Smoothed subjective load, not measured fitness, fatigue, form or injury "
    "risk. No ratio of the two curves, no ramp or readiness statement; never "
    "compared with or seeded from CTL, ATL, TSS, Garmin load or TRIMP. Days "
    "with unrated sessions are gaps: the value is withheld there, never "
    "estimated as zero."
)

TAUS: Final = {"short": SHORT_TAU_DAYS, "long": LONG_TAU_DAYS}

STATE_RATED: Final = "rated"
STATE_REST: Final = "rest"
STATE_GAP: Final = "gap"
STATE_OPEN: Final = "open"
STATE_NO_HISTORY: Final = "no_history"


def history_start(start: date, today: date) -> date:
    """First day of the history the recursion reads.

    Fixed by ``today`` for every period of the last 84 days, so Coach and UI seed
    the same day and show the same value for the same date.
    """
    return min(start - timedelta(days=LOOKBACK_DAYS), today - timedelta(days=251))


def complete_before(today: date, synced_at: str | None, timezone: str) -> date:
    """First day whose missing sessions are not yet known to be rest.

    The day of the last provider sync and later days may still lack sessions.
    """
    try:
        synced = datetime.fromisoformat(str(synced_at))
        if synced.tzinfo is None:
            return today
        return min(today, synced.astimezone(ZoneInfo(timezone)).date())
    except ValueError, KeyError:
        return today


def _daily_loads(
    summaries: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    start: date,
    end: date,
    timezone: str,
) -> dict[str, float | None]:
    """AU per local day with a session; ``None`` if any session of it is unrated."""
    days: dict[str, float | None] = {}
    sums: dict[str, list[float]] = {}
    for summary in summaries:
        day = summary_local_date(summary, timezone)
        if not start.isoformat() <= day <= end.isoformat():
            continue
        _entry, value = session_load(
            summary, feedback.get(stored_activity_key(summary)), timezone
        )
        sums.setdefault(day, [])
        if value is None:
            days[day] = None
        elif days.get(day, 0.0) is not None:
            sums[day].append(value)
            days[day] = math.fsum(sums[day])
    return days


def _reason(valued: Sequence[Any], first: date | None) -> str | None:
    if valued:
        return None
    return "warmup" if first else "no_sessions"


def _no_history_days(start: date, last: date) -> list[dict[str, Any]]:
    return [
        {"date": day.isoformat(), "state": STATE_NO_HISTORY, "load": None}
        | {name: None for name in TAUS}
        for day in (start + timedelta(days=i) for i in range((last - start).days + 1))
    ]


def _day_load(
    loads: Mapping[str, float | None], cursor: date, open_from: date
) -> tuple[float | None, str]:
    key = cursor.isoformat()
    if key in loads:
        return loads[key], STATE_RATED if loads[key] is not None else STATE_GAP
    if cursor >= open_from:
        return None, STATE_OPEN
    return 0.0, STATE_REST


def _walk(
    loads: Mapping[str, float | None],
    first: date,
    start: date,
    end: date,
    open_from: date,
) -> list[dict[str, Any]]:
    """Run both recursions from ``first`` and list the days of ``start``..``end``."""
    state = {name: 0.0 for name in TAUS}
    days: list[dict[str, Any]] = []
    for offset in range((end - first).days + 1):
        cursor = first + timedelta(days=offset)
        load, kind = _day_load(loads, cursor, open_from)
        if load is not None:
            for name, tau in TAUS.items():
                decay = math.exp(-1 / tau)
                state[name] = decay * state[name] + (1 - decay) * load
        if cursor < start:
            continue
        values = {
            name: None
            if load is None or offset < WARMUP_TAUS * tau
            else round(state[name], 1)
            for name, tau in TAUS.items()
        }
        days.append(
            {
                "date": cursor.isoformat(),
                "state": kind,
                "load": None if load is None else round(load, 1),
                **values,
            }
        )
    return days


def smoothed_session_load(
    summaries: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    *,
    start: date,
    end: date,
    today: date,
    complete_before: date | None = None,
    timezone: str,
    computed_at: str | None = None,
) -> dict[str, Any]:
    """Smoothed load per local day of ``start``..``end``.

    ``summaries`` should reach back to ``history_start``; sessions before it are
    ignored. A day from ``complete_before`` (default ``today``) on has no value unless a session is
    recorded, since a missing session is not yet a rest day.
    """
    loads = _daily_loads(
        summaries, feedback, history_start(start, today), end, timezone
    )
    first = date.fromisoformat(min(loads)) if loads else None
    days = _no_history_days(start, end if first is None else first - timedelta(days=1))
    if first is not None:
        days += _walk(loads, first, start, end, complete_before or today)
    valued = [
        day for day in days if day["short"] is not None or day["long"] is not None
    ]
    counts = {
        name: sum(day["state"] == name for day in days)
        for name in (STATE_RATED, STATE_REST, STATE_GAP, STATE_OPEN, STATE_NO_HISTORY)
    }
    return {
        "metric_id": METRIC_ID,
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "unit": UNIT,
        "status": "estimate" if valued else "insufficient_data",
        "reason": _reason(valued, first),
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone,
        },
        "computed_at": computed_at,
        "method": METHOD_NOTE,
        "limits": LIMITS,
        "evidence_card": EVIDENCE_CARD,
        "parameters": {
            "short_tau_days": SHORT_TAU_DAYS,
            "long_tau_days": LONG_TAU_DAYS,
            "warmup_days": {name: WARMUP_TAUS * tau for name, tau in TAUS.items()},
            "start_state_au": 0,
            "first_session_date": None if first is None else first.isoformat(),
        },
        "coverage": counts,
        "latest": valued[-1] if valued else None,
        "days": days,
    }
