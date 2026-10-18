"""Immutable detail sets of one provider activity: streams, laps and zone times.

Each set belongs to exactly one provider activity, so several providers can
offer alternative sets for the same canonical session. Choosing between them is
a read-time decision; these records only guarantee that each set is internally
consistent. Like backend.canonical.records, construction fails fast: mappers
clean provider values (``clean_series``) before building a set.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType
from typing import Final

from backend.canonical.records import Provenance
from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_CADENCE_RPM,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_ELEVATION_M,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
    bounded_number,
    optional_bounded_number,
    optional_text,
    require_instance,
    require_text,
)
from backend.canonical.vocabulary import (
    ActivityDetailKind,
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)

MAX_STREAM_POINTS: Final = 172_800
MAX_STREAM_SPAN_S: Final = 172_800.0
MAX_LAPS: Final = 200
MAX_ZONES: Final = 20
MAX_SPEED_MPS: Final = 100.0
MAX_INTENSITY_PCT: Final = 1_000.0
MAX_LAP_NAME_LENGTH: Final = 200
MAX_ZONE_LABEL_LENGTH: Final = 64

CHANNEL_BOUNDS: Final[Mapping[StreamChannel, tuple[float, float]]] = {
    StreamChannel.TIME_S: (0.0, MAX_ACTIVITY_DURATION_S),
    StreamChannel.DISTANCE_M: (0.0, MAX_ACTIVITY_DISTANCE_M),
    StreamChannel.ALTITUDE_M: (-1_000.0, 10_000.0),
    StreamChannel.GRADE_PCT: (-100.0, 100.0),
    StreamChannel.SPEED_MPS: (0.0, MAX_SPEED_MPS),
    StreamChannel.POWER_W: (0.0, MAX_ACTIVITY_POWER_W),
    StreamChannel.HEART_RATE_BPM: HEART_RATE_BOUNDS,
    StreamChannel.CADENCE_RPM: (0.0, MAX_ACTIVITY_CADENCE_RPM),
    StreamChannel.TEMPERATURE_C: (-60.0, 70.0),
    StreamChannel.MOVING: (0.0, 1.0),
}

ZONE_BOUNDARY_BOUNDS: Final[Mapping[ZoneMetric, tuple[float, float]]] = {
    ZoneMetric.HEART_RATE: (0.0, HEART_RATE_BOUNDS[1]),
    ZoneMetric.POWER: (0.0, MAX_ACTIVITY_POWER_W),
}


def clean_series(
    channel: StreamChannel, values: Iterable[object]
) -> tuple[tuple[float | None, ...], int]:
    """Return the points of one channel with unusable values replaced by None.

    Non-numbers, booleans, non-finite and out-of-range points become gaps; the
    second item counts the replaced points so mappers can report them.
    """
    lower, upper = CHANNEL_BOUNDS[channel]
    cleaned: list[float | None] = []
    rejected = 0
    for value in values:
        if value is None:
            cleaned.append(None)
            continue
        try:
            # float() raises OverflowError for integers beyond the float range.
            point = (
                float(value)
                if isinstance(value, int | float) and not isinstance(value, bool)
                else math.nan
            )
        except OverflowError:
            point = math.nan
        if not math.isfinite(point) or not lower <= point <= upper:
            cleaned.append(None)
            rejected += 1
            continue
        cleaned.append(point)
    return tuple(cleaned), rejected


def _require_detail_header(
    provider_activity_id: object, provenance: object, origin: object
) -> None:
    require_text(provider_activity_id, "provider_activity_id")
    source = require_instance(provenance, Provenance, "provenance")
    if source.provider is None:
        raise ValueError("provenance.provider is required for activity details")
    require_instance(origin, ActivityDetailOrigin, "origin")


@dataclass(frozen=True, slots=True)
class ActivityStreamSet:
    """Equal-length channels on one strictly increasing time axis (``time_s``)."""

    provider_activity_id: str
    provenance: Provenance
    origin: ActivityDetailOrigin
    resolution: StreamResolution
    channels: Mapping[StreamChannel, tuple[float | None, ...]]

    @property
    def kind(self) -> ActivityDetailKind:
        return ActivityDetailKind.STREAMS

    def __post_init__(self) -> None:
        _require_detail_header(self.provider_activity_id, self.provenance, self.origin)
        require_instance(self.resolution, StreamResolution, "resolution")
        channels = require_instance(self.channels, Mapping, "channels")
        frozen: dict[StreamChannel, tuple[float | None, ...]] = {}
        for channel, values in channels.items():
            require_instance(channel, StreamChannel, "channel")
            frozen[channel] = _validated_series(channel, values)
        time = frozen.get(StreamChannel.TIME_S)
        if time is None:
            raise ValueError("channels must include time_s")
        if not 1 <= len(time) <= MAX_STREAM_POINTS:
            raise ValueError(f"time_s must have between 1 and {MAX_STREAM_POINTS} points")
        if any(point is None for point in time):
            raise ValueError("time_s must not contain gaps")
        axis = [point for point in time if point is not None]
        if any(right <= left for left, right in pairwise(axis)):
            raise ValueError("time_s must be strictly increasing")
        if axis[-1] - axis[0] > MAX_STREAM_SPAN_S:
            raise ValueError(f"time_s must span at most {MAX_STREAM_SPAN_S:g} seconds")
        for channel, values in frozen.items():
            if len(values) != len(time):
                raise ValueError(f"{channel.value} must have as many points as time_s")
        if len(frozen) < 2:
            raise ValueError("channels must include at least one channel besides time_s")
        object.__setattr__(self, "channels", MappingProxyType(frozen))


def _validated_series(
    channel: StreamChannel, values: object
) -> tuple[float | None, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Iterable):
        raise TypeError(f"{channel.value} must be a sequence of numbers")
    lower, upper = CHANNEL_BOUNDS[channel]
    return tuple(
        None
        if value is None
        else bounded_number(value, f"{channel.value} point", lower, upper)
        for value in values
    )


@dataclass(frozen=True, slots=True)
class ActivityLap:
    """One lap or interval; offsets are seconds from the activity start."""

    index: int
    kind: LapKind
    start_offset_s: float
    end_offset_s: float
    name: str | None = None
    moving_duration_s: float | None = None
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_power: float | None = None
    max_power: float | None = None
    normalized_power: float | None = None
    avg_cadence: float | None = None
    avg_speed_mps: float | None = None
    elevation_gain_m: float | None = None
    load: float | None = None
    intensity_pct: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError("index must be an integer")
        if not 0 <= self.index < MAX_LAPS:
            raise ValueError(f"index must be between 0 and {MAX_LAPS - 1}")
        require_instance(self.kind, LapKind, "kind")
        start = bounded_number(
            self.start_offset_s, "start_offset_s", 0.0, MAX_ACTIVITY_DURATION_S
        )
        end = bounded_number(
            self.end_offset_s, "end_offset_s", 0.0, MAX_ACTIVITY_DURATION_S
        )
        if end < start:
            raise ValueError("end_offset_s must not be before start_offset_s")
        object.__setattr__(self, "start_offset_s", start)
        object.__setattr__(self, "end_offset_s", end)
        optional_text(self.name, "name", max_length=MAX_LAP_NAME_LENGTH)
        for name, (lower, upper) in _LAP_METRIC_BOUNDS.items():
            object.__setattr__(
                self,
                name,
                optional_bounded_number(getattr(self, name), name, lower, upper),
            )


_LAP_METRIC_BOUNDS: Final[Mapping[str, tuple[float, float]]] = {
    "moving_duration_s": (0.0, MAX_ACTIVITY_DURATION_S),
    "distance_m": (0.0, MAX_ACTIVITY_DISTANCE_M),
    "avg_hr": HEART_RATE_BOUNDS,
    "max_hr": HEART_RATE_BOUNDS,
    "avg_power": (0.0, MAX_ACTIVITY_POWER_W),
    "max_power": (0.0, MAX_ACTIVITY_POWER_W),
    "normalized_power": (0.0, MAX_ACTIVITY_POWER_W),
    "avg_cadence": (0.0, MAX_ACTIVITY_CADENCE_RPM),
    "avg_speed_mps": (0.0, MAX_SPEED_MPS),
    "elevation_gain_m": (0.0, MAX_ACTIVITY_ELEVATION_M),
    "load": (0.0, MAX_ACTIVITY_LOAD),
    "intensity_pct": (0.0, MAX_INTENSITY_PCT),
}
LAP_METRIC_FIELDS: Final = tuple(_LAP_METRIC_BOUNDS)


@dataclass(frozen=True, slots=True)
class ActivityLapSet:
    provider_activity_id: str
    provenance: Provenance
    origin: ActivityDetailOrigin
    lap_source: LapSource
    laps: tuple[ActivityLap, ...]

    @property
    def kind(self) -> ActivityDetailKind:
        return ActivityDetailKind.LAPS

    def __post_init__(self) -> None:
        _require_detail_header(self.provider_activity_id, self.provenance, self.origin)
        require_instance(self.lap_source, LapSource, "lap_source")
        laps = require_instance(self.laps, tuple, "laps")
        if not 1 <= len(laps) <= MAX_LAPS:
            raise ValueError(f"laps must contain between 1 and {MAX_LAPS} laps")
        for position, lap in enumerate(laps):
            require_instance(lap, ActivityLap, "lap")
            if lap.index != position:
                raise ValueError("lap indexes must be consecutive from 0")
        if any(
            right.start_offset_s < left.start_offset_s for left, right in pairwise(laps)
        ):
            raise ValueError("laps must be ordered by start_offset_s")


@dataclass(frozen=True, slots=True)
class ZoneBucket:
    """Seconds spent in one zone; zone indexes start at 1."""

    index: int
    seconds: float
    lower: float | None = None
    upper: float | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError("index must be an integer")
        if not 1 <= self.index <= MAX_ZONES:
            raise ValueError(f"index must be between 1 and {MAX_ZONES}")
        object.__setattr__(
            self,
            "seconds",
            bounded_number(self.seconds, "seconds", 0.0, MAX_ACTIVITY_DURATION_S),
        )
        optional_text(self.label, "label", max_length=MAX_ZONE_LABEL_LENGTH)


@dataclass(frozen=True, slots=True)
class ZoneDistribution:
    provider_activity_id: str
    provenance: Provenance
    origin: ActivityDetailOrigin
    metric: ZoneMetric
    boundary_source: ZoneBoundarySource
    buckets: tuple[ZoneBucket, ...]

    def __post_init__(self) -> None:
        _require_detail_header(self.provider_activity_id, self.provenance, self.origin)
        metric = require_instance(self.metric, ZoneMetric, "metric")
        require_instance(self.boundary_source, ZoneBoundarySource, "boundary_source")
        buckets = require_instance(self.buckets, tuple, "buckets")
        if not 1 <= len(buckets) <= MAX_ZONES:
            raise ValueError(f"buckets must contain between 1 and {MAX_ZONES} zones")
        lower_bound, upper_bound = ZONE_BOUNDARY_BOUNDS[metric]
        for position, bucket in enumerate(buckets, start=1):
            require_instance(bucket, ZoneBucket, "bucket")
            if bucket.index != position:
                raise ValueError("zone indexes must be consecutive from 1")
            lower = optional_bounded_number(
                bucket.lower, "lower", lower_bound, upper_bound
            )
            upper = optional_bounded_number(
                bucket.upper, "upper", lower_bound, upper_bound
            )
            if lower is not None and upper is not None and upper < lower:
                raise ValueError("zone upper boundary must not be below lower boundary")

    @property
    def kind(self) -> ActivityDetailKind:
        return self.metric.detail_kind


type ActivityDetailSet = ActivityStreamSet | ActivityLapSet | ZoneDistribution
