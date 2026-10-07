"""Observed power and running best efforts from original activity streams."""

from bisect import bisect_right
from itertools import pairwise
from typing import Any

from backend.performance.session_analysis import _number

POWER_DURATIONS = (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600)
LEGACY_POWER_DURATIONS = (5, 60, 300, 1200)
RUNNING_DURATIONS = (60, 300, 1200)
RUNNING_DISTANCES = (1000, 5000)


def power_profile(activity: dict[str, Any]) -> dict[str, Any]:
    base = {
        "method": "original-stream-integral-v1",
        "source": "Intervals.icu original watts stream",
        "scope": "Beobachtete Bestwerte dieser Aufzeichnung; keine FTP-, CP- oder W'-Schätzung.",
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
            "reason": "Vollstaendige Rad-Leistungsmessreihe fehlt.",
            "points": [],
            "duration_curve": [],
        }
    energy, coverage, rates = _power_integrals(times, watts, streams.get("moving"))
    curve = [
        _best_power_point(times, energy, coverage, rates, duration)
        for duration in POWER_DURATIONS
    ]
    legacy = [
        next(point for point in curve if point["duration_seconds"] == duration)
        for duration in LEGACY_POWER_DURATIONS
    ]
    return {
        **base,
        "status": "ok"
        if any(point["watts"] is not None for point in curve)
        else "insufficient_data",
        "points": legacy,
        "duration_curve": curve,
    }


def running_profile(activity: dict[str, Any]) -> dict[str, Any]:
    """Return observed running speed and distance efforts with exact coverage."""
    base = {
        "name": "running_best_efforts",
        "type": "running",
        "method": "original-stream-running-v1",
        "source": "Intervals.icu original speed/distance streams",
        "scope": "Beobachtete Laufbelastungen; Lücken und Pausen bleiben unbekannt.",
    }
    if activity.get("type") not in {"Run", "VirtualRun", "TrailRun"}:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Keine Laufaktivitaet.",
            "speed": [],
            "distance": [],
        }
    streams = activity.get("streams") or {}
    times = streams.get("time") or []
    speed = (
        streams.get("velocity")
        or streams.get("speed")
        or streams.get("velocity_smooth")
        or []
    )
    distance = streams.get("distance") or []
    if (
        len(times) < 2
        or (speed and len(speed) != len(times))
        or (distance and len(distance) != len(times))
    ):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Vollstaendige Lauf-Zeitreihe fehlt.",
            "speed": [],
            "distance": [],
        }
    if not speed and len(distance) != len(times):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Lauf-Geschwindigkeit oder -Distanz fehlt.",
            "speed": [],
            "distance": [],
        }
    moving = streams.get("moving")
    rates = []
    for i, (left, right) in enumerate(pairwise(times)):
        left_number, right_number = _number(left), _number(right)
        delta = (
            right_number - left_number
            if right_number is not None and left_number is not None
            else None
        )
        left_distance = _number(distance[i]) if len(distance) == len(times) else None
        right_distance = (
            _number(distance[i + 1]) if len(distance) == len(times) else None
        )
        distance_delta = (
            right_distance - left_distance
            if right_distance is not None and left_distance is not None
            else None
        )
        value = (
            _number(speed[i])
            if speed
            else (
                distance_delta / delta if distance_delta is not None and delta else None
            )
        )
        valid = (
            delta is not None
            and 0 < delta <= 5
            and value is not None
            and value > 0
            and (distance_delta is None or distance_delta >= 0)
        )
        if moving and (i >= len(moving) or moving[i] != 1):
            valid = False
        rates.append(
            (
                float(value) if valid and value is not None else 0.0,
                float(delta or 0),
                valid,
            )
        )
    speed_points = [
        _best_running_speed(times, rates, duration) for duration in RUNNING_DURATIONS
    ]
    distance_points = [
        _best_running_distance(times, rates, distance, target)
        for target in RUNNING_DISTANCES
    ]
    ok = any(point["speed_mps"] is not None for point in speed_points) or any(
        point["seconds"] is not None for point in distance_points
    )
    return {
        **base,
        "status": "ok" if ok else "insufficient_data",
        "speed": speed_points,
        "distance": distance_points,
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
        index = min(max(bisect_right(times, at) - 1, 0), len(rates) - 1)
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


def _best_running_speed(times: list, rates: list, duration: int) -> dict[str, Any]:
    best = None
    for start_index, start in enumerate(times[:-1]):
        elapsed = 0.0
        total = 0.0
        for rate, delta, valid in rates[start_index:]:
            if not valid:
                break
            take = min(delta, duration - elapsed)
            total += rate * take
            elapsed += take
            if elapsed >= duration:
                candidate = total / duration
                if best is None or candidate > best[0]:
                    best = (candidate, start)
                break
    return {
        "duration_seconds": duration,
        "speed_mps": round(best[0], 3) if best else None,
        "start_seconds": best[1] if best else None,
        "coverage": 1.0 if best else None,
        "status": "ok" if best else "unknown",
    }


def _best_running_distance(
    times: list, rates: list, distances: list, target: int
) -> dict[str, Any]:
    if len(distances) != len(times):
        return {
            "distance_meters": target,
            "seconds": None,
            "start_seconds": None,
            "coverage": None,
            "status": "unknown",
        }
    best = None
    for start in range(len(times) - 1):
        if not rates[start][2] or _number(distances[start]) is None:
            continue
        base = float(distances[start])
        for end in range(start + 1, len(times)):
            if not rates[end - 1][2] or _number(distances[end]) is None:
                break
            delta = float(distances[end]) - base
            if delta < target:
                continue
            segment = float(distances[end]) - float(distances[end - 1])
            if segment <= 0:
                break
            fraction = (target - (delta - segment)) / segment
            elapsed = (times[end - 1] - times[start]) + fraction * (
                times[end] - times[end - 1]
            )
            if best is None or elapsed < best[0]:
                best = (elapsed, times[start])
            break
    return {
        "distance_meters": target,
        "seconds": round(best[0], 2) if best else None,
        "start_seconds": best[1] if best else None,
        "coverage": 1.0 if best else None,
        "status": "ok" if best else "unknown",
    }
