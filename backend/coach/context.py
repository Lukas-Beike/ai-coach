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


def _truncate_values(value: dict[str, Any], limits: Mapping[str, int]) -> dict[str, Any]:
    for key, limit in limits.items():
        if key in value:
            value[key] = str(value[key])[:limit]
    return value


def compact_coach_activity(activity: Any, *, select: Callable[[Any, tuple[str, ...]], dict[str, Any]]) -> dict[str, Any]:
    return _truncate_values(select(activity, COACH_ACTIVITY_FIELDS), {"id": 200, "name": 200, "type": 80, "feel": 120})


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
