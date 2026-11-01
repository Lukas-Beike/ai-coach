"""Provider-neutral activity summary shape and its pure readers.

``backend.activities.activity_summary`` builds summaries from canonical records;
this module holds only the shape, so ports and consumers can name it without
depending on the builder.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.canonical.vocabulary import LoadModel, ProviderId

# Load models on the TSS scale: one hour at threshold is about 100.
TSS_LIKE_LOAD_MODELS: Final = frozenset(
    {LoadModel.INTERVALS_TRAINING_LOAD, LoadModel.TSS}
)


class ActivitySummary(TypedDict, total=False):
    """One session's summary; only values some record reports are present.

    ``id`` is the local session id; ``record_ids`` maps each provider of the
    session to its provider activity id. ``started_at`` is the exact start and
    ``started_at_local`` the athlete's wall time. Zone times are lists of
    ``{"id": "Z1", "secs": 600.0}`` items. ``rpe_conflict`` is True when the
    session's records report different provider RPE values.
    """

    id: str
    started_at: str
    started_at_local: str
    name: str
    sport: str
    environment: str
    recorded_by: str
    device_type: str
    device_name: str
    source: str
    sources: dict[str, str]
    record_ids: dict[str, str]
    moving_duration_s: float
    elapsed_duration_s: float
    distance_m: float
    elevation_gain_m: float
    avg_hr: float
    max_hr: float
    avg_power: float
    avg_cadence: float
    avg_speed_mps: float
    max_speed_mps: float
    avg_temp_c: float
    rpe: float
    rpe_conflict: bool
    feel: float
    normalized_power: float
    weighted_avg_speed_mps: float
    pace_mps: float
    intensity: float
    ftp_w: float
    eftp_w: float
    vo2max: float
    training_load: float
    load_model: str
    training_effect_label: str
    training_effect_load: float
    power_zone_times: list[dict[str, Any]]
    heart_rate_zone_times: list[dict[str, Any]]
    pace_zone_times: list[dict[str, Any]]
    planned_event_id: str


def summary_local_date(summary: Mapping[str, Any], timezone: str | None = None) -> str:
    """Return the ISO start date of a summary, or "" without a start.

    Without ``timezone`` this is the athlete-local date the reader assigned. With
    an IANA ``timezone`` the exact start is converted to that zone first; an
    unknown zone falls back to the athlete-local date.
    """
    if timezone:
        try:
            zone = ZoneInfo(timezone)
            started = datetime.fromisoformat(str(summary.get("started_at") or ""))
        except ValueError, KeyError, ZoneInfoNotFoundError:
            pass
        else:
            return started.astimezone(zone).date().isoformat()
    return str(summary.get("started_at_local") or "")[:10]


def stored_activity_key(summary: Mapping[str, Any]) -> str:
    """Return the key feedback, workout profiles and analyses are stored under.

    As ``ActivityReferences.resolve_reference`` resolves it: the session's
    Intervals.icu activity id when it holds one, else the local session id.
    """
    record_ids = summary.get("record_ids")
    if isinstance(record_ids, Mapping):
        intervals_id = record_ids.get(ProviderId.INTERVALS.value)
        if intervals_id:
            return str(intervals_id)
    return str(summary.get("id") or "")


def summary_duration_s(summary: Mapping[str, Any]) -> float | None:
    """Return the moving duration, else the elapsed duration, of a summary."""
    for key in ("moving_duration_s", "elapsed_duration_s"):
        value = summary.get(key)
        if value is not None:
            return float(value)
    return None


def summary_is_indoor(summary: Mapping[str, Any]) -> bool:
    """Return True for an indoor or virtual session."""
    return summary.get("environment") in _INDOOR_ENVIRONMENTS


_INDOOR_ENVIRONMENTS: Final = frozenset({"indoor", "virtual"})
