"""Bounded observed cycling best efforts from Intervals.icu power curves."""

from datetime import date
from typing import Any

from backend.errors import AppError

PROFILE_DURATIONS = (5, 60, 300, 1200, 3600)


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
        try:
            day = date.fromisoformat(str(curve.get("start_date_local"))[:10])
        except ValueError:
            continue
        watts = curve.get("watts")
        if (
            not start <= day <= end
            or not isinstance(watts, list)
            or len(watts) != len(durations)
        ):
            continue
        for duration, value in zip(durations, watts, strict=True):
            if type(duration) is not int or duration not in PROFILE_DURATIONS:
                continue
            if type(value) not in {int, float} or not 0 <= value <= 5000:
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
