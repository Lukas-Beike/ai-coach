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
from datetime import date, timedelta
from typing import Any, Final

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
# Days of history before a period that the recursion needs for the long curve.
LOOKBACK_DAYS: Final = WARMUP_TAUS * LONG_TAU_DAYS
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

STATE_RATED: Final = "rated"
STATE_REST: Final = "rest"
STATE_GAP: Final = "gap"
STATE_OPEN: Final = "open"
STATE_NO_HISTORY: Final = "no_history"


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


def smoothed_session_load(
    summaries: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    *,
    start: date,
    end: date,
    today: date,
    timezone: str,
    computed_at: str | None = None,
) -> dict[str, Any]:
    """Smoothed load per local day of ``start``..``end``.

    ``summaries`` should reach back ``LOOKBACK_DAYS`` before ``start``; sessions
    outside ``start - LOOKBACK_DAYS``..``end`` are ignored. ``today`` is still
    open: it has no value unless a session is recorded, since a missing session
    is not yet a rest day.
    """
    history_start = start - timedelta(days=LOOKBACK_DAYS)
    loads = _daily_loads(summaries, feedback, history_start, end, timezone)
    first = date.fromisoformat(min(loads)) if loads else None
    taus = {"short": SHORT_TAU_DAYS, "long": LONG_TAU_DAYS}
    state = {name: 0.0 for name in taus}
    days: list[dict[str, Any]] = []
    cursor = first or start
    while cursor <= end:
        key = cursor.isoformat()
        if key in loads:
            load = loads[key]
            kind = STATE_RATED if load is not None else STATE_GAP
        elif cursor == today:
            load, kind = None, STATE_OPEN
        else:
            load, kind = 0.0, STATE_REST
        if load is not None:
            for name, tau in taus.items():
                decay = math.exp(-1 / tau)
                state[name] = decay * state[name] + (1 - decay) * load
        if cursor >= start:
            elapsed = (cursor - first).days if first else 0
            days.append(
                {
                    "date": key,
                    "state": kind,
                    "load": None if load is None else round(load, 1),
                    **{
                        name: round(state[name], 1)
                        if load is not None and elapsed >= WARMUP_TAUS * tau
                        else None
                        for name, tau in taus.items()
                    },
                }
            )
        cursor += timedelta(days=1)
    if first is None:
        days = [
            {"date": day.isoformat(), "state": STATE_NO_HISTORY, "load": None}
            | {name: None for name in taus}
            for day in (
                start + timedelta(days=i) for i in range((end - start).days + 1)
            )
        ]
    elif first > start:
        days = [
            {"date": day.isoformat(), "state": STATE_NO_HISTORY, "load": None}
            | {name: None for name in taus}
            for day in (start + timedelta(days=i) for i in range((first - start).days))
        ] + days
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
        "reason": None if valued else ("no_sessions" if first is None else "warmup"),
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
            "warmup_days": {name: WARMUP_TAUS * tau for name, tau in taus.items()},
            "start_state_au": 0,
            "first_session_date": None if first is None else first.isoformat(),
        },
        "coverage": counts,
        "latest": valued[-1] if valued else None,
        "days": days,
    }
