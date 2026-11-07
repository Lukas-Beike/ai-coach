"""Stateless performance load context composition.

Fitness, fatigue and form come only from the local curve (card M7,
``backend.performance.fitness_fatigue``) over the stored local load. The stored
Intervals.icu CTL, ATL and form stay a separately labelled history and never
enter a local value.
"""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Final

from backend.activities.sync_time import activities_synced_at
from backend.performance import load as performance_load
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.fitness_fatigue import SOURCE_LABEL, local_fitness_fatigue
from backend.performance.load import SessionFeedback
from backend.performance.smoothed_load import complete_before
from backend.runtime.ports import LocalLoadDayReader

LOCAL_LOAD_SOURCE: Final = SOURCE_LABEL
INTERVALS_HISTORY_SOURCE: Final = "Intervals.icu (gespeichert, nicht lokal)"
# The days the current local values and their averages are read from.
CURRENT_DAYS: Final = 7


def read_local_fitness(
    reader: Any,
    db: Any,
    *,
    start: date,
    end: date,
    today: date,
    timezone: str,
) -> dict[str, Any]:
    """The local curve (M7) of ``start``..``end`` read through ``reader``.

    ``reader`` serves the stored load days (``LocalLoadDayReader``) and, when it
    can, the provider coverage whose activities sync time marks the open days,
    as the load tab does; without a sync time the days before ``today`` count.
    No session marks are read.
    """
    days = reader.local_load_days(db) if isinstance(reader, LocalLoadDayReader) else {}
    coverage = reader if callable(getattr(reader, "coverage", None)) else None
    return local_fitness_fatigue(
        days,
        (),
        {},
        start=start,
        end=end,
        today=today,
        complete_before=complete_before(
            today, activities_synced_at(coverage, db), timezone
        ),
        timezone=timezone,
    )


def local_fitness_curve(
    canonical: CanonicalPerformanceInputs,
    activities: list[Any],
    today: date,
    *,
    timezone: str,
    session_feedback: SessionFeedback | None = None,
    days: int = CURRENT_DAYS,
) -> dict[str, Any]:
    """The local fitness, fatigue and form (M7) of the last ``days`` days."""
    return local_fitness_fatigue(
        canonical.local_load_days or {},
        activities,
        session_feedback or {},
        start=today - timedelta(days=days - 1),
        end=today,
        today=today,
        complete_before=complete_before(
            today, canonical.activities_synced_at, timezone
        ),
        timezone=timezone,
    )


def _average(days: list[Mapping[str, Any]], key: str) -> float | None:
    values = [float(day[key]) for day in days if day.get(key) is not None]
    return round(sum(values) / len(values), 2) if values else None


def _current_load(curve: Mapping[str, Any]) -> dict[str, Any]:
    latest = curve.get("latest") or {}
    days = list(curve.get("days") or [])
    incomplete = sum(day.get("state") == "incomplete" for day in days)
    return {
        "id": latest.get("date"),
        "ctl": latest.get("fitness"),
        "atl": latest.get("fatigue"),
        "tsb": latest.get("form"),
        "source": LOCAL_LOAD_SOURCE,
        "method_id": curve.get("method_id"),
        "method_version": curve.get("method_version"),
        "status": curve.get("status"),
        **({"reason": curve["reason"]} if curve.get("reason") else {}),
        **({"incomplete_days_7d": incomplete} if incomplete else {}),
        "averages_7d": {
            "ctl": _average(days, "fitness"),
            "atl": _average(days, "fatigue"),
            "tsb": _average(days, "form"),
        },
    }


def _intervals_history(canonical: CanonicalPerformanceInputs) -> dict[str, Any] | None:
    """The stored Intervals.icu values of its latest wellness day, labelled."""
    if canonical.wellness_day is None:
        return None
    form = (canonical.form_by_day or {}).get(canonical.wellness_day)
    if canonical.ctl is None and canonical.atl is None and form is None:
        return None
    return {
        "as_of": canonical.wellness_day.isoformat(),
        "ctl": canonical.ctl,
        "atl": canonical.atl,
        "tsb": form,
        "source": INTERVALS_HISTORY_SOURCE,
    }


def performance_load_context(
    activities: list[Any],
    today: date,
    *,
    canonical: CanonicalPerformanceInputs,
    timezone: str,
    session_feedback: SessionFeedback | None = None,
) -> dict[str, Any]:
    """Load rollups, the local fitness (M7) and the labelled Intervals history.

    ``session_feedback`` as ``activity_rollup``.
    """
    feedback = session_feedback or {}
    last_7 = performance_load.activity_rollup(
        activities, 7, today, session_feedback=feedback
    )
    previous_7 = performance_load.activity_rollup(
        activities, 7, today - timedelta(days=7), session_feedback=feedback
    )
    last_30 = performance_load.activity_rollup(
        activities, 30, today, session_feedback=feedback
    )
    previous_30 = performance_load.activity_rollup(
        activities, 30, today - timedelta(days=30), session_feedback=feedback
    )
    curve = local_fitness_curve(
        canonical,
        activities,
        today,
        timezone=timezone,
        session_feedback=feedback,
    )
    return {
        "load": _current_load(curve),
        "intervals_history": _intervals_history(canonical),
        "last_7": last_7,
        "previous_7": previous_7,
        "last_30": last_30,
        "previous_30": previous_30,
    }
