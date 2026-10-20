"""Compact activity projection shared by the planning and performance readers.

It also reads which device recorded an Intervals.icu row (Wahoo or Garmin).

``ACTIVITY_FIELDS`` is the Intervals.icu compact ``recent_activities`` row shape. It lives here,
below both domains, so the performance readers can derive that shape from raw
activity rows without importing the planning package.
"""

from __future__ import annotations

from typing import Any

from backend.canonical.vocabulary import RecordingOrigin

ACTIVITY_FIELDS = (
    "id",
    "start_date_local",
    "name",
    "type",
    "moving_time",
    "distance",
    "total_elevation_gain",
    "elapsed_time",
    "icu_training_load",
    "icu_intensity",
    "icu_ctl",
    "icu_atl",
    "icu_ftp",
    "icu_eftp",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "weighted_average_watts",
    "icu_weighted_avg_watts",
    "normalized_power",
    "average_speed",
    "max_speed",
    "icu_weighted_avg_speed",
    "icu_pace",
    "vo2max",
    "vo2_max",
    "vO2MaxValue",
    "vo2MaxValue",
    "icu_vo2max",
    "feel",
    "icu_rpe",
    "paired_event_id",
    "source",
    "device_name",
    "external_id",
    "file_type",
)

# Planned-unit metrics a synced remote event carries back onto the local unit.
REMOTE_EVENT_METRIC_KEYS = (
    "moving_time",
    "workout_doc",
    "icu_training_load",
    "icu_intensity",
)
# Query that asks the activity detail endpoint to include interval rows.
ACTIVITY_DETAIL_PARAMS = {"intervals": "true"}
# Stream names the Intervals.icu streams endpoint knows; it answers 422 to others.
ACTIVITY_DETAIL_STREAM_TYPES = (
    "time",
    "distance",
    "altitude",
    "grade_smooth",
    "velocity_smooth",
    "watts",
    "heartrate",
    "cadence",
    "temp",
    "moving",
)
# Provider stream names the app stores under its own name.
ACTIVITY_DETAIL_STREAM_ALIASES = {"temp": "temperature"}


def activity_detail_laps(detail: dict[str, Any]) -> Any:
    """Return the interval rows of an activity detail payload as laps."""
    return detail.get("icu_intervals", [])


def selected(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Return the non-null ``fields`` of a mapping, or an empty dict for non-mappings."""
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in fields if key in item and item[key] is not None}


# Wire fields that name the device or app which recorded an activity.
_DEVICE_SOURCE_FIELDS = ("source", "device_name", "external_id")


def intervals_activity_device_source(activity: Any) -> RecordingOrigin | None:
    """Return explicit Wahoo or Garmin provenance; a manual source has none."""
    if not isinstance(activity, dict):
        return None
    source = activity.get("source")
    if isinstance(source, str) and source.strip().casefold() == "manual":
        return None
    provenance = " ".join(
        str(activity.get(key) or "") for key in _DEVICE_SOURCE_FIELDS
    ).casefold()
    if RecordingOrigin.WAHOO in provenance or "elemnt" in provenance:
        return RecordingOrigin.WAHOO
    if RecordingOrigin.GARMIN in provenance:
        return RecordingOrigin.GARMIN
    return None


def intervals_activity_recorded_by_wahoo(activity: Any) -> bool:
    """Return True when an Intervals.icu activity names a Wahoo recording device."""
    return intervals_activity_device_source(activity) == RecordingOrigin.WAHOO
