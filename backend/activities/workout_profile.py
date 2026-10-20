"""Small, provider-free calendar profiles from explicit steps or original samples."""

import math
import re
from typing import Any

from backend.activities.workout_text import WorkoutTextError, structured_steps
from backend.activities.zone_settings import (
    HR_ZONE_LIMITS,
    POWER_ZONE_LIMITS,
    ZoneSettings,
    percent_zone,
)
from backend.providers.intervals_activity_keys import activity_ftp, activity_lthr

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


def recorded_profile(activity: dict[str, Any]) -> dict[str, Any] | None:
    streams = _profile_streams(activity)
    if streams is None:
        return None
    times, values, kind, start, end = streams
    width = (end - start) / 60
    totals, known = _bucket_totals(times, values, kind, start, end)
    threshold = _number(
        activity_ftp(activity) if kind == "watts" else activity_lthr(activity)
    )
    segments = [
        _recorded_segment(total, coverage, width, kind, threshold)
        for total, coverage in zip(totals, known, strict=True)
    ]
    if not any(item["value"] is not None for item in segments):
        return None
    return {
        "source": "recorded",
        "unit": "W" if kind == "watts" else "bpm",
        "segments": segments,
    }


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

    return segment, unit, estimated


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
    total: float, coverage: float, width: float, kind: str, threshold: float | None
) -> dict[str, Any]:
    value = total / coverage if coverage >= width * 0.8 else None
    zone = None
    if value is not None and threshold and threshold > 0:
        percent = value / threshold * 100
        zone = percent_zone(
            percent, POWER_ZONE_LIMITS if kind == "watts" else HR_ZONE_LIMITS
        )
    label = "Missing"
    if value is not None:
        unit = "W" if kind == "watts" else "bpm"
        label = f"{value:.0f} {unit}"
    return {
        "duration": width,
        "value": value,
        "end_value": value,
        "zone": zone,
        "label": label,
    }
