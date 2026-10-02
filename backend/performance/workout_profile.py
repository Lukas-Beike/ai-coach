"""Small, provider-free calendar profiles from explicit steps or original samples."""

import math
import re
from typing import Any

from backend.providers.workout_text import WorkoutTextError, structured_steps


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def _power_zone(percent: float) -> int:
    return next(
        (
            index
            for index, limit in enumerate((55, 75, 90, 105, 120, 150), 1)
            if percent <= limit
        ),
        7,
    )


def planned_profile(workout: dict[str, Any]) -> dict[str, Any] | None:
    description = workout.get("description")
    if not isinstance(description, str) or len(description) > 20000:
        return None
    try:
        steps = structured_steps(description, str(workout.get("target") or "AUTO"))
    except WorkoutTextError:
        return None
    if not steps or any("duration" not in step for step in steps):
        return None
    segments = []
    units = set()
    for step in steps:
        target = step["target"]
        zone = re.fullmatch(r"Z([1-7])(?:\s+(?:HR|PACE))?", target)
        numbers = re.findall(r"\d+(?:\.\d+)?", target)
        if not numbers:
            return None
        low, high = float(numbers[0]), float(numbers[-1])
        value = (low + high) / 2
        if zone:
            color = int(zone[1])
            units.add("zone")
        elif step["kind"] == "power" and "%" in target:
            color = _power_zone(value)
            units.add("%FTP")
        else:
            color = None
            units.add(
                "bpm" if "BPM" in target else "W" if "W" in target else step["kind"]
            )
        segments.append(
            {
                "duration": step["duration"],
                "value": low if step["ramp"] else value,
                "end_value": high if step["ramp"] else value,
                "zone": color,
                "label": target,
            }
        )
    if len(units) != 1:
        return None
    return {"source": "planned", "unit": units.pop(), "segments": segments}


def recorded_profile(activity: dict[str, Any]) -> dict[str, Any] | None:
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
    ftp = _number(activity.get("icu_ftp"))
    segments = []
    for total, coverage in zip(totals, known, strict=True):
        value = total / coverage if coverage >= width * 0.8 else None
        segments.append(
            {
                "duration": width,
                "value": value,
                "end_value": value,
                "zone": _power_zone(value / ftp * 100)
                if value is not None and kind == "watts" and ftp and ftp > 0
                else None,
                "label": f"{value:.0f} {'W' if kind == 'watts' else 'bpm'}"
                if value is not None
                else "Missing",
            }
        )
    return (
        {
            "source": "recorded",
            "unit": "W" if kind == "watts" else "bpm",
            "segments": segments,
        }
        if any(item["value"] is not None for item in segments)
        else None
    )
