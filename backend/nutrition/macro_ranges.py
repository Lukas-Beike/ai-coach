"""Read-only macro references derived from weight and a training calendar."""

from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _recorded_high_seconds(zones: list[Any]) -> float | None:
    high = 0.0
    for zone in zones:
        if not isinstance(zone, dict):
            return None
        name = str(zone.get("id", ""))
        seconds = _number(zone.get("secs"))
        if not name.startswith("Z") or not name[1:].isdigit() or seconds is None:
            return None
        if int(name[1:]) >= 4:
            high += seconds
    return high


def _planned_high_seconds(profile: Any) -> float | None:
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


def _high_seconds(row: dict[str, Any]) -> float | None:
    for key in ("power_zone_times", "pace_zone_times", "heart_rate_zone_times"):
        zones = row.get(key)
        if isinstance(zones, list) and zones:
            return _recorded_high_seconds(zones)
    return _planned_high_seconds(row.get("workout_profile"))


def _session_totals(entry: dict[str, Any]) -> tuple[float, bool] | None:
    compliance = entry.get("compliance") or {}
    if not isinstance(compliance, dict):
        return None
    row = compliance.get("actual_activity") or entry
    if not isinstance(row, dict):
        return None
    duration = None
    for key in ("moving_duration_s", "elapsed_duration_s", "planned_duration_s"):
        duration = _number(row.get(key))
        if duration is not None:
            break
    high = _high_seconds(row)
    if duration is None or high is None:
        return None
    return duration / 60, high >= 600


def _calendar_date(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    compliance = entry.get("compliance") or {}
    if not isinstance(compliance, dict):
        return None
    if (
        compliance.get("status") == "missed"
        or entry.get("archived")
        or entry.get("local_deleted")
    ):
        return ""
    actual = compliance.get("actual_activity")
    dated = actual if isinstance(actual, dict) else entry
    return (
        str(
            dated.get("date")
            or dated.get("started_at_local")
            or dated.get("starts_at_local")
            or ""
        )[:10]
        or None
    )


def _training_totals(calendar: list[Any], day: str) -> tuple[float, bool] | None:
    minutes = 0.0
    intense = False
    for entry in calendar:
        entry_date = _calendar_date(entry)
        if entry_date is None:
            return None
        if entry_date != day:
            continue
        totals = _session_totals(entry)
        if totals is None:
            return None
        minutes += totals[0]
        intense = intense or totals[1]
    return minutes, intense


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
    totals = _training_totals(calendar, day)
    if totals is None:
        return result
    minutes, intense = totals
    level = int(minutes >= 90) + int(minutes >= 120)
    level = min(2, level + int(intense))
    low, high = ((3, 5), (5, 7), (6, 10))[level]
    result["carbs_g"] = (mass * low, mass * high)
    return result
