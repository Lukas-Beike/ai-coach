"""Time in zone of a session derived from its streams with the athlete's zones.

Garmin's Personal API serves no zone times (#1724), and the zones set on a
device differ from the athlete's local zones. For every metric with a stream,
the seconds per zone are counted from the merged stream with the zones in
effect for the session's sport and day (``ZoneSettings``, resolved by
``performance.session_zones``) and win over the provider distribution, which
stays an alternative (#1743), so the detail view counts what the reports count.

A sample counts the time until the next sample. A gap longer than
``max(MIN_GAP_S, GAP_FACTOR x median step)`` is a pause or a dropout and counts
nothing, so downsampled charts and smart recording still count while pauses do
not. Where the streams carry ``moving``, only moving samples count, as for the
stream averages (``stream_average``). Power 0 W (coasting) counts in the lowest zone; heart rate 0 is no reading.
A metric without its threshold, or without any counted second, gets no
distribution. A zone bound outside the canonical boundary range is left open.

``zone_times`` counts the same way for the cross-session reports (#1743): heart
rate and power always from the streams, and for runs the pace zones from the
speed stream against the threshold pace (speed 0 is no reading).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from types import MappingProxyType
from typing import Final

from backend.activities.detail_merge import (
    DetailCandidate,
    MergedDetail,
    MergedStreams,
    SetChoice,
)
from backend.activities.zone_settings import ZoneSettings, percent_zone
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
# Bump when ``zone_times`` counts or names its zones differently, so stored report
# zones recompute (2: the zone source of each sensor, the Garmin watch zones).
ZONE_TIMES_VERSION: Final = 2
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
    """Choose a derived distribution for each metric that has a stream.

    A provider distribution of that metric becomes an alternative. ``settings``
    is read only when such a stream exists.
    """
    streams = merged.streams
    if streams is None:
        return merged
    metrics = [
        metric
        for metric, (channel, _unit) in _CHANNELS.items()
        if channel in streams.channels
    ]
    resolved = settings() if metrics else None
    if resolved is None:
        return merged
    added: dict[ZoneMetric, SetChoice] = {}
    for metric in metrics:
        candidate = _derived(streams, metric, resolved)
        if candidate is None:
            continue
        provider = merged.zones.get(metric)
        alternatives = (
            () if provider is None else (provider.chosen, *provider.alternatives)
        )
        added[metric] = SetChoice(chosen=candidate, alternatives=alternatives)
    if not added:
        return merged
    return MergedDetail(
        streams=merged.streams,
        laps=merged.laps,
        zones=MappingProxyType({**merged.zones, **added}),
    )


def zone_sources(settings: ZoneSettings) -> dict[str, str]:
    """The source of the zone limits of each report sensor."""
    return {
        "heart_rate": settings.hr_source,
        "power": settings.power_source,
        "pace": settings.pace_source,
    }


def zone_times(
    streams: MergedStreams | None, settings: ZoneSettings, *, pace: bool
) -> dict[str, list[dict[str, object]]]:
    """Seconds per zone ``[{"id": "Z1", "secs": ...}]`` by report sensor.

    Keys are ``heart_rate``, ``power`` and, with ``pace``, ``pace``; a sensor
    without its stream, threshold or any counted second is left out.
    """
    if streams is None:
        return {}
    sensors: list[tuple[str, StreamChannel, float | None, tuple[float, ...]]] = [
        (
            "heart_rate",
            StreamChannel.HEART_RATE_BPM,
            settings.hr_zone_reference,
            settings.hr_limits,
        ),
        ("power", StreamChannel.POWER_W, settings.ftp, settings.power_limits),
    ]
    if pace:
        sensors.append(
            (
                "pace",
                StreamChannel.SPEED_MPS,
                settings.threshold_pace,
                settings.pace_limits,
            )
        )
    result: dict[str, list[dict[str, object]]] = {}
    for sensor, channel, threshold, limits in sensors:
        seconds = _channel_seconds(streams, channel, threshold, limits)
        if seconds is not None:
            result[sensor] = [
                {"id": f"Z{index}", "secs": round(value, 1)}
                for index, value in enumerate(seconds, start=1)
            ]
    return result


def _channel_seconds(
    streams: MergedStreams,
    channel: StreamChannel,
    threshold: float | None,
    limits: tuple[float, ...],
) -> list[float] | None:
    """Seconds per zone of one channel against percent ``limits`` of ``threshold``."""
    choice = streams.channels.get(channel)
    moving = streams.channels.get(StreamChannel.MOVING)
    size = len(streams.time_s)
    if (
        choice is None
        or not threshold
        or threshold <= 0
        or len(limits) + 1 > MAX_ZONES
        or len(choice.values) != size
        or (moving is not None and len(moving.values) != size)
    ):
        return None
    seconds = _seconds(
        streams.time_s,
        choice.values,
        None if moving is None else moving.values,
        lambda value: percent_zone(value / threshold * 100, limits),
        len(limits) + 1,
        count_zero=channel is StreamChannel.POWER_W,
    )
    return seconds if any(seconds) else None


def _limits(
    metric: ZoneMetric, settings: ZoneSettings
) -> tuple[float, tuple[float, ...], str] | None:
    """The threshold, percent limits and source of one metric, if its threshold is known."""
    if metric is ZoneMetric.HEART_RATE:
        threshold, limits, source = (
            settings.hr_zone_reference,
            settings.hr_limits,
            settings.hr_source,
        )
    else:
        threshold, limits, source = (
            settings.ftp,
            settings.power_limits,
            settings.power_source,
        )
    if not threshold or threshold <= 0 or len(limits) + 1 > MAX_ZONES:
        return None
    return threshold, limits, source


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
    threshold, limits, source_name = zone_limits
    moving = streams.channels.get(StreamChannel.MOVING)
    if moving is not None and len(moving.values) != len(streams.time_s):
        return None
    seconds = _seconds(
        streams.time_s,
        choice.values,
        None if moving is None else moving.values,
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
        label=f"{LABEL}: {source_name}",
    )
    distribution = ZoneDistribution(
        provider_activity_id=source.stored.provider_activity_id,
        provenance=provenance,
        origin=ActivityDetailOrigin.FETCH,
        metric=metric,
        boundary_source=ZoneBoundarySource.PROFILE,
        buckets=buckets,
    )
    return DetailCandidate(
        started_at=source.started_at,
        device_type=source.device_type,
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


def max_step_s(time_s: Sequence[float]) -> float | None:
    """Longest step still counted as recorded time, or None without a step.

    A step above ``max(MIN_GAP_S, GAP_FACTOR x median step)`` is a pause or dropout.
    """
    steps = [right - left for left, right in pairwise(time_s) if right > left]
    if not steps:
        return None
    return max(MIN_GAP_S, GAP_FACTOR * statistics.median(steps))


def _seconds(
    time_s: tuple[float, ...],
    values: tuple[float | None, ...],
    moving: tuple[float | None, ...] | None,
    zone_of: Callable[[float], int | None],
    zones: int,
    *,
    count_zero: bool,
) -> list[float]:
    """Seconds per zone; the last sample and samples before a gap count nothing."""
    seconds = [0.0] * zones
    max_step = max_step_s(time_s)
    if max_step is None:
        return seconds
    flags = moving if moving is not None else (1.0,) * len(values)
    for (start, end), value, flag in zip(
        pairwise(time_s), values[:-1], flags[:-1], strict=True
    ):
        step = end - start
        if (flag or 0.0) < 1.0:
            continue
        if value is None or value < 0 or (value == 0 and not count_zero):
            continue
        zone = zone_of(value)
        if zone is not None and 0 < step <= max_step:
            seconds[zone - 1] += step
    return seconds
