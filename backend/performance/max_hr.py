"""Garmin sport-specific maximum heart-rate aggregation."""

from typing import Any

from backend.activities.identity import activity_kind
from backend.canonical.decimal_text import provider_number as _as_number


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def garmin_activity_max_hr(activities: Any) -> dict[str, float | int]:
    """Keep sport-specific Garmin max-HR aggregates before activity dedupe."""
    values: dict[str, list[float | int]] = {"cycling": [], "running": []}
    if not isinstance(activities, list):
        return {}
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        kind = activity_kind(activity)
        value = _as_number(
            _first_present(activity, ("maxHR", "maxHeartRate", "max_heartrate"))
        )
        if kind in values and value is not None and 80 <= float(value) <= 260:
            values[kind].append(value)
    return {kind: max(items) for kind, items in values.items() if items}


def merge_garmin_max_hr(current: Any, previous: Any) -> dict[str, float | int]:
    """Retain the last known Garmin max-HR when a refresh has no activity value."""
    merged: dict[str, float | int] = {}
    for source in (previous, current):
        if not isinstance(source, dict):
            continue
        for kind in ("cycling", "running"):
            value = _as_number(source.get(kind))
            if value is not None and 80 <= float(value) <= 260:
                merged[kind] = max(merged.get(kind, value), value)
    return merged
