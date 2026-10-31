"""Pure detailed projection of a raw Intervals.icu activity for Coach analysis."""

from __future__ import annotations

import math
from typing import Any

from backend.providers.intervals_activity_detail_mapping import zone_times
from backend.providers.intervals_activity_keys import (
    INTENSITY,
    LACTATE_THRESHOLD_HR,
    PACE,
    ROLLING_FTP,
    RPE,
    WEIGHTED_AVG_SPEED,
    WEIGHTED_AVG_WATTS,
)
from backend.providers.intervals_performance_fields import (
    CONFIGURED_FTP,
    HEART_RATE_ZONE_TIMES,
    TRAINING_LOAD,
    ZONE_TIMES,
)

COACH_ACTIVITY_DETAIL_FIELDS = (
    "start_date_local",
    "start_date",
    "name",
    "type",
    "sport",
    "subtype",
    "moving_time",
    "elapsed_time",
    "distance",
    "total_elevation_gain",
    "total_elevation_loss",
    "calories",
    "average_speed",
    "max_speed",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "max_watts",
    "weighted_average_watts",
    WEIGHTED_AVG_WATTS,
    "normalized_power",
    "average_cadence",
    "max_cadence",
    "average_temp",
    "min_temp",
    "max_temp",
    TRAINING_LOAD,
    INTENSITY,
    ROLLING_FTP,
    CONFIGURED_FTP,
    LACTATE_THRESHOLD_HR,
    WEIGHTED_AVG_SPEED,
    PACE,
    RPE,
    "feel",
    "faded",
    "decoupling",
)
COACH_ACTIVITY_DETAIL_STREAM_FIELDS = (
    "time",
    "distance",
    "altitude",
    "grade",
    "grade_smooth",
    "speed",
    "velocity",
    "velocity_smooth",
    "pace",
    "watts",
    "power",
    "heartrate",
    "cadence",
    "temperature",
    "moving",
    "timer",
)
COACH_ACTIVITY_DETAIL_LAP_FIELDS = (
    "name",
    "start_time",
    "end_time",
    "start_index",
    "end_index",
    "elapsed_time",
    "moving_time",
    "distance",
    "average_speed",
    "max_speed",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "max_watts",
    "weighted_average_watts",
    WEIGHTED_AVG_WATTS,
    "normalized_power",
    "average_cadence",
    "total_elevation_gain",
    TRAINING_LOAD,
    INTENSITY,
)
# Raised when the projection gains a field that stored records lack; prefetch
# then reloads the recent activities once.
DETAIL_PROJECTION_VERSION = 2
COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS = 2000
COACH_ACTIVITY_DETAIL_MAX_LAPS = 200


def _analysis_scalar(value: Any, *, limit: int = 200) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:limit]
    return None


def _downsample_series(
    values: Any, *, limit: int = COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS
) -> list[Any]:
    if not isinstance(values, list):
        return []
    values = [_analysis_scalar(value, limit=80) for value in values]
    if len(values) <= limit:
        return values
    indexes = {0, len(values) - 1}
    indexes.update(
        round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)
    )
    return [values[index] for index in sorted(indexes)]


def _analysis_laps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    laps: list[dict[str, Any]] = []
    for item in value[:COACH_ACTIVITY_DETAIL_MAX_LAPS]:
        if not isinstance(item, dict):
            continue
        lap: dict[str, Any] = {}
        for key in COACH_ACTIVITY_DETAIL_LAP_FIELDS:
            if key in item:
                scalar = _analysis_scalar(item[key], limit=120)
                if scalar is not None:
                    lap[key] = scalar
        if lap:
            laps.append(lap)
    return laps


def _detail_scalars(activity: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in COACH_ACTIVITY_DETAIL_FIELDS:
        if key in activity:
            scalar = _analysis_scalar(
                activity[key], limit=500 if key == "name" else 200
            )
            if scalar is not None:
                projected[key] = scalar
    return projected


def _detail_streams(streams: Any) -> dict[str, Any]:
    if not isinstance(streams, dict):
        return {}
    return {
        key: _downsample_series(streams[key])
        for key in COACH_ACTIVITY_DETAIL_STREAM_FIELDS
        if key in streams
    }


def detailed_activity(activity: Any) -> dict[str, Any]:
    """Project one activity for detailed coaching without raw metadata."""
    if not isinstance(activity, dict):
        return {}
    projected = _detail_scalars(activity)
    streams = _detail_streams(activity.get("streams"))
    if streams:
        projected["streams"] = streams
    for key in (HEART_RATE_ZONE_TIMES, ZONE_TIMES):
        zones = zone_times(activity.get(key))
        if zones:
            projected[key] = zones
    laps = _analysis_laps(activity.get("laps"))
    if laps:
        projected["laps"] = laps
    return projected
