"""Pure wellness projections used by the performance context."""

from __future__ import annotations

from typing import Any

from backend.canonical.decimal_text import provider_number as _as_number


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
