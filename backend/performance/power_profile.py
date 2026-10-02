"""Observed time-weighted cycling best power; no inferred FTP or CP model."""

from bisect import bisect_right
from typing import Any

from backend.performance.session_analysis import _number


def power_profile(activity: dict[str, Any]) -> dict[str, Any]:
    base = {
        "method": "original-stream-integral-v1",
        "source": "Intervals.icu original watts stream",
        "scope": "Observed best means in this recording; no FTP, CP or W-prime estimate.",
    }
    streams = activity.get("streams") or {}
    times, watts = streams.get("time") or [], streams.get("watts") or []
    if (
        activity.get("type") not in {"Ride", "VirtualRide"}
        or len(times) < 2
        or len(times) != len(watts)
    ):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Vollständige Rad-Leistungsmessreihe fehlt.",
            "points": [],
        }
    energy, coverage, rates = _power_integrals(times, watts, streams.get("moving"))
    points = []
    for duration in (5, 60, 300, 1200):
        points.append(_best_power_point(times, energy, coverage, rates, duration))
    return {
        **base,
        "status": "ok"
        if any(point["watts"] is not None for point in points)
        else "insufficient_data",
        "points": points,
    }


def _power_integrals(
    times: list, watts: list, moving: list | None
) -> tuple[list[float], list[float], list]:
    energy, coverage, rates = [0.0], [0.0], []
    for index in range(len(times) - 1):
        delta = times[index + 1] - times[index]
        value = _number(watts[index])
        valid = 0 < delta <= 5 and value is not None and value >= 0
        valid = valid and (not moving or moving[index] == 1)
        rate = float(value) if valid and value is not None else 0.0
        rates.append((rate, 1.0 if valid else 0.0))
        energy.append(energy[-1] + rate * delta)
        coverage.append(coverage[-1] + (delta if valid else 0))

    return energy, coverage, rates


def _best_power_point(
    times: list, energy: list, coverage: list, rates: list, duration: int
) -> dict[str, Any]:
    def integral(at: float, values: list[float], channel: int) -> float:
        index = min(bisect_right(times, at) - 1, len(rates) - 1)
        return values[index] + rates[index][channel] * (at - times[index])

    starts = sorted(
        {float(time) for time in times if time + duration <= times[-1]}
        | {float(time - duration) for time in times if time - duration >= times[0]}
    )
    best, best_start = None, None
    for start in starts:
        end = start + duration
        known = integral(end, coverage, 1) - integral(start, coverage, 1)
        if abs(known - duration) > 1e-6:
            continue
        mean = (integral(end, energy, 0) - integral(start, energy, 0)) / duration
        if best is None or mean > best:
            best, best_start = mean, start
    return {
        "duration_seconds": duration,
        "watts": round(best, 2) if best is not None else None,
        "start_seconds": best_start,
        "coverage": 1.0 if best is not None else None,
        "status": "ok" if best is not None else "insufficient_data",
    }
