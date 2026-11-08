"""Observed power and running best efforts from original activity streams."""

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from itertools import accumulate, pairwise
from typing import Any, Final

from backend.canonical.activity_summary import summary_is_indoor
from backend.performance.session_analysis import _number
from backend.providers.source_labels import SESSION_SOURCES_LABEL

# 180/420/720 s are the 3/7/12-min efforts of the CP/CS field protocols; cycling
# CP also fits the 1200 s effort (M4 card 4).
POWER_DURATIONS = (5, 15, 30, 60, 120, 180, 300, 420, 600, 720, 1200, 1800, 3600)
LEGACY_POWER_DURATIONS = (5, 60, 300, 1200)
RUNNING_DURATIONS = (60, 180, 300, 420, 720, 1200)
RUNNING_DISTANCES = (1000, 5000)
METHOD_ID: Final = "mean-max-curve"
# Version 1: time-weighted windows that must be fully covered by valid samples.
# Version 2 (card M4 v4, #1773): an outdoor running window counts only when its
# net altitude change is at most 1 % of its distance; without altitude it does
# not count.
METHOD_VERSION: Final = 2
MAX_RUNNING_NET_GRADE: Final = 0.01

# Whether the window from sample ``start`` to sample ``stop`` over ``metres`` counts.
type WindowCheck = Callable[[int, int, float], bool]


def power_profile(
    activity: dict[str, Any], *, source_label: str = SESSION_SOURCES_LABEL
) -> dict[str, Any]:
    base = {
        "method": METHOD_ID,
        "method_version": METHOD_VERSION,
        "source": f"{source_label} original watts stream",
        "scope": "Beobachtete Bestwerte dieser Aufzeichnung; keine FTP-, CP- oder W'-Schätzung.",
    }
    streams = activity.get("streams") or {}
    times, watts = streams.get("time") or [], streams.get("watts") or []
    if activity.get("sport") != "ride" or len(times) < 2 or len(times) != len(watts):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Vollständige Rad-Leistungsmessreihe fehlt.",
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


def running_profile(
    activity: dict[str, Any], *, source_label: str = SESSION_SOURCES_LABEL
) -> dict[str, Any]:
    """Return observed running speed and distance efforts with exact coverage."""
    base = {
        "name": "running_best_efforts",
        "type": "running",
        "method": METHOD_ID,
        "method_version": METHOD_VERSION,
        "source": f"{source_label} original speed/distance streams",
        "scope": "Beobachtete Laufbelastungen; Lücken und Pausen bleiben unbekannt.",
    }
    if activity.get("sport") != "run":
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Keine Laufaktivität.",
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
            "reason": "Vollständige Lauf-Zeitreihe fehlt.",
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
    rates = _running_rates(times, speed, distance, streams.get("moving"))
    flat = _flat_window_check(activity, len(times))
    speed_points = [
        _best_running_speed(times, rates, duration, flat)
        for duration in RUNNING_DURATIONS
    ]
    distances = [_number(value) for value in distance]
    distance_points = [
        _best_running_distance(times, rates, distances, target, flat)
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


def _flat_window_check(activity: dict[str, Any], count: int) -> WindowCheck:
    """Accept every window indoors; outdoors only windows with a flat net altitude.

    A downhill window would inflate a best effort and the Critical Speed fit
    (card M4 v4); a window with a missing altitude end does not count outdoors.
    """
    if summary_is_indoor(activity):
        return lambda _start, _stop, _metres: True
    raw = (activity.get("streams") or {}).get("altitude") or []
    altitude = [_number(value) for value in raw] if len(raw) == count else []

    def flat(start: int, stop: int, metres: float) -> bool:
        if not altitude or metres <= 0:
            return False
        first, last = altitude[start], altitude[min(stop, count - 1)]
        if first is None or last is None:
            return False
        return abs(last - first) <= MAX_RUNNING_NET_GRADE * metres

    return flat


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
    last = len(rates) - 1

    def index(at: float) -> int:
        return min(max(bisect_right(times, at) - 1, 0), last)

    starts = sorted(
        {float(time) for time in times if time + duration <= times[-1]}
        | {float(time - duration) for time in times if time - duration >= times[0]}
    )
    best, best_start = None, None
    for start in starts:
        end = start + duration
        left, right = index(start), index(end)
        left_offset, right_offset = start - times[left], end - times[right]
        known = (coverage[right] + rates[right][1] * right_offset) - (
            coverage[left] + rates[left][1] * left_offset
        )
        if abs(known - duration) > 1e-6:
            continue
        mean = (
            (energy[right] + rates[right][0] * right_offset)
            - (energy[left] + rates[left][0] * left_offset)
        ) / duration
        if best is None or mean > best:
            best, best_start = mean, start
    return {
        "duration_seconds": duration,
        "watts": round(best, 2) if best is not None else None,
        "start_seconds": best_start,
        "coverage": 1.0 if best is not None else None,
        "status": "ok" if best is not None else "insufficient_data",
    }


def _best_running_speed(
    times: list, rates: list, duration: int, flat: WindowCheck
) -> dict[str, Any]:
    elapsed = [0.0, *accumulate(delta for _, delta, _ in rates)]
    covered = [0.0, *accumulate(rate * delta for rate, delta, _ in rates)]
    run_end = _valid_run_ends([valid for _, _, valid in rates])
    best = None
    for start, time in enumerate(times[:-1]):
        candidate = _running_speed_candidate(
            elapsed, covered, rates, start, run_end[start], duration
        )
        if candidate is None or (best is not None and candidate[0] <= best[0]):
            continue
        if flat(start, candidate[1], candidate[0] * duration):
            best = (candidate[0], time)
    return {
        "duration_seconds": duration,
        "speed_mps": round(best[0], 3) if best else None,
        "start_seconds": best[1] if best else None,
        "coverage": 1.0 if best else None,
        "status": "ok" if best else "unknown",
    }


def _best_running_distance(
    times: list, rates: list, distances: list, target: int, flat: WindowCheck
) -> dict[str, Any]:
    if len(distances) != len(times):
        return {
            "distance_meters": target,
            "seconds": None,
            "start_seconds": None,
            "coverage": None,
            "status": "unknown",
        }
    run_end = _valid_run_ends(
        [
            valid and distances[index + 1] is not None
            for index, (_, _, valid) in enumerate(rates)
        ]
    )
    best = _fastest_distance_window(times, rates, distances, run_end, target, flat)
    return {
        "distance_meters": target,
        "seconds": round(best[0], 2) if best else None,
        "start_seconds": best[1] if best else None,
        "coverage": 1.0 if best else None,
        "status": "ok" if best else "unknown",
    }


def _fastest_distance_window(
    times: list,
    rates: list,
    distances: list,
    run_end: list[int],
    target: int,
    flat: WindowCheck,
) -> tuple[float, Any] | None:
    """The shortest time over ``target`` metres and its start, among flat windows."""
    best = None
    for start in range(len(times) - 1):
        if not rates[start][2] or distances[start] is None:
            continue
        candidate = _running_distance_candidate(
            times, distances, start, run_end[start], target
        )
        if candidate is None or (best is not None and candidate[0] >= best[0]):
            continue
        if flat(start, candidate[1], target):
            best = (candidate[0], times[start])
    return best


def _valid_run_ends(valid: list[bool]) -> list[int]:
    """For each sample, the index after the last valid segment that follows it."""
    ends = [len(valid)] * (len(valid) + 1)
    for index in range(len(valid) - 1, -1, -1):
        ends[index] = ends[index + 1] if valid[index] else index
    return ends


def _running_rates(
    times: list, speed: list, distance: list, moving: list | None
) -> list:
    rates = []
    for i, (left, right) in enumerate(pairwise(times)):
        value, delta, valid = _running_segment(
            times, speed, distance, moving, i, left, right
        )
        rates.append(
            (
                float(value) if valid and value is not None else 0.0,
                float(delta or 0),
                valid,
            )
        )
    return rates


def _running_segment(
    times: list,
    speed: list,
    distance: list,
    moving: list | None,
    i: int,
    left: Any,
    right: Any,
) -> tuple:
    left_number, right_number = _number(left), _number(right)
    delta = (
        right_number - left_number
        if right_number is not None and left_number is not None
        else None
    )
    left_distance = _number(distance[i]) if len(distance) == len(times) else None
    right_distance = _number(distance[i + 1]) if len(distance) == len(times) else None
    distance_delta = (
        right_distance - left_distance
        if right_distance is not None and left_distance is not None
        else None
    )
    value = _number(speed[i]) if speed else None
    if not speed and distance_delta is not None and delta:
        value = distance_delta / delta
    valid = (
        delta is not None
        and 0 < delta <= 5
        and value is not None
        and value > 0
        and (distance_delta is None or distance_delta >= 0)
    )
    if moving and (i >= len(moving) or moving[i] != 1):
        valid = False
    return value, delta, valid


def _running_speed_candidate(
    elapsed: list[float],
    covered: list[float],
    rates: list,
    start: int,
    end: int,
    duration: int,
) -> tuple[float, int] | None:
    """Mean speed over ``duration`` from ``start`` within one valid run, and the
    sample index the window ends at."""
    if end <= start:
        return None
    target = elapsed[start] + duration
    stop = bisect_left(elapsed, target, start + 1, end + 1)
    while stop <= end and elapsed[stop] - elapsed[start] < duration:
        stop += 1
    while stop - 1 > start and elapsed[stop - 1] - elapsed[start] >= duration:
        stop -= 1
    if stop > end:
        return None
    before = elapsed[stop - 1] - elapsed[start]
    total = (
        covered[stop - 1] - covered[start] + rates[stop - 1][0] * (duration - before)
    )
    return total / duration, stop


def _running_distance_candidate(
    times: list, distances: list, start: int, end: int, target: int
) -> tuple[float, int] | None:
    """Time to cover ``target`` metres from ``start`` within one valid run, and
    the sample index the window ends at."""
    if end <= start:
        return None
    base = distances[start]
    stop = bisect_left(distances, base + target, start + 1, end + 1)
    while stop <= end and distances[stop] - base < target:
        stop += 1
    while stop - 1 > start and distances[stop - 1] - base >= target:
        stop -= 1
    if stop > end:
        return None
    delta = distances[stop] - base
    segment = distances[stop] - distances[stop - 1]
    if segment <= 0:
        return None
    fraction = (target - (delta - segment)) / segment
    seconds = (times[stop - 1] - times[start]) + fraction * (
        times[stop] - times[stop - 1]
    )
    return seconds, stop
