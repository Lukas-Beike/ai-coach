"""Read-time choice between alternative provider detail sets of one session.

Several provider activities can be bundled into one canonical session, and each
may hold its own streams, laps and zone times. This module picks, without I/O,
which set to show for each part: the primary stream set fixes the time axis, and
each channel comes from the best-ranked set that can be placed on that axis.
Inputs are never mutated; ranking is deterministic.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median
from types import MappingProxyType
from typing import Final

from backend.canonical.activity_detail import (
    ActivityLapSet,
    ActivityStreamSet,
    ZoneDistribution,
)
from backend.canonical.vocabulary import (
    DeviceType,
    LapSource,
    ProviderId,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.activity_detail_store import StoredDetailSet

MIN_ALIGNMENT_OVERLAP: Final = 0.8
ALIGNMENT_TOLERANCE_INTERVALS: Final = 2.0

_PROVIDER_RANK: Final[Mapping[str, int]] = {
    provider.value: rank
    for rank, provider in enumerate(
        (ProviderId.INTERVALS, ProviderId.GARMIN, ProviderId.WAHOO)
    )
}
_UNKNOWN_PROVIDER_RANK: Final = len(_PROVIDER_RANK)
_RESOLUTION_RANK: Final[Mapping[StreamResolution, int]] = {
    StreamResolution.FULL: 0,
    StreamResolution.DOWNSAMPLED: 1,
}
_LAP_SOURCE_RANK: Final[Mapping[LapSource, int]] = {
    LapSource.PROVIDER_INTERVALS: 0,
    LapSource.DEVICE_LAPS: 1,
    LapSource.SPLITS: 2,
}
# Lower rank is better; channels missing here have no device ranking.
_DEVICE_PREFERENCE: Final[Mapping[StreamChannel, tuple[DeviceType, ...]]] = {
    StreamChannel.HEART_RATE_BPM: (
        DeviceType.CHEST_STRAP,
        DeviceType.WATCH,
        DeviceType.BIKE_COMPUTER,
    ),
    StreamChannel.POWER_W: (
        DeviceType.POWER_METER,
        DeviceType.BIKE_COMPUTER,
        DeviceType.WATCH,
    ),
    StreamChannel.CADENCE_RPM: (
        DeviceType.POWER_METER,
        DeviceType.BIKE_COMPUTER,
        DeviceType.WATCH,
    ),
    StreamChannel.SPEED_MPS: (DeviceType.BIKE_COMPUTER, DeviceType.WATCH),
    StreamChannel.DISTANCE_M: (DeviceType.BIKE_COMPUTER, DeviceType.WATCH),
    StreamChannel.ALTITUDE_M: (DeviceType.BIKE_COMPUTER, DeviceType.WATCH),
    StreamChannel.GRADE_PCT: (DeviceType.BIKE_COMPUTER, DeviceType.WATCH),
}


@dataclass(frozen=True, slots=True)
class DetailCandidate:
    """A stored detail set with the start and device class of its provider record."""

    stored: StoredDetailSet
    started_at: datetime | None
    device_type: DeviceType | None


@dataclass(frozen=True, slots=True)
class ChannelChoice:
    """One channel on the primary time axis and the set it was taken from."""

    values: tuple[float | None, ...]
    source: DetailCandidate
    aligned: bool


@dataclass(frozen=True, slots=True)
class MergedStreams:
    """The primary stream set's time axis and the chosen value of every channel."""

    primary: DetailCandidate
    time_s: tuple[float, ...]
    channels: Mapping[StreamChannel, ChannelChoice]
    alternatives: tuple[DetailCandidate, ...]


@dataclass(frozen=True, slots=True)
class SetChoice:
    """The set shown for one kind and the ranked sets it was preferred over."""

    chosen: DetailCandidate
    alternatives: tuple[DetailCandidate, ...]


@dataclass(frozen=True, slots=True)
class MergedDetail:
    """Everything shown for one canonical session; absent kinds are None or empty."""

    streams: MergedStreams | None
    laps: SetChoice | None
    zones: Mapping[ZoneMetric, SetChoice]


def merge_details(candidates: Iterable[DetailCandidate]) -> MergedDetail:
    """Choose the stream, lap and zone sets to show for one canonical session."""
    items = tuple(candidates)
    stream_items = [c for c in items if isinstance(c.stored.detail, ActivityStreamSet)]
    lap_items = [c for c in items if isinstance(c.stored.detail, ActivityLapSet)]
    zone_items = [c for c in items if isinstance(c.stored.detail, ZoneDistribution)]
    return MergedDetail(
        streams=_merge_streams(stream_items),
        laps=_choose_laps(lap_items),
        zones=_choose_zones(zone_items),
    )


def clock_offset(candidate: DetailCandidate, primary: DetailCandidate) -> float | None:
    """Seconds from the primary recording start to the candidate's, None when unknown.

    Sets of the same provider recording share its clock.
    """
    if (candidate.stored.provider, candidate.stored.provider_activity_id) == (
        primary.stored.provider,
        primary.stored.provider_activity_id,
    ):
        return 0.0
    if candidate.started_at is None or primary.started_at is None:
        return None
    return (candidate.started_at - primary.started_at).total_seconds()


def stream_average(streams: MergedStreams, channel: StreamChannel) -> float | None:
    """Mean of the channel's values, restricted to moving points when MOVING is shown."""
    if channel in (StreamChannel.TIME_S, StreamChannel.MOVING):
        raise ValueError(f"{channel.value} has no average")
    choice = streams.channels.get(channel)
    if choice is None:
        return None
    moving = streams.channels.get(StreamChannel.MOVING)
    moving_values = moving.values if moving is not None else None
    points = [
        value
        for index, value in enumerate(choice.values)
        if value is not None
        and (moving_values is None or (moving_values[index] or 0.0) >= 1.0)
    ]
    if not points:
        return None
    return math.fsum(points) / len(points)


def _merge_streams(candidates: list[DetailCandidate]) -> MergedStreams | None:
    if not candidates:
        return None
    ranked = sorted(candidates, key=_primary_stream_key)
    primary = ranked[0]
    primary_axis = _axis(primary)
    channels: dict[StreamChannel, ChannelChoice] = {}
    for channel in StreamChannel:
        if channel is StreamChannel.TIME_S or not _has_values(candidates, channel):
            continue
        for candidate in _channel_order(channel, ranked, primary):
            values = _streams_of(candidate).channels[channel]
            placed = _place(candidate, primary, primary_axis, values)
            if placed is not None and any(value is not None for value in placed):
                channels[channel] = ChannelChoice(
                    values=placed,
                    source=candidate,
                    aligned=candidate is not primary,
                )
                break
    return MergedStreams(
        primary=primary,
        time_s=primary_axis,
        channels=MappingProxyType(channels),
        alternatives=tuple(ranked[1:]),
    )


def _channel_order(
    channel: StreamChannel, ranked: list[DetailCandidate], primary: DetailCandidate
) -> list[DetailCandidate]:
    """The stream candidates carrying the channel, best source first."""
    return sorted(
        (c for c in ranked if channel in _streams_of(c).channels),
        key=lambda c: _channel_key(channel, c, primary),
    )


def _choose_laps(candidates: list[DetailCandidate]) -> SetChoice | None:
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda c: (
            _LAP_SOURCE_RANK[_laps_of(c).lap_source],
            _own_copy_rank(c),
            *_tie_break(c),
        ),
    )
    return SetChoice(chosen=ranked[0], alternatives=tuple(ranked[1:]))


def _choose_zones(
    candidates: list[DetailCandidate],
) -> Mapping[ZoneMetric, SetChoice]:
    by_metric: dict[ZoneMetric, list[DetailCandidate]] = {}
    for candidate in candidates:
        by_metric.setdefault(_zones_of(candidate).metric, []).append(candidate)
    zones: dict[ZoneMetric, SetChoice] = {}
    for metric in ZoneMetric:
        if metric not in by_metric:
            continue
        ranked = sorted(
            by_metric[metric],
            key=lambda c: (0 if _zone_is_bounded(_zones_of(c)) else 1, *_tie_break(c)),
        )
        zones[metric] = SetChoice(chosen=ranked[0], alternatives=tuple(ranked[1:]))
    return MappingProxyType(zones)


def _primary_stream_key(candidate: DetailCandidate) -> tuple[object, ...]:
    streams = _streams_of(candidate)
    return (
        _RESOLUTION_RANK[streams.resolution],
        _own_copy_rank(candidate),
        -_populated_channel_count(streams),
        *_tie_break(candidate),
    )


def _channel_key(
    channel: StreamChannel, candidate: DetailCandidate, primary: DetailCandidate
) -> tuple[object, ...]:
    return (
        _RESOLUTION_RANK[_streams_of(candidate).resolution],
        _device_rank(channel, candidate.device_type),
        _own_copy_rank(candidate),
        0 if candidate is primary else 1,
        *_tie_break(candidate),
    )


def _device_rank(channel: StreamChannel, device_type: DeviceType | None) -> int:
    order = _DEVICE_PREFERENCE.get(channel, ())
    if device_type is None or device_type not in order:
        return len(order)
    return order.index(device_type)


def _tie_break(candidate: DetailCandidate) -> tuple[int, float, str]:
    stored = candidate.stored
    return (
        _PROVIDER_RANK.get(stored.provider, _UNKNOWN_PROVIDER_RANK),
        -_fetched_timestamp(stored.fetched_at),
        stored.provider_activity_id,
    )


def _fetched_timestamp(text: str) -> float:
    """Return the POSIX time of an aware ISO timestamp; unusable values sort last."""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return -math.inf
    if parsed.utcoffset() is None:
        return -math.inf
    return parsed.timestamp()


def _own_copy_rank(candidate: DetailCandidate) -> int:
    """Rank 0 for the recording platform's own copy, 1 for a relayed copy."""
    provider = candidate.stored.detail.provenance.provider
    own = provider is not None and provider.value == (
        candidate.stored.detail.provenance.recorded_by.value
    )
    return 0 if own else 1


def _populated_channel_count(streams: ActivityStreamSet) -> int:
    return sum(
        1
        for channel, values in streams.channels.items()
        if channel is not StreamChannel.TIME_S
        and any(value is not None for value in values)
    )


def _has_values(candidates: Sequence[DetailCandidate], channel: StreamChannel) -> bool:
    return any(
        value is not None
        for candidate in candidates
        for value in _streams_of(candidate).channels.get(channel, ())
    )


def _axis(candidate: DetailCandidate) -> tuple[float, ...]:
    return tuple(
        point
        for point in _streams_of(candidate).channels[StreamChannel.TIME_S]
        if point is not None
    )


def _place(
    candidate: DetailCandidate,
    primary: DetailCandidate,
    primary_axis: tuple[float, ...],
    values: tuple[float | None, ...],
) -> tuple[float | None, ...] | None:
    """Return ``values`` on the primary time axis, or None when they cannot be placed."""
    if candidate is primary:
        return values
    axis = _axis(candidate)
    if axis == primary_axis and candidate.started_at == primary.started_at:
        return values
    if candidate.started_at is None or primary.started_at is None:
        return None
    if len(axis) < 2 or len(primary_axis) < 2:
        return None
    offset = (candidate.started_at - primary.started_at).total_seconds()
    shifted = tuple(point + offset for point in axis)
    overlap = min(shifted[-1], primary_axis[-1]) - max(shifted[0], primary_axis[0])
    span = primary_axis[-1] - primary_axis[0]
    if overlap / span < MIN_ALIGNMENT_OVERLAP:
        return None
    tolerance = ALIGNMENT_TOLERANCE_INTERVALS * median(
        later - earlier for earlier, later in pairwise(axis)
    )
    placed: list[float | None] = []
    for point in primary_axis:
        index = _nearest_index(shifted, point)
        within = abs(shifted[index] - point) <= tolerance
        placed.append(values[index] if within else None)
    return tuple(placed)


def _nearest_index(axis: tuple[float, ...], point: float) -> int:
    """Index of the nearest value; exact ties pick the earlier value."""
    position = bisect_left(axis, point)
    if position == 0:
        return 0
    if position == len(axis):
        return len(axis) - 1
    before = point - axis[position - 1]
    after = axis[position] - point
    return position - 1 if before <= after else position


def _streams_of(candidate: DetailCandidate) -> ActivityStreamSet:
    detail = candidate.stored.detail
    if not isinstance(detail, ActivityStreamSet):
        raise TypeError("candidate is not a stream set")
    return detail


def _laps_of(candidate: DetailCandidate) -> ActivityLapSet:
    detail = candidate.stored.detail
    if not isinstance(detail, ActivityLapSet):
        raise TypeError("candidate is not a lap set")
    return detail


def _zones_of(candidate: DetailCandidate) -> ZoneDistribution:
    detail = candidate.stored.detail
    if not isinstance(detail, ZoneDistribution):
        raise TypeError("candidate is not a zone distribution")
    return detail


def _zone_is_bounded(zones: ZoneDistribution) -> bool:
    return zones.boundary_source is not ZoneBoundarySource.UNKNOWN or all(
        bucket.lower is not None or bucket.upper is not None for bucket in zones.buckets
    )
