"""The athlete's estimated first threshold from per-session DFA-a1 results.

Each session with a chest-strap recording that carried RR intervals may hold an
estimate in bpm (``dfa_alpha1``). The athlete-level value is the median over the
sessions of the last 60 days, each expressed as percent of the run threshold HR
in effect on its own date (like the measured ``first_threshold_pct``), so a later
threshold change moves neither. It needs at least three qualifying sessions. Only
sessions whose own quality is good qualify. It is research-grade, an estimate
for the athlete to review, and it never replaces a measured value by itself.

Pure; stdlib and canonical records only.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.first_threshold import percent_of_lthr
from backend.canonical.vocabulary import DfaQuality

ESTIMATE_DAYS: Final = 60
MIN_SESSIONS: Final = 3
# The estimate is good with this many sessions that agree within this spread
# (percentage points of the threshold HR); otherwise it is low.
GOOD_MIN_SESSIONS: Final = 5
GOOD_MAX_SPREAD_PCT: Final = 5.0
SOURCE_LABEL: Final = (
    "Schätzung aus Brustgurt-RR-Intervallen (DFA-α1, Forschungsstand), kein Laborwert"
)


@dataclass(frozen=True, slots=True)
class SessionThreshold:
    """One session's estimate in bpm on its local day, with its own quality."""

    day: date
    bpm: float
    quality: DfaQuality


@dataclass(frozen=True, slots=True)
class FirstThresholdEstimate:
    """The athlete-level estimate: percent of the threshold HR and its basis."""

    percent_lthr: float
    sessions: int
    quality: DfaQuality
    first_day: date
    last_day: date
    spread_pct: float


def first_threshold_estimate(
    sessions: Iterable[SessionThreshold],
    lthr_on: Callable[[date], float | None],
    today: date,
) -> FirstThresholdEstimate | None:
    """The median over the qualifying sessions of the last 60 days, or None.

    A session qualifies with good quality, a day in the window and a known run
    threshold HR on that day that makes its value a plausible percent.
    """
    since = today - timedelta(days=ESTIMATE_DAYS - 1)
    values: list[tuple[date, float]] = []
    for session in sessions:
        if session.quality is not DfaQuality.GOOD or not since <= session.day <= today:
            continue
        lthr = lthr_on(session.day)
        if lthr is None or not math.isfinite(lthr):
            continue
        percent = percent_of_lthr(session.bpm, lthr)
        if percent is not None:
            values.append((session.day, percent))
    if len(values) < MIN_SESSIONS:
        return None
    percents = [percent for _, percent in values]
    spread = max(percents) - min(percents)
    good = len(values) >= GOOD_MIN_SESSIONS and spread <= GOOD_MAX_SPREAD_PCT
    return FirstThresholdEstimate(
        percent_lthr=round(statistics.median(percents), 1),
        sessions=len(values),
        quality=DfaQuality.GOOD if good else DfaQuality.LOW,
        first_day=min(day for day, _ in values),
        last_day=max(day for day, _ in values),
        spread_pct=round(spread, 1),
    )


def estimate_view(
    estimate: FirstThresholdEstimate | None, run_lthr: float | None
) -> dict[str, Any] | None:
    """The estimate as shown to the athlete and the Coach; None without one.

    ``bpm`` resolves the percent with today's run threshold HR (None when none
    is known). The label says what the value is.
    """
    if estimate is None:
        return None
    bpm = (
        None
        if run_lthr is None or run_lthr <= 0
        else math.floor(estimate.percent_lthr * run_lthr / 100 + 0.5)
    )
    return {
        "percent_lthr": estimate.percent_lthr,
        "bpm": bpm,
        "sessions": estimate.sessions,
        "quality": estimate.quality.value,
        "from": estimate.first_day.isoformat(),
        "to": estimate.last_day.isoformat(),
        "spread_pct": estimate.spread_pct,
        "source": SOURCE_LABEL,
    }
