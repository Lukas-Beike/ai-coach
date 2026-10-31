"""Provider-neutral summary of one canonical activity session.

A session bundles the active records of every provider that reported the same
activity. Its summary names each value in the vocabulary of ``activity_detail.v1``
and takes it from the best-ranked record that has it: measured values in
``measured_order`` (the recording platform's own copy first), derived values in
``derived_order`` (provider rank). ``sources`` names the source label of every
value, so consumers never read provider rows or provider field names.

``training_load`` is filled only from TSS-like load models, so loads of different
scales are never added up; ``load_model`` names the model it came from.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, tzinfo
from typing import Any, Final

from backend.activities.detail_contract import derived_order, measured_order
from backend.canonical.activity_summary import (
    TSS_LIKE_LOAD_MODELS,
    ActivitySummary,
    stored_activity_key,
    summary_duration_s,
    summary_is_indoor,
    summary_local_date,
)
from backend.canonical.records import ActivityRecord

# Summary key -> ActivityRecord field, in measured order.
_MEASURED: Final = (
    ("moving_duration_s", "moving_duration_s"),
    ("elapsed_duration_s", "elapsed_duration_s"),
    ("distance_m", "distance_m"),
    ("elevation_gain_m", "elevation_gain_m"),
    ("avg_hr", "avg_hr"),
    ("max_hr", "max_hr"),
    ("avg_power", "avg_power"),
    ("avg_cadence", "avg_cadence"),
    ("avg_speed_mps", "avg_speed_mps"),
    ("max_speed_mps", "max_speed_mps"),
    ("avg_temp_c", "avg_temp_c"),
    ("rpe", "rpe"),
    ("feel", "feel"),
)
# Summary key -> ActivityRecord field, in derived order.
_DERIVED: Final = (
    ("normalized_power", "normalized_power"),
    ("weighted_avg_speed_mps", "weighted_avg_speed_mps"),
    ("pace_mps", "pace_mps"),
    ("intensity", "intensity"),
    ("ftp_w", "ftp_w"),
    ("eftp_w", "eftp_w"),
    ("vo2max", "vo2max"),
    ("power_zone_times", "power_zone_times_s"),
    ("heart_rate_zone_times", "hr_zone_times_s"),
    ("pace_zone_times", "pace_zone_times_s"),
    ("planned_event_id", "planned_event_id"),
)
_ZONE_KEYS: Final = frozenset(
    {"power_zone_times", "heart_rate_zone_times", "pace_zone_times"}
)


def activity_summary(
    session_id: str, records: Sequence[ActivityRecord], zone: tzinfo
) -> ActivitySummary:
    """Summarise the active records of one session; ``records`` must not be empty."""
    if not records:
        raise ValueError("records must not be empty")
    measured = measured_order(records)
    derived = derived_order(records)
    primary = measured[0]
    local_start = primary.started_at.astimezone(zone).replace(tzinfo=None)
    summary: dict[str, Any] = {
        "id": session_id,
        "started_at": primary.started_at.isoformat(),
        "started_at_local": local_start.isoformat(timespec="seconds"),
        "sport": primary.sport.value,
        "environment": primary.environment.value,
        "recorded_by": primary.provenance.recorded_by.value,
    }
    sources: dict[str, str] = {}
    name = _first(measured, "name")
    if name is not None:
        summary["name"] = name[1]
    if primary.device_type is not None:
        summary["device_type"] = primary.device_type.value
    for ordered, fields in ((measured, _MEASURED), (derived, _DERIVED)):
        for key, field in fields:
            found = _first(ordered, field)
            if found is None:
                continue
            record, value = found
            summary[key] = _zones(value) if key in _ZONE_KEYS else value
            sources[key] = _label(record)
    load = next(
        (
            record
            for record in derived
            if record.load is not None and record.load_model in TSS_LIKE_LOAD_MODELS
        ),
        None,
    )
    if load is not None:
        summary["training_load"] = load.load
        summary["load_model"] = load.load_model.value
        sources["training_load"] = _label(load)
    summary["source"] = _label(primary)
    summary["sources"] = sources
    record_ids: dict[str, str] = {}
    for record in measured:
        provider = record.provenance.provider
        if provider is not None:
            record_ids.setdefault(provider.value, record.activity_id)
    summary["record_ids"] = record_ids
    return summary  # type: ignore[return-value]


def activity_summaries(
    sessions: Iterable[tuple[str, Sequence[ActivityRecord]]],
    zone: tzinfo,
    *,
    limit: int | None = None,
) -> tuple[ActivitySummary, ...]:
    """Summarise sessions newest first (start, then id), keeping ``limit`` at most."""
    summaries = sorted(
        (
            activity_summary(session_id, records, zone)
            for session_id, records in sessions
            if records
        ),
        key=lambda summary: (
            datetime.fromisoformat(summary["started_at"]),
            summary["id"],
        ),
        reverse=True,
    )
    return tuple(summaries if limit is None else summaries[:limit])


def _first(
    ordered: Sequence[ActivityRecord], field: str
) -> tuple[ActivityRecord, Any] | None:
    for record in ordered:
        value = getattr(record, field)
        if value is not None:
            return record, value
    return None


def _zones(value: Any) -> list[dict[str, Any]]:
    return [{"id": zone_id, "secs": seconds} for zone_id, seconds in value]


def _label(record: ActivityRecord) -> str:
    provenance = record.provenance
    if provenance.label:
        return provenance.label
    return "" if provenance.provider is None else provenance.provider.value


__all__ = [
    "TSS_LIKE_LOAD_MODELS",
    "ActivitySummary",
    "activity_summaries",
    "activity_summary",
    "stored_activity_key",
    "summary_duration_s",
    "summary_is_indoor",
    "summary_local_date",
]
