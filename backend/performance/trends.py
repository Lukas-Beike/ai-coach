"""Historical performance averages from canonical days and Garmin history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.vocabulary import MetricKind
from backend.performance import activity_validation
from backend.performance.wellness_days import WellnessDay


def garmin_history_average(
    snapshot: dict[str, Any],
    key: str,
    days: int,
    end_date: date,
    history: Mapping[str, Mapping[date, float]] | None = None,
) -> float | None:
    """Average a Garmin metric over ``days`` using canonical history when given."""
    cutoff = end_date - timedelta(days=days - 1)
    if history is not None:
        numbers = [
            float(value)
            for day, value in history.get(key, {}).items()
            if cutoff <= day <= end_date
        ]
        return round(sum(numbers) / len(numbers), 2) if numbers else None
    values: list[float] = []
    rows = (
        snapshot.get("performance_history")
        if isinstance(snapshot.get("performance_history"), list)
        else []
    )
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            item_date = date.fromisoformat(iso_date_prefix(str(item.get("date"))))
        except TypeError, ValueError:
            continue
        if not cutoff <= item_date <= end_date:
            continue
        value = _as_number((item.get("metrics") or {}).get(key))
        if value is not None:
            values.append(float(value))
    return round(sum(values) / len(values), 2) if values else None


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
