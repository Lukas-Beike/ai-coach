"""Counts-only canonical stand-ins for the former snapshot list lengths.

Diagnostics must not carry athlete content, so only numbers leave this module.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.planning.compact_activities import (
    RECENT_ACTIVITY_LIMIT,
    compact_activity_rows,
)
from backend.runtime.ports import ActivityRowReader, ObservationReader

# The snapshot kept a bounded recent wellness list; count the same recent window.
_WELLNESS_WINDOW_DAYS: Final = 91

# Daily wellness metrics that Intervals.icu wellness rows map to. Weight and VO2max
# are left out: the athlete record also observes them on the sync day.
_WELLNESS_DAY_KINDS: Final = (
    MetricKind.BODY_FAT,
    MetricKind.RESTING_HR,
    MetricKind.HRV_RMSSD,
    MetricKind.HRV_SDNN,
    MetricKind.SLEEP_DURATION,
    MetricKind.SLEEP_SCORE,
    MetricKind.READINESS,
    MetricKind.CTL,
    MetricKind.ATL,
)


def activity_count(reader: ActivityRowReader | None, db: Any) -> int:
    """Return how many compact recent activities the canonical source serves."""
    if reader is None:
        return 0
    return len(
        compact_activity_rows(reader.activity_rows(db, limit=RECENT_ACTIVITY_LIMIT))
    )


def wellness_day_count(reader: ObservationReader | None, db: Any, today: date) -> int:
    """Return the Intervals.icu wellness days observed in the recent window."""
    if reader is None:
        return 0
    start = today - timedelta(days=_WELLNESS_WINDOW_DAYS)
    days = {
        observation.observed_on
        for kind in _WELLNESS_DAY_KINDS
        for observation in reader.observations(db, kind, start=start)
        if observation.provenance.provider == ProviderId.INTERVALS
    }
    return len(days)
