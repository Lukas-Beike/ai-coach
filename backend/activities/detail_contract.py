"""Provider-neutral ``activity_detail.v1`` document of one canonical session.

The document is built from merged detail (``backend.activities.detail_merge``) and
the session's active activity records. It is pure: no I/O, no clock, and no
provider activity ids, URLs, raw payloads or provider wire keys leave it. Sources
are named by ``ProviderId`` and the stored provenance label only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from backend.activities.detail_merge import (
    DetailCandidate,
    MergedDetail,
    MergedStreams,
    SetChoice,
    clock_offset,
    stream_average,
)
from backend.activities.detail_projection import (
    COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS,
    _downsample_series,
)
from backend.canonical.activity_detail import (
    LAP_METRIC_FIELDS,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneDistribution,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import ProviderId, StreamChannel, ZoneMetric
from backend.db.activity_detail_store import StoredDetailSet

ACTIVITY_DETAIL_CONTRACT: Final = "activity_detail.v1"

_ENVELOPE_KEYS: Final = ("activity_feedback", "equipment", "activity_validation")
_PROVIDER_ORDER: Final[tuple[ProviderId, ...]] = (
    ProviderId.INTERVALS,
    ProviderId.GARMIN,
    ProviderId.WAHOO,
)
_MEASURED_METRICS: Final[tuple[tuple[str, str], ...]] = (
    ("duration_s", "s"),
    ("moving_duration_s", "s"),
    ("elapsed_duration_s", "s"),
    ("distance_m", "m"),
    ("elevation_gain_m", "m"),
    ("elevation_high_m", "m"),
    ("elevation_low_m", "m"),
    ("avg_hr", "bpm"),
    ("max_hr", "bpm"),
    ("min_hr", "bpm"),
    ("avg_power", "W"),
    ("max_power_w", "W"),
    ("avg_cadence", "rpm"),
    ("max_speed_mps", "m/s"),
    ("steps", "count"),
    ("energy_kj", "kJ"),
)
_DERIVED_METRICS: Final[tuple[tuple[str, str | None], ...]] = (
    ("normalized_power", "W"),
    ("load", None),
)
# Measured averages that fall back to the merged stream mean when no record has them.
_GAP_FILL: Final[Mapping[str, tuple[StreamChannel, str]]] = {
    "avg_hr": (StreamChannel.HEART_RATE_BPM, "bpm"),
    "avg_power": (StreamChannel.POWER_W, "W"),
}


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Freshness of one provider's stored detail against its current summary.

    ``load_error`` is the ``{message, observed_at}`` note of a failed load of the
    current summary version, already filtered by the caller.
    """

    stale: bool = False
    load_error: Mapping[str, Any] | None = None


def measured_order(records: Sequence[ActivityRecord]) -> list[ActivityRecord]:
    """Order records by how much their measured values win.

    The recording platform's own copy comes first, then the provider rank, then the
    newest retrieval, then the provider activity id.
    """
    return sorted(records, key=lambda record: (_own_rank(record), *_tie_break(record)))


def _derived_order(records: Sequence[ActivityRecord]) -> list[ActivityRecord]:
    """Order records for derived values: provider rank, newest retrieval, id."""
    return sorted(records, key=_tie_break)


def activity_detail_contract(
    session_id: str,
    records: Sequence[ActivityRecord],
    merged: MergedDetail,
    stored: Sequence[StoredDetailSet],
    *,
    analysis: Mapping[str, Any] | None,
    refreshable: frozenset[ProviderId],
    status: Mapping[ProviderId, ProviderStatus] | None = None,
    envelope: Mapping[str, Any] | None = None,
    summary_metrics: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the ``activity_detail.v1`` document of one canonical session.

    ``status`` adds stale, load error and coverage to each provider entry.
    ``envelope`` adds the feedback, equipment and activity validation blocks.
    ``summary_metrics`` fill metrics that no measured or derived value provides.
    """
    if not records:
        raise ValueError("records must not be empty")
    measured = measured_order(records)
    metrics = _metrics(measured, _derived_order(records), merged)
    for key, entry in (summary_metrics or {}).items():
        metrics.setdefault(key, dict(entry))
    document = {
        "contract": ACTIVITY_DETAIL_CONTRACT,
        "session": _session(session_id, measured[0]),
        "metrics": metrics,
        "streams": _streams(merged.streams),
        "laps": _laps(merged.laps, merged.streams),
        "zones": _zones(merged.zones),
        "analysis": analysis,
        "detail_data": {
            "providers": _providers(records, stored, refreshable, status),
            "display_sampled": _display_sampled(merged.streams),
        },
    }
    if envelope is not None:
        document.update({key: envelope.get(key) for key in _ENVELOPE_KEYS})
    return document


def _session(session_id: str, primary: ActivityRecord) -> dict[str, Any]:
    return {
        "activity_id": session_id,
        "sport": primary.sport.value,
        "environment": primary.environment.value,
        "started_at": primary.started_at.isoformat(),
        "name": primary.name,
        "device_type": None
        if primary.device_type is None
        else primary.device_type.value,
    }


def _metrics(
    measured: Sequence[ActivityRecord],
    derived: Sequence[ActivityRecord],
    merged: MergedDetail,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for key, unit in _MEASURED_METRICS:
        entry = _record_metric(measured, key, unit, "measured")
        if entry is None:
            entry = _gap_fill(key, merged)
        if entry is not None:
            metrics[key] = entry
    for key, derived_unit in _DERIVED_METRICS:
        entry = _record_metric(
            derived, key, derived_unit, "derived", with_model=key == "load"
        )
        if entry is not None:
            metrics[key] = entry
    return metrics


def _record_metric(
    ordered: Sequence[ActivityRecord],
    key: str,
    unit: str | None,
    kind: str,
    *,
    with_model: bool = False,
) -> dict[str, Any] | None:
    present = [
        (record, getattr(record, key))
        for record in ordered
        if getattr(record, key) is not None
    ]
    if not present:
        return None

    def item(record: ActivityRecord, value: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "value": value,
            "source": _source(record.provenance, kind),
        }
        if with_model:
            entry["model"] = record.load_model.value
        return entry

    first = item(*present[0])
    metric: dict[str, Any] = {
        "value": first["value"],
        "unit": unit,
        "source": first["source"],
        "alternatives": [item(record, value) for record, value in present[1:]],
    }
    if with_model:
        metric["model"] = first["model"]
    return metric


def _gap_fill(key: str, merged: MergedDetail) -> dict[str, Any] | None:
    """Fill a missing average from the merged stream mean, labelled as derived."""
    if merged.streams is None or key not in _GAP_FILL:
        return None
    channel, unit = _GAP_FILL[key]
    average = stream_average(merged.streams, channel)
    choice = merged.streams.channels.get(channel)
    if average is None or choice is None:
        return None
    return {
        "value": average,
        "unit": unit,
        "source": _source(choice.source.stored.detail.provenance, "derived"),
        "alternatives": [],
    }


def _streams(streams: MergedStreams | None) -> dict[str, Any] | None:
    if streams is None:
        return None
    return {
        "time_s": _downsample_series(list(streams.time_s)),
        "source": _candidate_source(streams.primary),
        "channels": {
            channel.value: {
                "values": _downsample_series(list(choice.values)),
                "source": _candidate_source(choice.source),
                "aligned": choice.aligned,
            }
            for channel, choice in streams.channels.items()
        },
    }


def _laps(
    choice: SetChoice | None, streams: MergedStreams | None
) -> dict[str, Any] | None:
    if choice is None:
        return None
    chosen = _lap_set(choice.chosen)
    offset = None if streams is None else clock_offset(choice.chosen, streams.primary)
    return {
        "lap_source": chosen.lap_source.value,
        "source": _candidate_source(choice.chosen),
        # Offsets are moved onto the stream clock when the recordings can be aligned;
        # otherwise they stay on the lap recording's own clock.
        "on_stream_clock": offset is not None,
        "laps": [_lap(lap, offset or 0.0) for lap in chosen.laps],
        "alternatives": [_lap_alternative(alt) for alt in choice.alternatives],
    }


def _lap_alternative(candidate: DetailCandidate) -> dict[str, Any]:
    lap_set = _lap_set(candidate)
    return {
        "lap_source": lap_set.lap_source.value,
        "source": _candidate_source(candidate),
        "count": len(lap_set.laps),
    }


def _lap(lap: ActivityLap, shift_s: float) -> dict[str, Any]:
    return {
        "index": lap.index,
        "kind": lap.kind.value,
        "start_offset_s": lap.start_offset_s + shift_s,
        "end_offset_s": lap.end_offset_s + shift_s,
        "name": lap.name,
        **{field: getattr(lap, field) for field in LAP_METRIC_FIELDS},
    }


def _zones(zones: Mapping[ZoneMetric, SetChoice]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for metric, choice in zones.items():
        zone = _zone_set(choice.chosen)
        result[metric.value] = {
            "boundary_source": zone.boundary_source.value,
            "source": _candidate_source(choice.chosen),
            "buckets": [
                {
                    "index": bucket.index,
                    "seconds": bucket.seconds,
                    "lower": bucket.lower,
                    "upper": bucket.upper,
                    "label": bucket.label,
                }
                for bucket in zone.buckets
            ],
            "alternatives": [_candidate_source(alt) for alt in choice.alternatives],
        }
    return result


def _providers(
    records: Sequence[ActivityRecord],
    stored: Sequence[StoredDetailSet],
    refreshable: frozenset[ProviderId],
    status: Mapping[ProviderId, ProviderStatus] | None,
) -> list[dict[str, Any]]:
    labels: dict[ProviderId, str | None] = {}
    for record in records:
        provider = record.provenance.provider
        if provider is not None:
            labels.setdefault(provider, record.provenance.label)
    providers: list[dict[str, Any]] = []
    for provider in sorted(labels, key=_provider_rank):
        sets = [item for item in stored if item.provider == provider.value]
        entry: dict[str, Any] = {
            "provider": provider.value,
            "label": labels[provider],
            "kinds": sorted({item.detail.kind.value for item in sets}),
            "fetched_at": _newest_text([item.fetched_at for item in sets]),
            "refreshable": provider in refreshable,
        }
        if status is not None:
            state = status.get(provider, ProviderStatus())
            entry["stale"] = state.stale
            entry["load_error"] = (
                None if state.load_error is None else dict(state.load_error)
            )
            entry["coverage"] = _coverage(sets)
        providers.append(entry)
    return providers


def _coverage(sets: Sequence[StoredDetailSet]) -> dict[str, dict[str, int]]:
    """Return points and valid points per stream channel; the fullest set wins."""
    coverage: dict[str, dict[str, int]] = {}
    for item in sets:
        detail = item.detail
        if not isinstance(detail, ActivityStreamSet):
            continue
        for channel, values in detail.channels.items():
            if channel is StreamChannel.TIME_S:
                continue
            entry = {
                "points": len(values),
                "valid_points": sum(value is not None for value in values),
            }
            known = coverage.get(channel.value)
            if known is None or entry["points"] > known["points"]:
                coverage[channel.value] = entry
    return dict(sorted(coverage.items()))


def _display_sampled(streams: MergedStreams | None) -> bool:
    """Return True when a merged stream is longer than the display cap."""
    return streams is not None and len(streams.time_s) > (
        COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS
    )


def _newest_text(texts: Sequence[str]) -> str | None:
    """Return the latest aware ISO timestamp among ``texts``; unusable ones are skipped."""
    newest: str | None = None
    newest_seconds = -math.inf
    for text in texts:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.utcoffset() is None:
            continue
        if newest is None or parsed.timestamp() > newest_seconds:
            newest, newest_seconds = text, parsed.timestamp()
    return newest


def _source(provenance: Provenance, kind: str) -> dict[str, Any]:
    provider = provenance.provider
    return {
        "provider": None if provider is None else provider.value,
        "label": provenance.label,
        "kind": kind,
        "recorded_by": provenance.recorded_by.value,
    }


def _candidate_source(candidate: DetailCandidate) -> dict[str, Any]:
    return _source(candidate.stored.detail.provenance, "measured")


def _lap_set(candidate: DetailCandidate) -> ActivityLapSet:
    detail = candidate.stored.detail
    if not isinstance(detail, ActivityLapSet):
        raise TypeError("lap choice must be a lap set")
    return detail


def _zone_set(candidate: DetailCandidate) -> ZoneDistribution:
    detail = candidate.stored.detail
    if not isinstance(detail, ZoneDistribution):
        raise TypeError("zone choice must be a zone distribution")
    return detail


def _own_rank(record: ActivityRecord) -> int:
    provider = record.provenance.provider
    own = provider is not None and provider.value == (
        record.provenance.recorded_by.value
    )
    return 0 if own else 1


def _provider_rank(provider: ProviderId) -> int:
    return (
        _PROVIDER_ORDER.index(provider)
        if provider in _PROVIDER_ORDER
        else len(_PROVIDER_ORDER)
    )


def _tie_break(record: ActivityRecord) -> tuple[int, float, str]:
    provider = record.provenance.provider
    rank = len(_PROVIDER_ORDER) if provider is None else _provider_rank(provider)
    retrieved = record.provenance.retrieved_at
    seconds = -math.inf if retrieved is None else retrieved.timestamp()
    return rank, -seconds, record.activity_id
