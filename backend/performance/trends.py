"""Historical performance averages from canonical days and Garmin history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from backend.canonical.vocabulary import MetricKind
from backend.performance import activity_validation
from backend.performance.wellness_days import WellnessDay


def garmin_history_average(
    key: str,
    days: int,
    end_date: date,
    history: Mapping[str, Mapping[date, float]],
) -> float | None:
    """Average a Garmin metric's canonical day history over ``days``."""
    cutoff = end_date - timedelta(days=days - 1)
    numbers = [
        float(value)
        for day, value in history.get(key, {}).items()
        if cutoff <= day <= end_date
    ]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def intervals_performance_average(
    days_view: tuple[WellnessDay, ...],
    run_eftp_by_day: Mapping[date, float] | None,
    key: str,
    days: int,
    end_date: date,
) -> float | None:
    """Average supported Intervals metrics over an inclusive calendar window."""
    cutoff = end_date - timedelta(days=days - 1)
    candidates: Iterable[tuple[date, float | None]]
    if key == "run_threshold_watts":
        candidates = (run_eftp_by_day or {}).items()
    else:
        kind = {"weight_kg": MetricKind.WEIGHT, "readiness": MetricKind.READINESS}.get(
            key
        )
        if kind is None:
            return None
        candidates = ((item.day, item.value(kind)) for item in days_view)
    values = [
        float(bounded)
        for day, value in candidates
        if cutoff <= day <= end_date
        if (bounded := activity_validation.bounded_performance_metric(key, value))
        is not None
    ]
    return round(sum(values) / len(values), 2) if values else None
