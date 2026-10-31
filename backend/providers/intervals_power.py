"""Bounded observed cycling best efforts from Intervals.icu power curves."""

from datetime import date
from typing import Any

from backend.errors import AppError

PROFILE_DURATIONS = (5, 60, 300, 1200, 3600)
POWER_CURVE_LABEL = "Intervals.icu gemessene Leistungskurve"


def _curve_day(curve: dict[str, Any], start: date, end: date) -> date | None:
    try:
        day = date.fromisoformat(str(curve.get("start_date_local"))[:10])
    except ValueError:
        return None
    return day if start <= day <= end else None


def _valid_power(duration: Any, value: Any) -> bool:
    return (
        type(duration) is int
        and duration in PROFILE_DURATIONS
        and type(value) in {int, float}
        and 0 <= value <= 5000
    )


def _curve_samples(
    curve: Any, durations: list[Any], start: date, end: date
) -> list[tuple[date, int, int | float]]:
    if not isinstance(curve, dict):
        return []
    day = _curve_day(curve, start, end)
    watts = curve.get("watts")
    if day is None or not isinstance(watts, list) or len(watts) != len(durations):
        return []
    return [
        (day, duration, value)
        for duration, value in zip(durations, watts, strict=True)
        if _valid_power(duration, value)
    ]


def cycling_power_points(payload: Any, start: date, end: date) -> list[dict[str, Any]]:
    """Normalize the documented activity-power-curves payload, without estimates."""
    if not isinstance(payload, dict):
        raise AppError(502, "Ungültiges Rad-Leistungsprofil vom Anbieter.")
    durations, curves = payload.get("secs"), payload.get("curves")
    if not isinstance(durations, list) or not isinstance(curves, list):
        raise AppError(502, "Ungültiges Rad-Leistungsprofil vom Anbieter.")
    best: dict[int, dict[str, Any]] = {}
    for curve in curves:
        for day, duration, value in _curve_samples(curve, durations, start, end):
            if duration not in best or value > best[duration]["watts"]:
                best[duration] = {
                    "duration_seconds": duration,
                    "watts": value,
                    "date": day.isoformat(),
                    "activity_id": str(curve.get("id") or "")[:200],
                    "source": POWER_CURVE_LABEL,
                    "status": "ok",
                }
    return [best[key] for key in sorted(best)]
