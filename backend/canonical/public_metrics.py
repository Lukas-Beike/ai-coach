"""Neutral key names for the activity and calendar JSON shown in the browser.

Stored activity rows keep the keys of the provider that reported them. The
browser contract names them neutrally, so the HTTP layer translates stored keys
through this module instead of exposing them.

Completed-activity objects (list rows, completed calendar entries and the
``compliance.actual_activity`` of a matched planned unit) get the full activity
map, in the vocabulary of the activity detail document. Every other calendar
entry (planned units, competitions, external events) is a local record whose
start and planned duration are already stored as ``starts_at_local`` and
``planned_duration_s``; it gets only the metric renames.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Stored key -> neutral key, applied to every translated record. The stored key
# is removed from the translated copy.
_NEUTRAL_METRIC_KEYS = (
    ("icu_training_load", "training_load"),
    ("icu_intensity", "intensity"),
    ("icu_rpe", "rpe"),
    ("icu_weighted_avg_watts", "normalized_power"),
    ("icu_hr_zone_times", "heart_rate_zone_times"),
    ("icu_zone_times", "power_zone_times"),
)

# Stored key -> neutral key, applied to completed-activity objects only.
_NEUTRAL_ACTIVITY_KEYS = (
    ("start_date_local", "started_at_local"),
    ("start_date", "started_at"),
    ("moving_time", "moving_duration_s"),
    ("elapsed_time", "elapsed_duration_s"),
    ("distance", "distance_m"),
    ("total_elevation_gain", "elevation_gain_m"),
    ("average_heartrate", "avg_hr"),
    ("max_heartrate", "max_hr"),
    ("average_watts", "avg_power"),
    ("weighted_average_watts", "weighted_avg_power"),
    ("average_speed", "avg_speed_mps"),
    ("max_speed", "max_speed_mps"),
    ("icu_weighted_avg_speed", "weighted_avg_speed_mps"),
    ("icu_pace", "pace_mps"),
    ("icu_ctl", "ctl"),
    ("icu_atl", "atl"),
    ("icu_ftp", "ftp_w"),
    ("icu_eftp", "eftp_w"),
    # The VO2max aliases collapse onto one key; the first present one wins.
    ("vo2max", "vo2max"),
    ("vo2_max", "vo2max"),
    ("vO2MaxValue", "vo2max"),
    ("vo2MaxValue", "vo2max"),
    ("icu_vo2max", "vo2max"),
)


def _renamed(
    record: Mapping[str, Any], keys: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    translated = dict(record)
    for stored_key, neutral_key in keys:
        if stored_key not in translated or stored_key == neutral_key:
            continue
        stored = translated.pop(stored_key)
        if translated.get(neutral_key) is None:
            translated[neutral_key] = stored
    laps = translated.get("laps")
    if isinstance(laps, list):
        translated["laps"] = [
            _renamed(lap, keys) if isinstance(lap, Mapping) else lap for lap in laps
        ]
    return translated


def neutral_activity_metrics(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``record`` with the stored metric keys renamed neutrally.

    Nested ``laps`` are translated the same way. An existing neutral value wins
    over the stored one. Records without the stored metrics are returned unchanged.
    """
    return _renamed(record, _NEUTRAL_METRIC_KEYS)


def neutral_activity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a completed-activity record with every stored activity key renamed."""
    return _renamed(record, (*_NEUTRAL_METRIC_KEYS, *_NEUTRAL_ACTIVITY_KEYS))


def neutral_activity_records(records: Iterable[Any]) -> list[Any]:
    """Translate activity rows, leaving non-mapping items unchanged."""
    return [
        neutral_activity(record) if isinstance(record, Mapping) else record
        for record in records
    ]


def neutral_calendar_entry(entry: Any) -> Any:
    """Translate one calendar entry and the activity matched to it.

    A completed-activity entry is an activity; every other entry is a local
    planning record with neutral start and duration keys and gets only the metric
    renames.
    """
    if not isinstance(entry, Mapping):
        return entry
    if entry.get("is_completed_activity"):
        translated = neutral_activity(entry)
    else:
        translated = neutral_activity_metrics(entry)
    compliance = translated.get("compliance")
    if isinstance(compliance, Mapping) and isinstance(
        compliance.get("actual_activity"), Mapping
    ):
        translated["compliance"] = {
            **compliance,
            "actual_activity": neutral_activity(compliance["actual_activity"]),
        }
    return translated


def neutral_calendar_entries(entries: Iterable[Any]) -> list[Any]:
    return [neutral_calendar_entry(entry) for entry in entries]


# Calendar lists of the plan and bootstrap state that can carry activities.
_CALENDAR_KEYS = ("training_calendar", "planned", "calendar")


def neutral_calendar_state(state: dict[str, Any]) -> dict[str, Any]:
    """Translate, in place, every calendar list of a plan or bootstrap state."""
    for key in _CALENDAR_KEYS:
        if isinstance(state.get(key), list):
            state[key] = neutral_calendar_entries(state[key])
    view = state.get("planning_view")
    if isinstance(view, dict) and isinstance(view.get("items"), list):
        state["planning_view"] = {
            **view,
            "items": neutral_calendar_entries(view["items"]),
        }
    return state
