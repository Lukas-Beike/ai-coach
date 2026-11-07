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

from backend.canonical.vocabulary import Assist, LoadModel, Terrain

# Load models on the TSS scale: one hour at threshold is about 100.
TSS_LIKE_LOAD_MODELS: Final = frozenset(
    {LoadModel.INTERVALS_TRAINING_LOAD, LoadModel.TSS}
)


class ActivitySummary(TypedDict, total=False):
    """One session's summary; only values some record reports are present.

    ``id`` is the local session id; ``record_ids`` maps each provider of the
    session to its provider activity id. ``started_at`` is the exact start and
    ``started_at_local`` the wall time where the activity was recorded:
    ``local_offset_minutes`` is its UTC offset when a provider reports one, else
    the athlete zone applies. ``terrain`` follows ``session_terrain`` and
    is left out when unknown; ``assist`` is present only as "electric"
    (``session_assist``).
    Zone times are lists of
    ``{"id": "Z1", "secs": 600.0}`` items. ``rpe_conflict`` is True when the
    session's records report different provider RPE values. ``purpose`` is an
    ``ActivityPurpose`` value, absent for ordinary training without a source;
    ``competition_id`` names the stored competition a race is linked to.
    """

    id: str
    started_at: str
    started_at_local: str
    local_offset_minutes: int
    name: str
    sport: str
    environment: str
    terrain: str
    assist: str
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
    elevation_loss_m: float
    avg_hr: float
    max_hr: float
    avg_power: float
    avg_cadence: float
    avg_speed_mps: float
    max_speed_mps: float
    avg_temp_c: float
    min_temp_c: float
    max_temp_c: float
    energy_kj: float
    energy_kcal: float
    # Local session metrics (card M8), stored as derived observations.
    efficiency_factor: float
    efficiency_factor_unit: str
    variability_index: float
    work_kj: float
    decoupling_pct: float
    rpe: float
    rpe_conflict: bool
    feel: float
    normalized_power: float
    weighted_avg_speed_mps: float
    pace_mps: float
    intensity: float
    provider_intensity: float
    grade_adjusted_speed_mps: float
    ftp_w: float
    vo2max: float
    training_load: float
    load_method: str
    load_method_version: int
    load_branch: str
    load_threshold_after_session: bool
    load_sex_assumed: bool
    load_calibration: dict[str, Any]
    provider_training_load: float
    provider_load_model: str
    training_effect_label: str
    training_effect_load: float
    aerobic_training_effect: float
    anaerobic_training_effect: float
    power_zone_times: list[dict[str, Any]]
    heart_rate_zone_times: list[dict[str, Any]]
    pace_zone_times: list[dict[str, Any]]
    planned_event_id: str
    purpose: str
    competition_id: str


def summary_local_date(summary: Mapping[str, Any], timezone: str | None = None) -> str:
    """Return the ISO start date of a summary, or "" without a start.

    Without ``timezone`` this is the local date the reader assigned. With an IANA
    ``timezone`` the exact start is converted to that zone first, unless the
    summary carries its own UTC offset: such an activity stays on the day it was
    lived. An unknown zone falls back to the assigned local date.
    """
    if timezone and summary.get("local_offset_minutes") is None:
        try:
            zone = ZoneInfo(timezone)
            started = datetime.fromisoformat(str(summary.get("started_at") or ""))
        except ValueError, KeyError, ZoneInfoNotFoundError:
            pass
        else:
            return started.astimezone(zone).date().isoformat()
    return str(summary.get("started_at_local") or "")[:10]


def stored_activity_key(summary: Mapping[str, Any]) -> str:
    """Return the key feedback, equipment assignments and analyses are stored under.

    The live local session id; ``ActivityReferences.resolve_reference`` resolves
    any other reference to it. Rows stored before this rule sit under a provider
    record id of the session and are found through ``record_ids``.
    """
    return str(summary.get("id") or "")


def legacy_activity_keys(summary: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the provider record ids older rows of the session may be stored under."""
    record_ids = summary.get("record_ids")
    if not isinstance(record_ids, Mapping):
        return ()
    return tuple(str(value) for value in record_ids.values() if value)


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


def summary_is_trail_run(summary: Mapping[str, Any]) -> bool:
    """Return True for a trail run, whose pace is not comparable with road runs."""
    return (
        summary.get("sport") == "run" and summary.get("terrain") == Terrain.TRAIL.value
    )


def summary_is_electric(summary: Mapping[str, Any]) -> bool:
    """Return True for a motor-assisted session, such as an e-bike ride."""
    return summary.get("assist") == Assist.ELECTRIC.value
