"""Bounded observed cycling best efforts from Intervals.icu power curves."""

from datetime import date
from typing import Any

from backend.errors import AppError

PROFILE_DURATIONS = (5, 60, 300, 1200, 3600)


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


def cycling_power_points(payload: Any, start: date, end: date) -> list[dict[str, Any]]:
    """Normalize the documented activity-power-curves payload, without estimates."""
    if not isinstance(payload, dict):
        raise AppError(502, "Ungültiges Rad-Leistungsprofil vom Anbieter.")
    durations, curves = payload.get("secs"), payload.get("curves")
    if not isinstance(durations, list) or not isinstance(curves, list):
        raise AppError(502, "Ungültiges Rad-Leistungsprofil vom Anbieter.")
    best: dict[int, dict[str, Any]] = {}
    for curve in curves:
        if not isinstance(curve, dict):
            continue
        day = _curve_day(curve, start, end)
        watts = curve.get("watts")
        if day is None or not isinstance(watts, list) or len(watts) != len(durations):
            continue
        for duration, value in zip(durations, watts, strict=True):
            if not _valid_power(duration, value):
                continue
            if duration not in best or value > best[duration]["watts"]:
                best[duration] = {
                    "duration_seconds": duration,
                    "watts": value,
                    "date": day.isoformat(),
                    "activity_id": str(curve.get("id") or "")[:200],
                    "source": "Intervals.icu gemessene Leistungskurve",
                    "status": "ok",
                }
    return [best[key] for key in sorted(best)]
