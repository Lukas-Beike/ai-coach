"""Pure wellness projections used by the performance context."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def wellness_average(
    rows: list[dict[str, Any]],
    keys: tuple[str, ...],
    days: int,
    end_date: date,
    divisor: float = 1.0,
) -> float | None:
    """Average a wellness field over the inclusive, anchored date window."""
    cutoff = end_date - timedelta(days=days - 1)
    values: list[float] = []
    for row in rows:
        try:
            row_date = date.fromisoformat(
                str(row.get("id") or row.get("date") or "")[:10]
            )
        except ValueError:
            continue
        if row_date < cutoff or row_date > end_date:
            continue
        value = _as_number(_first_present(row, keys))
        if value is not None:
            values.append(float(value) / divisor)
    return round(sum(values) / len(values), 2) if values else None


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


def wellness_form_value(row: Any) -> float | int | None:
    """Return direct Intervals form/TSB/freshness, or derive CTL minus ATL."""
    if not isinstance(row, dict):
        return None
    direct = _as_number(_first_present(row, ("tsb", "form", "freshness")))
    if direct is not None:
        return direct
    ctl = _as_number(_first_present(row, ("ctl",)))
    atl = _as_number(_first_present(row, ("atl",)))
    if ctl is None or atl is None:
        return None
    return round(float(ctl) - float(atl), 2)


def readiness_score_value(value: Any) -> float | int | None:
    """Extract a scalar readiness score from nested provider payloads."""
    if isinstance(value, list):
        dated = [item for item in value if isinstance(item, dict)]
        if not dated:
            return None
        dated.sort(
            key=lambda item: str(
                _first_present(item, ("calendarDate", "date", "id", "timestamp")) or ""
            )
        )
        return readiness_score_value(dated[-1])
    if isinstance(value, dict):
        direct = _first_present(
            value,
            (
                "readiness",
                "readinessScore",
                "readiness_score",
                "trainingReadiness",
                "training_readiness",
                "score",
                "value",
            ),
        )
        if isinstance(direct, (dict, list)):
            return readiness_score_value(direct)
        return _as_number(direct)
    return _as_number(value)


def wellness_form_average(
    rows: list[dict[str, Any]], days: int, end_date: date
) -> float | None:
    """Average form/TSB over the inclusive, anchored date window."""
    cutoff = end_date - timedelta(days=days - 1)
    values: list[float] = []
    for row in rows:
        try:
            row_date = date.fromisoformat(
                str(row.get("id") or row.get("date") or "")[:10]
            )
        except ValueError:
            continue
        if row_date < cutoff or row_date > end_date:
            continue
        value = wellness_form_value(row)
        if value is not None:
            values.append(float(value))
    return round(sum(values) / len(values), 2) if values else None
