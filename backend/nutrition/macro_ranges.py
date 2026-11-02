"""Read-only macro references derived from weight and a training calendar."""

from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _high_seconds(row: dict[str, Any]) -> float | None:
    for key in ("power_zone_times", "pace_zone_times", "heart_rate_zone_times"):
        zones = row.get(key)
        if isinstance(zones, list) and zones:
            values = []
            for zone in zones:
                if not isinstance(zone, dict):
                    return None
                name = str(zone.get("id", ""))
                seconds = _number(zone.get("secs"))
                if (
                    not name.startswith("Z")
                    or not name[1:].isdigit()
                    or seconds is None
                ):
                    return None
                if int(name[1:]) >= 4:
                    values.append(seconds)
            return sum(values)
    profile = row.get("workout_profile")
    if not isinstance(profile, dict) or profile.get("axis") != "duration":
        return None
    segments = profile.get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    high = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            return None
        duration = _number(segment.get("duration"))
        zone = _number(segment.get("zone"))
        if (
            duration is None
            or zone is None
            or "-" in str(segment.get("label") or "")
            or segment.get("end_value") != segment.get("value")
        ):
            return None
        if zone >= 4:
            high += duration
    return high


def macro_ranges(weight: Any, calendar: Any, day: str, kcal: Any) -> dict[str, Any]:
    """Calculate ranges; an unknown input leaves its comparison unavailable."""
    result: dict[str, Any] = {}
    mass = _number(weight)
    if mass:
        result["protein_g"] = (mass * 170 / 100, mass * 230 / 100)
        result["carbs_g"] = (mass * 3, mass * 5)
    energy = _number(kcal)
    if energy:
        result["fat_g"] = (energy * 0.2 / 9, energy * 0.3 / 9)
    if not mass or not isinstance(calendar, list):
        return result
    minutes = 0.0
    intense = False
    for entry in calendar:
        if not isinstance(entry, dict):
            return result
        entry_date = str(entry.get("date") or entry.get("starts_at_local") or "")[:10]
        if entry_date != day or entry.get("archived") or entry.get("local_deleted"):
            continue
        compliance = entry.get("compliance") or {}
        if not isinstance(compliance, dict):
            return result
        row = compliance.get("actual_activity") or entry
        if not isinstance(row, dict):
            return result
        duration = _number(row.get("moving_duration_s"))
        if duration is None:
            duration = _number(row.get("elapsed_duration_s"))
        if duration is None:
            duration = _number(row.get("planned_duration_s"))
        if duration is None:
            return result
        high = _high_seconds(row)
        if high is None:
            return result
        minutes += duration / 60
        intense = intense or high >= 600
    level = 2 if minutes >= 120 else 1 if minutes >= 90 else 0
    level = min(2, level + int(intense))
    low, high = ((3, 5), (5, 7), (6, 10))[level]
    result["carbs_g"] = (mass * low, mass * high)
    return result
