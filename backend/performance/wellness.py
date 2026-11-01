"""Pure wellness projections used by the performance context."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.vocabulary import MetricKind
from backend.performance.recovery import rounded_average
from backend.performance.wellness_days import WellnessDay


def wellness_window_values(
    days_view: tuple[WellnessDay, ...],
    kind: MetricKind,
    days: int,
    end_date: date,
    divisor: float = 1.0,
) -> list[tuple[date, float]]:
    """Dated numbers of the inclusive, anchored window behind the wellness average."""
    cutoff = end_date - timedelta(days=days - 1)
    values: list[tuple[date, float]] = []
    for item in days_view:
        if item.day < cutoff or item.day > end_date:
            continue
        value = item.value(kind)
        if value is not None:
            values.append((item.day, float(value) / divisor))
    return values


def wellness_average(
    days_view: tuple[WellnessDay, ...],
    kind: MetricKind,
    days: int,
    end_date: date,
    divisor: float = 1.0,
) -> float | None:
    """Average a wellness field over the inclusive, anchored date window."""
    values = wellness_window_values(days_view, kind, days, end_date, divisor)
    return rounded_average([value for _, value in values])


def comparison_value(
    current: Any,
    average: Any,
    unit: str,
    days: int,
    higher_is_better: bool | None = True,
    label: str | None = None,
) -> dict[str, Any] | None:
    """Project a current value and its historical average for the Coach."""
    current_number = _as_number(current)
    average_number = _as_number(average)
    if current_number is None or average_number is None:
        return None
    delta = round(float(current_number) - float(average_number), 2)
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"
    if higher_is_better is None:
        good = False
    elif higher_is_better:
        good = delta > 0
    else:
        good = delta < 0
    if good:
        color = "good"
    elif delta and higher_is_better is not None:
        color = "bad"
    else:
        color = "neutral"
    return {
        "current": current_number,
        "average": average_number,
        "delta": delta,
        "unit": unit,
        "days": days,
        "direction": direction,
        "color": color,
        "label": label or f"{days}-Tage-Durchschnitt",
    }


def wellness_form_average(
    form_by_day: Mapping[date, float] | None, days: int, end_date: date
) -> float | None:
    """Average the form observations of the inclusive window ending on ``end_date``."""
    cutoff = end_date - timedelta(days=days - 1)
    values = [
        value for day, value in (form_by_day or {}).items() if cutoff <= day <= end_date
    ]
    return round(sum(values) / len(values), 2) if values else None
