"""Dependency-light, deterministic coach-context projections."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any


COACH_ACTIVITY_FIELDS = (
    "id", "start_date_local", "name", "type", "moving_time", "distance", "total_elevation_gain",
    "icu_training_load", "icu_intensity", "average_heartrate", "max_heartrate", "average_watts",
    "weighted_average_watts", "average_speed", "icu_weighted_avg_speed", "icu_pace", "icu_rpe", "feel",
)

COACH_ACTIVITY_DETAIL_FIELDS = (
    "start_date_local", "start_date", "name", "type", "sport", "subtype", "moving_time", "elapsed_time",
    "distance", "total_elevation_gain", "total_elevation_loss", "calories", "average_speed", "max_speed",
    "average_heartrate", "max_heartrate", "average_watts", "max_watts", "weighted_average_watts",
    "average_cadence", "max_cadence", "average_temp", "min_temp", "max_temp", "icu_training_load",
    "icu_intensity", "icu_rolling_ftp", "icu_weighted_avg_speed", "icu_pace", "icu_rpe", "feel", "faded",
    "decoupling",
)
COACH_ACTIVITY_DETAIL_STREAM_FIELDS = (
    "time", "distance", "altitude", "grade", "grade_smooth", "speed", "velocity", "pace", "watts",
    "power", "heartrate", "cadence", "temperature", "moving", "timer",
)
COACH_ACTIVITY_DETAIL_LAP_FIELDS = (
    "name", "start_time", "elapsed_time", "moving_time", "distance", "average_speed", "max_speed",
    "average_heartrate", "max_heartrate", "average_watts", "max_watts", "weighted_average_watts",
    "average_cadence", "total_elevation_gain", "icu_training_load", "icu_intensity",
)
COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS = 2000
COACH_ACTIVITY_DETAIL_MAX_LAPS = 200


def _truncate_values(value: dict[str, Any], limits: Mapping[str, int]) -> dict[str, Any]:
    for key, limit in limits.items():
        if key in value:
            value[key] = str(value[key])[:limit]
    return value


def compact_coach_activity(activity: Any, *, select: Callable[[Any, tuple[str, ...]], dict[str, Any]]) -> dict[str, Any]:
    return _truncate_values(select(activity, COACH_ACTIVITY_FIELDS), {"id": 200, "name": 200, "type": 80, "feel": 120})


def _analysis_scalar(value: Any, *, limit: int = 200) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:limit]
    return None


def _downsample_series(values: Any, *, limit: int = COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS) -> list[Any]:
    if not isinstance(values, list):
        return []
    values = [_analysis_scalar(value, limit=80) for value in values]
    if len(values) <= limit:
        return values
    indexes = {0, len(values) - 1}
    indexes.update(round(index * (len(values) - 1) / (limit - 1)) for index in range(limit))
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


def detailed_coach_activity(activity: Any) -> dict[str, Any]:
    """Project one activity for detailed coaching without exposing raw metadata."""
    if not isinstance(activity, dict):
        return {}
    projected: dict[str, Any] = {}
    for key in COACH_ACTIVITY_DETAIL_FIELDS:
        if key in activity:
            scalar = _analysis_scalar(activity[key], limit=200 if key != "name" else 500)
            if scalar is not None:
                projected[key] = scalar
    streams = activity.get("streams")
    if isinstance(streams, dict):
        projected_streams = {
            key: _downsample_series(streams[key])
            for key in COACH_ACTIVITY_DETAIL_STREAM_FIELDS
            if key in streams
        }
        if projected_streams:
            projected["streams"] = projected_streams
    laps = _analysis_laps(activity.get("laps"))
    if laps:
        projected["laps"] = laps
    return projected


def compact_coach_planned_event(event: Any, *, select: Callable[[Any, tuple[str, ...]], dict[str, Any]]) -> dict[str, Any]:
    compacted = select(event, ("id", "start_date_local", "name", "type", "moving_time", "target", "icu_intensity", "status", "sync_status"))
    return _truncate_values(compacted, {"id": 200, "start_date_local": 40, "name": 200, "type": 80, "target": 1000, "status": 80, "sync_status": 80})


def compact_coach_local_planned_workout(workout: Any, *, select: Callable[[Any, tuple[str, ...]], dict[str, Any]]) -> dict[str, Any]:
    compacted = select(workout, ("id", "date", "name", "type", "duration_minutes", "target", "icu_intensity", "status", "sync_status"))
    return _truncate_values(compacted, {"id": 80, "date": 20, "name": 200, "type": 80, "target": 1000, "status": 80, "sync_status": 80})


def compact_coach_local_planned_workouts(
    workouts: Any,
    *,
    limit: int,
    select: Callable[[Any, tuple[str, ...]], dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(workouts, list):
        return []
    return [
        compact_coach_local_planned_workout(workout, select=select)
        for workout in sorted(
            (item for item in workouts if isinstance(item, dict)),
            key=lambda item: (str(item.get("date") or ""), str(item.get("id") or "")),
        )[:limit]
    ]


def coach_context_json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def bounded_coach_context_value(value: Any, limit: int) -> Any:
    """Keep a JSON value valid while deterministically fitting a character limit."""
    if limit <= 0:
        return None
    if coach_context_json_size(value) <= limit:
        return value
    if isinstance(value, str):
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if coach_context_json_size(value[:middle]) <= limit:
                low = middle
            else:
                high = middle - 1
        return value[:low]
    if isinstance(value, list):
        result: list[Any] = []
        for item in value:
            candidate = result + [bounded_coach_context_value(item, limit)]
            if coach_context_json_size(candidate) > limit:
                break
            result = candidate
        return result
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            candidate = dict(result)
            candidate[str(key)] = bounded_coach_context_value(item, limit)
            if coach_context_json_size(candidate) > limit:
                break
            result = candidate
        return result
    return None


def bounded_coach_context_sections(
    context: dict[str, Any],
    *,
    section_limits: Mapping[str, int],
) -> tuple[dict[str, Any], list[dict[str, int | str]]]:
    projected = dict(context)
    truncations: list[dict[str, int | str]] = []
    for section, limit in section_limits.items():
        original_size = coach_context_json_size(projected.get(section))
        projected_value = bounded_coach_context_value(projected.get(section), limit)
        projected[section] = projected_value
        projected_size = coach_context_json_size(projected_value)
        if projected_size < original_size:
            truncations.append({"section": section, "original_characters": original_size, "projected_characters": projected_size})
    return projected, truncations


def coach_context_projection_meta(
    context: dict[str, Any],
    local_planned_count: int,
    library_count: int,
    *,
    section_limits: Mapping[str, int],
    total_limit: int,
    local_activity_limit: int,
    planned_event_limit: int,
    local_planned_limit: int,
    truncations: list[dict[str, int | str]] | None = None,
) -> dict[str, Any]:
    section_sizes = {section: coach_context_json_size(context.get(section)) for section in sorted(section_limits)}
    return {
        "version": 1,
        "budgets": {**section_limits, "total": total_limit},
        "section_characters": section_sizes,
        "over_budget_sections": [section for section in sorted(section_sizes) if section_sizes[section] > section_limits[section]],
        "truncated_sections": truncations or [],
        "planned_local_items": local_planned_count,
        "library_items": library_count,
        "activity_limit_per_sport": local_activity_limit,
        "planned_event_limit": planned_event_limit,
        "local_planned_limit": local_planned_limit,
    }
