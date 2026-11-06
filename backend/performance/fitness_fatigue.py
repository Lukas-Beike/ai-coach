"""Local fitness, fatigue and form (M7) from the local TSS-scale load (M6).

Evidence card: ``docs/performance-methods/m7-local-fitness-fatigue.md``. The
input is the stored local session load per athlete-local day over the whole
stored history; the recursion is
``E_t = exp(-1/tau) * E_(t-1) + (1 - exp(-1/tau)) * L_t`` with tau 42 days
(fitness) and 7 days (fatigue), and form is fitness minus fatigue of the same
day. The curves start at 0 on the day before the first day with a local load;
a provider CTL, ATL or form never initialises or corrects them. A past day
without any session is a rest day (load 0). A day with a session that has no
local load (strength, yoga, alpine ski, walking, missing inputs) adds nothing
for that session and is marked incomplete with the session count and its
session-RPE AU beside, never converted. Days from the last provider sync on
without a session are open: no value, state unchanged. Values are withheld
during a warm-up of two tau from the first load day and rounded only for
output. Computed on read, never stored.
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
from backend.performance.local_tss import METHOD_ID as LOAD_METHOD_ID
from backend.performance.local_tss import METHOD_VERSION as LOAD_METHOD_VERSION
from backend.performance.session_rpe_load import session_load

METRIC_ID: Final = "local_fitness_fatigue"
METHOD_ID: Final = "local-fitness-fatigue"
METHOD_VERSION: Final = 1
UNIT: Final = "TSS/d"
EVIDENCE_CARD: Final = "docs/performance-methods/m7-local-fitness-fatigue.md"
FITNESS_TAU_DAYS: Final = 42
FATIGUE_TAU_DAYS: Final = 7
WARMUP_TAUS: Final = 2
METHOD_NOTE: Final = (
    "Fitness (tau 42 d), fatigue (tau 7 d) and form (fitness minus fatigue) from "
    "the local TSS-scale session load of the whole stored history. Starts at 0 "
    "before the first day with a local load; values appear after a warm-up of "
    "two tau."
)
LIMITS: Final = (
    "Model estimate from the local load, not measured fitness, fatigue or "
    "readiness and no performance, race-time or injury-risk prediction. Never "
    "seeded from or mixed with Intervals.icu CTL, ATL or form. Sessions without "
    "a local load (strength, yoga, alpine ski, walking, missing inputs) add "
    "nothing; their days are marked incomplete."
)

TAUS: Final = {"fitness": FITNESS_TAU_DAYS, "fatigue": FATIGUE_TAU_DAYS}

STATE_LOADED: Final = "loaded"
STATE_INCOMPLETE: Final = "incomplete"
STATE_REST: Final = "rest"
STATE_OPEN: Final = "open"
STATE_NO_HISTORY: Final = "no_history"
STATES: Final = (
    STATE_LOADED,
    STATE_INCOMPLETE,
    STATE_REST,
    STATE_OPEN,
    STATE_NO_HISTORY,
)


def _has_load(summary: Mapping[str, Any]) -> bool:
    try:
        return math.isfinite(float(summary.get("training_load")))  # type: ignore[arg-type]
    except TypeError, ValueError:
        return False


def _without_load(
    summaries: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    start: date,
    end: date,
    timezone: str,
) -> dict[str, tuple[int, list[float]]]:
    """Per local day: sessions without a local load and their rated sRPE AU."""
    days: dict[str, tuple[int, list[float]]] = {}
    for summary in summaries:
        day = summary_local_date(summary, timezone)
        if not start.isoformat() <= day <= end.isoformat() or _has_load(summary):
            continue
        _entry, au = session_load(
            summary, feedback.get(stored_activity_key(summary)), timezone
        )
        count, values = days.get(day, (0, []))
        days[day] = (count + 1, values + ([] if au is None else [au]))
    return days


def _day(
    cursor: date,
    loads: Mapping[str, float],
    missing: Mapping[str, tuple[int, list[float]]],
    open_from: date,
) -> tuple[float | None, str]:
    key = cursor.isoformat()
    if key in missing:
        return loads.get(key, 0.0), STATE_INCOMPLETE
    if key in loads:
        return loads[key], STATE_LOADED
    if cursor >= open_from:
        return None, STATE_OPEN
    return 0.0, STATE_REST


def _row(
    cursor: date,
    kind: str,
    load: float | None,
    values: Mapping[str, float | None],
    missing: tuple[int, list[float]] | None,
) -> dict[str, Any]:
    fitness, fatigue = values["fitness"], values["fatigue"]
    row: dict[str, Any] = {
        "date": cursor.isoformat(),
        "state": kind,
        "load": None if load is None else round(load, 1),
        "fitness": None if fitness is None else round(fitness, 1),
        "fatigue": None if fatigue is None else round(fatigue, 1),
        "form": None
        if fitness is None or fatigue is None
        else round(fitness - fatigue, 1),
    }
    if missing is not None:
        count, au = missing
        row["sessions_without_load"] = count
        row["session_rpe_au_without_load"] = round(math.fsum(au), 1) if au else None
    return row


def _walk(
    loads: Mapping[str, float],
    missing: Mapping[str, tuple[int, list[float]]],
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
        load, kind = _day(cursor, loads, missing, open_from)
        if load is not None:
            for name, tau in TAUS.items():
                decay = math.exp(-1 / tau)
                state[name] = decay * state[name] + (1 - decay) * load
        if cursor < start:
            continue
        values = {
            name: None if load is None or offset < WARMUP_TAUS * tau else state[name]
            for name, tau in TAUS.items()
        }
        days.append(_row(cursor, kind, load, values, missing.get(cursor.isoformat())))
    return days


def _no_history_days(
    start: date, last: date, missing: Mapping[str, tuple[int, list[float]]]
) -> list[dict[str, Any]]:
    """Days before the first load day; sessions without a load still mark them."""
    empty = {"fitness": None, "fatigue": None}
    return [
        _row(day, STATE_NO_HISTORY, None, empty, missing.get(day.isoformat()))
        for day in (start + timedelta(days=i) for i in range((last - start).days + 1))
    ]


def local_fitness_fatigue(
    loads: Mapping[str, float],
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
    """Local fitness, fatigue and form per local day of ``start``..``end``.

    ``loads`` is the stored local load per local ISO day of the whole history
    (``LocalLoadDayReader``). ``summaries`` should cover ``start``..``end``; they
    only mark the days whose sessions have no local load. A day from
    ``complete_before`` (default ``today``) on without a session has no value.
    """
    missing = _without_load(summaries, feedback, start, end, timezone)
    loaded_days = [day for day, value in loads.items() if day <= end.isoformat()]
    first = date.fromisoformat(min(loaded_days)) if loaded_days else None
    days = _no_history_days(
        start, end if first is None else first - timedelta(days=1), missing
    )
    if first is not None:
        days += _walk(loads, missing, first, start, end, complete_before or today)
    valued = [
        day for day in days if day["fitness"] is not None or day["fatigue"] is not None
    ]
    return {
        "metric_id": METRIC_ID,
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "unit": UNIT,
        "status": "estimate" if valued else "insufficient_data",
        "reason": None if valued else ("warmup" if first else "no_load"),
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
            "fitness_tau_days": FITNESS_TAU_DAYS,
            "fatigue_tau_days": FATIGUE_TAU_DAYS,
            "warmup_days": {name: WARMUP_TAUS * tau for name, tau in TAUS.items()},
            "start_state": 0,
            "first_load_date": None if first is None else first.isoformat(),
            "load_method_id": LOAD_METHOD_ID,
            "load_method_version": LOAD_METHOD_VERSION,
        },
        "coverage": {
            name: sum(day["state"] == name for day in days) for name in STATES
        },
        "sessions_without_load": sum(
            day.get("sessions_without_load", 0) for day in days
        ),
        "latest": valued[-1] if valued else None,
        "days": days,
    }
