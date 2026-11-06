"""Time in zone of a session derived from its streams with the athlete's zones.

Garmin's Personal API serves no zone times (#1724), so a session can have full
heart-rate and power streams but no provider distribution. For a metric without
one, the seconds per zone are counted from the merged stream with the zones in
effect for the session's sport and day (``ZoneSettings``: local configuration,
then provider configuration, then the canonical threshold with default limits).
Nothing is stored: the result follows the current zone settings on every read.

A sample counts the time until the next sample. A gap longer than
``max(MIN_GAP_S, GAP_FACTOR x median step)`` is a pause or a dropout and counts
nothing, so downsampled charts and smart recording still count while pauses do
not. Power 0 W (coasting) counts in the lowest zone; heart rate 0 is no reading.
A metric without its threshold, or without any counted second, gets no
distribution. A zone bound outside the canonical boundary range is left open.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping
from dataclasses import replace
from itertools import pairwise
from types import MappingProxyType
from typing import Final

from backend.activities.detail_merge import (
    DetailCandidate,
    MergedDetail,
    MergedStreams,
    SetChoice,
)
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_detail import (
    MAX_ZONES,
    ZONE_BOUNDARY_BOUNDS,
    ZoneBucket,
    ZoneDistribution,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    SourceKind,
    StreamChannel,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.activity_detail_store import StoredDetailSet

METHOD_VERSION: Final = 1
LABEL: Final = "Zoneneinstellungen"
MIN_GAP_S: Final = 30.0
GAP_FACTOR: Final = 3.0
# Metric -> stream channel and the unit ``ZoneSettings.absolute_zone`` reads.
_CHANNELS: Final[Mapping[ZoneMetric, tuple[StreamChannel, str]]] = {
    ZoneMetric.HEART_RATE: (StreamChannel.HEART_RATE_BPM, "bpm"),
    ZoneMetric.POWER: (StreamChannel.POWER_W, "W"),
}


def with_stream_zones(
    merged: MergedDetail, settings: Callable[[], ZoneSettings | None]
) -> MergedDetail:
    """Add a derived distribution for each metric the providers left without one.

    ``settings`` is read only when a stream of such a metric exists.
    """
    streams = merged.streams
    if streams is None:
        return merged
    missing = [
        metric
        for metric, (channel, _unit) in _CHANNELS.items()
        if metric not in merged.zones and channel in streams.channels
    ]
    resolved = settings() if missing else None
    if resolved is None:
        return merged
    added: dict[ZoneMetric, SetChoice] = {}
    for metric in missing:
        candidate = _derived(streams, metric, resolved)
        if candidate is not None:
            added[metric] = SetChoice(chosen=candidate, alternatives=())
    if not added:
        return merged
    return replace(merged, zones=MappingProxyType({**merged.zones, **added}))


def _limits(
    metric: ZoneMetric, settings: ZoneSettings
) -> tuple[float, tuple[float, ...]] | None:
    """The threshold and the percent limits of one metric, if its threshold is known."""
    if metric is ZoneMetric.HEART_RATE:
        threshold, limits = settings.lthr, settings.hr_limits
    else:
        threshold, limits = settings.ftp, settings.power_limits
    if not threshold or threshold <= 0 or len(limits) + 1 > MAX_ZONES:
        return None
    return threshold, limits


def _derived(
    streams: MergedStreams, metric: ZoneMetric, settings: ZoneSettings
) -> DetailCandidate | None:
    channel, unit = _CHANNELS[metric]
    choice = streams.channels.get(channel)
    zone_limits = _limits(metric, settings)
    if (
        choice is None
        or zone_limits is None
        or len(choice.values) != len(streams.time_s)
    ):
        return None
    threshold, limits = zone_limits
    seconds = _seconds(
        streams.time_s,
        choice.values,
        lambda value: settings.absolute_zone(unit, value),
        len(limits) + 1,
        count_zero=metric is ZoneMetric.POWER,
    )
    if not any(seconds):
        return None
    low, high = ZONE_BOUNDARY_BOUNDS[metric]
    bounds = [
        bound if low <= bound <= high else None
        for bound in (limit * threshold / 100 for limit in limits)
    ]
    buckets = tuple(
        ZoneBucket(
            index=index,
            seconds=value,
            lower=bounds[index - 2] if index > 1 else None,
            upper=bounds[index - 1] if index <= len(bounds) else None,
        )
        for index, value in enumerate(seconds, start=1)
    )
    source = choice.source
    stream_provenance = source.stored.detail.provenance
    provenance = Provenance(
        provider=stream_provenance.provider,
        source_kind=SourceKind.DERIVED,
        source_record_id=stream_provenance.source_record_id,
        recorded_by=stream_provenance.recorded_by,
        retrieved_at=stream_provenance.retrieved_at,
        label=LABEL,
    )
    distribution = ZoneDistribution(
        provider_activity_id=source.stored.provider_activity_id,
        provenance=provenance,
        origin=ActivityDetailOrigin.FETCH,
        metric=metric,
        boundary_source=ZoneBoundarySource.PROFILE,
        buckets=buckets,
    )
    return replace(
        source,
        stored=StoredDetailSet(
            provider=source.stored.provider,
            provider_activity_id=source.stored.provider_activity_id,
            activity_id=source.stored.activity_id,
            mapper_version=METHOD_VERSION,
            summary_sha256=None,
            fetched_at=source.stored.fetched_at,
            detail=distribution,
        ),
    )


def _seconds(
    time_s: tuple[float, ...],
    values: tuple[float | None, ...],
    zone_of: Callable[[float], int | None],
    zones: int,
    *,
    count_zero: bool,
) -> list[float]:
    """Seconds per zone; the last sample and samples before a gap count nothing."""
    seconds = [0.0] * zones
    steps = [right - left for left, right in pairwise(time_s) if right > left]
    if not steps:
        return seconds
    max_step = max(MIN_GAP_S, GAP_FACTOR * statistics.median(steps))
    for (start, end), value in zip(pairwise(time_s), values[:-1], strict=True):
        step = end - start
        if value is None or value < 0 or (value == 0 and not count_zero):
            continue
        zone = zone_of(value)
        if zone is not None and 0 < step <= max_step:
            seconds[zone - 1] += step
    return seconds
