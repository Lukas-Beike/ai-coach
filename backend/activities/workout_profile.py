"""Small, provider-free calendar profiles from explicit steps or original samples."""

import math
import re
from typing import Any

from backend.activities.workout_text import WorkoutTextError, structured_steps
from backend.activities.zone_settings import (
    DEFAULT_ZONE_SOURCE,
    ZoneSettings,
)

_ZONE_TARGET = re.compile(r"Z([1-7])(?:\s*-\s*Z([1-7]))?(?:\s+(?:HR|PACE))?")


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def planned_profile(
    workout: dict[str, Any], settings: ZoneSettings | None = None
) -> dict[str, Any] | None:
    """Profile of the planned steps; ``settings`` supplies the athlete's zones.

    Absolute watt or bpm targets are colored from the athlete's FTP or LTHR and
    the profile is then marked ``estimated``.
    """
    settings = settings or ZoneSettings()
    description = workout.get("description")
    if not isinstance(description, str) or len(description) > 20000:
        return None
    try:
        steps = structured_steps(description, str(workout.get("target") or "AUTO"))
    except WorkoutTextError:
        return None
    # Steps are either all timed or all distance-based; the other kind has no
    # common width axis, so a mixed list gets no profile.
    axis = "duration" if steps and "duration" in steps[0] else "distance"
    if not steps or any(axis not in step for step in steps):
        return None
    built = _planned_segments(steps, axis, settings)
    if built is None:
        return None
    segments, units, estimated = built
    if len(units) != 1:
        zone_segments = _zone_segments(steps, segments)
        if zone_segments is None:
            return None
        segments = zone_segments
        units = {"zone"}
    profile: dict[str, Any] = {
        "source": "planned",
        "axis": axis,
        "unit": units.pop(),
        "segments": segments,
    }
    if estimated:
        profile["estimated"] = True
    return profile


def recorded_profile(
    activity: dict[str, Any], zones: ZoneSettings | None = None
) -> dict[str, Any] | None:
    """Profile of the recorded watts, else heart rate, colored by the session's zones.

    ``zones`` holds the thresholds and limits resolved locally for the session
    date; without a matching threshold the segments stay uncolored.
    """
    streams = _profile_streams(activity)
    if streams is None:
        return None
    times, values, kind, start, end = streams
    width = (end - start) / 60
    totals, known = _bucket_totals(times, values, kind, start, end)
    unit = "W" if kind == "watts" else "bpm"
    segments = [
        _recorded_segment(total, coverage, width, unit, zones or ZoneSettings())
        for total, coverage in zip(totals, known, strict=True)
    ]
    if not any(item["value"] is not None for item in segments):
        return None
    return {"source": "recorded", "unit": unit, "segments": segments}


def _planned_segments(
    steps: list[dict[str, Any]], axis: str, settings: ZoneSettings
) -> tuple[list[dict[str, Any]], set[str], bool] | None:
    segments: list[dict[str, Any]] = []
    units: set[str] = set()
    estimated = False
    for step in steps:
        result = _planned_segment(step, axis, settings)
        if result is None:
            return None
        segment, unit, from_estimate = result
        segments.append(segment)
        units.add(unit)
        estimated = estimated or from_estimate
    return segments, units, estimated


def _zone_segments(
    steps: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    # Steps of one kind may mix zone and percent targets (for example
    # "Z1 HR" and "86-89% HR"); the zone is their common axis.
    if len({step["kind"] for step in steps}) != 1 or any(
        segment["zone"] is None for segment in segments
    ):
        return None
    return [
        {**segment, "value": segment["zone"], "end_value": segment["zone"]}
        for segment in segments
    ]


def _planned_segment(
    step: dict[str, Any], axis: str, settings: ZoneSettings
) -> tuple[dict[str, Any], str, bool] | None:
    target = step["target"]
    numbers = re.findall(r"\d+(?:\.\d+)?", target)
    if not numbers or ":" in target:
        return None
    low, high = float(numbers[0]), float(numbers[-1])
    value = (low + high) / 2
    zone = _ZONE_TARGET.fullmatch(target)
    color: int | None = None
    estimated = False
    if zone:
        color = int(zone[2] or zone[1])
        unit = "zone"
    elif "%" in target and step["kind"] in {"power", "hr", "pace"}:
        color, unit = _percent_target_zone(step["kind"], target, value, settings)
    else:
        unit = step["kind"]
        if "BPM" in target:
            unit = "bpm"
        elif "W" in target:
            unit = "W"
        color = settings.absolute_zone(unit, value)
        estimated = color is not None
    segment = {
        axis: step[axis],
        "value": low if step["ramp"] else value,
        "end_value": high if step["ramp"] else value,
        "zone": color,
        "label": target,
    }
    if target_range := _target_range(step["kind"], target, zone, (low, high), settings):
        segment["range"] = target_range
    return segment, unit, estimated


# The unit of each step kind's range, and its zone limits and reference on a day.
_RANGE_UNITS = {"hr": "bpm", "power": "W", "pace": "s/km"}


def _target_range(
    kind: str,
    target: str,
    zone: re.Match[str] | None,
    numbers: tuple[float, float],
    settings: ZoneSettings,
) -> dict[str, Any] | None:
    """The step's target as ``{"unit", "min", "max"}`` in bpm, W or s/km (#2447).

    A zone target spans its zones' limits in effect on the unit's day and needs
    the athlete's own zones of that signal; ``min`` is missing for the lowest
    zone and ``max`` for the open top zone. A percent target is that share of
    the threshold; an absolute bpm or watt target is itself. Pace is seconds per
    km, ``min`` the slower end. None without the needed zones or threshold.
    """
    unit = _RANGE_UNITS.get(kind)
    reference = _reference(kind, target, settings)
    if unit is None or not reference:
        return None
    if zone:
        percents = _zone_percents(kind, zone, settings)
    elif "%" in target:
        percents = numbers
    elif unit != "s/km" and ("BPM" in target or "W" in target):
        return {"unit": unit, "min": round(numbers[0]), "max": round(numbers[1])}
    else:
        percents = None
    return None if percents is None else _scaled(unit, reference, percents, bool(zone))


def _zone_percents(
    kind: str, zone: re.Match[str], settings: ZoneSettings
) -> tuple[float | None, float | None] | None:
    """The lower and upper limit (percent) of the zones; None without own zones."""
    limits, source = _signal_limits(kind, settings)
    if source == DEFAULT_ZONE_SOURCE:
        return None
    first, last = int(zone[1]), int(zone[2] or zone[1])
    # A zone the athlete's set does not have gets no range.
    if not 1 <= first <= last <= len(limits) + 1:
        return None
    return (
        limits[first - 2] if first > 1 else None,
        limits[last - 1] if last - 1 < len(limits) else None,
    )


def _scaled(
    unit: str,
    reference: float,
    percents: tuple[float | None, float | None],
    zone_start: bool,
) -> dict[str, Any]:
    low, high = (None if p is None else reference * p / 100 for p in percents)
    if unit == "s/km":
        # Faster is more intense: the slower end comes first.
        return _range(unit, *(None if v is None else 1000 / v for v in (low, high)))
    if not zone_start:
        return _range(unit, low, high)
    # Whole bpm or watts: a zone ends at the last whole unit below its limit and
    # starts one above the zone below ("110–128 bpm"); Garmin's limits lie half a
    # unit above the zone's last bpm, a local limit on it.
    low, high = (None if v is None else math.floor(v + 1e-6) for v in (low, high))
    return _range(unit, None if low is None else low + 1, high)


def _range(unit: str, low: float | None, high: float | None) -> dict[str, Any]:
    values = {"min": low, "max": high}
    return {"unit": unit, **{k: round(v) for k, v in values.items() if v is not None}}


def _reference(kind: str, target: str, settings: ZoneSettings) -> float | None:
    """The bpm, W or m/s that the step's percent and zone limits are relative to."""
    if kind == "power":
        return settings.ftp
    if kind == "pace":
        return settings.threshold_pace
    if "%" in target and "LTHR" not in target:
        return settings.max_hr
    return settings.hr_zone_reference


def _signal_limits(kind: str, settings: ZoneSettings) -> tuple[tuple[float, ...], str]:
    if kind == "power":
        return settings.power_limits, settings.power_source
    if kind == "pace":
        return settings.pace_limits, settings.pace_source
    return settings.hr_limits, settings.hr_source


def _percent_target_zone(
    kind: str, target: str, percent: float, settings: ZoneSettings
) -> tuple[int, str]:
    if kind == "power":
        return settings.power_zone(percent), "%FTP"
    if kind == "pace":
        return settings.pace_zone(percent), "%PACE"
    if "LTHR" in target:
        return settings.hr_zone_of_lthr(percent), "%LTHR"
    return settings.hr_zone_of_max(percent), "%HR"


def _profile_streams(
    activity: dict[str, Any],
) -> tuple[list, list, str, float, float] | None:
    streams = activity.get("streams")
    if not isinstance(streams, dict):
        return None
    times = streams.get("time")
    kind = "watts" if isinstance(streams.get("watts"), list) else "heartrate"
    values = streams.get(kind)
    if (
        not isinstance(times, list)
        or not isinstance(values, list)
        or len(times) != len(values)
        or not 2 <= len(times) <= 200000
    ):
        return None
    start, end = _number(times[0]), _number(times[-1])
    if start is None or end is None or not 0 < end - start <= 86400:
        return None

    return times, values, kind, start, end


def _bucket_totals(
    times: list, values: list, kind: str, start: float, end: float
) -> tuple[list[float], list[float]]:
    width = (end - start) / 60
    totals, known = [0.0] * 60, [0.0] * 60
    for index in range(len(times) - 1):
        left, right, value = (
            _number(times[index]),
            _number(times[index + 1]),
            _number(values[index]),
        )
        if (
            left is None
            or right is None
            or value is None
            or not 0 < right - left <= 10
            or not start <= left < right <= end
            or not (0 if kind == "watts" else 20)
            <= value
            <= (3000 if kind == "watts" else 230)
        ):
            continue
        first = min(59, int((left - start) / width))
        last = min(59, int((right - start) / width))
        for bucket in range(first, last + 1):
            seconds = max(
                0,
                min(right, start + (bucket + 1) * width)
                - max(left, start + bucket * width),
            )
            totals[bucket] += value * seconds
            known[bucket] += seconds

    return totals, known


def _recorded_segment(
    total: float, coverage: float, width: float, unit: str, zones: ZoneSettings
) -> dict[str, Any]:
    value = total / coverage if coverage >= width * 0.8 else None
    return {
        "duration": width,
        "value": value,
        "end_value": value,
        "zone": None if value is None else zones.absolute_zone(unit, value),
        "label": "Missing" if value is None else f"{value:.0f} {unit}",
    }
