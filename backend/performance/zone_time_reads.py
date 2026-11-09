"""Report zone times of the activity summaries in one zone model (#1743).

Cross-session reports add seconds per zone over many sessions, so every session
counts in the athlete's local zones where it can: the zone times stored with
its canonical session analysis (``SessionAnalysisStage``), counted from the
streams with the zones in effect on the session day. A session without them
keeps the Garmin or Wahoo zone times of its records (zones set on the watch).
``zone_models`` names the model of each zone key, so reports never add seconds
of the two models. Readers never compute zone times.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.activities.stream_zones import LABEL
from backend.db.activity_analysis_reads import stored_zone_times
from backend.performance.canonical_session_analysis import ANALYSIS_VERSION

LOCAL_MODEL: Final = "local"
PROVIDER_MODEL: Final = "provider"
# Stored sensor -> summary zone key.
ZONE_KEYS: Final = (
    ("power", "power_zone_times"),
    ("heart_rate", "heart_rate_zone_times"),
    ("pace", "pace_zone_times"),
)


def read_zone_times(db: Any, session_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """The stored report zone times of the sessions, by session id."""
    return stored_zone_times(db, ANALYSIS_VERSION, session_ids)


def _zones(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not value:
        return None
    zones = [
        item
        for item in value
        if isinstance(item, dict)
        and isinstance(item.get("secs"), int | float)
        and str(item.get("id", "")).startswith("Z")
    ]
    return zones if len(zones) == len(value) else None


def _source_label(times: Mapping[str, Any], sensor: str) -> str:
    """The label of stored zone times, with the zone source of the sensor."""
    label = str(times.get("label") or LABEL)
    sources = times.get("sources")
    named = sources.get(sensor) if isinstance(sources, dict) else None
    return f"{label}: {named}" if named else label


def with_zone_times(
    summaries: Iterable[Mapping[str, Any]],
    stored: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return the summaries with local zone times and each zone key's model."""
    result = []
    for summary in summaries:
        item = dict(summary)
        times = stored.get(str(item.get("id")), {})
        sources = dict(item.get("sources") or {})
        models: dict[str, str] = {}
        for sensor, key in ZONE_KEYS:
            local = _zones(times.get(sensor))
            if local is not None:
                item[key] = local
                sources[key] = _source_label(times, sensor)
                models[key] = LOCAL_MODEL
            elif item.get(key):
                models[key] = PROVIDER_MODEL
        if models:
            item["sources"] = sources
            item["zone_models"] = models
        result.append(item)
    return tuple(result)


def zone_model(summary: Mapping[str, Any], key: str) -> str:
    """The zone model of one summary zone key; unmarked values are provider zones."""
    models = summary.get("zone_models")
    value = models.get(key) if isinstance(models, Mapping) else None
    return LOCAL_MODEL if value == LOCAL_MODEL else PROVIDER_MODEL
