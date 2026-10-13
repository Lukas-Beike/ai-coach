"""Compact activity projection shared by the planning and performance readers.

``ACTIVITY_FIELDS`` is the Intervals.icu compact ``recent_activities`` row shape. It lives here,
below both domains, so the performance readers can derive that shape from raw
activity rows without importing the planning package.
"""

from __future__ import annotations

from typing import Any

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


def selected(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Return the non-null ``fields`` of a mapping, or an empty dict for non-mappings."""
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in fields if key in item and item[key] is not None}
