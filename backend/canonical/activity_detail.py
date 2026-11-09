"""Immutable detail sets of one provider activity: streams, laps, zone times
and executed strength sets.

Each set belongs to exactly one provider activity, so several providers can
offer alternative sets for the same canonical session. Choosing between them is
a read-time decision; these records only guarantee that each set is internally
consistent. Like backend.canonical.records, construction fails fast: mappers
clean provider values (``clean_series``) before building a set.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
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
    POSITION_CHANNELS,
    ActivityDetailKind,
    ActivityDetailOrigin,
    ExerciseCategory,
    HeartRateSource,
    LapKind,
    LapSource,
    PowerSource,
    SensorRole,
    StreamChannel,
    StreamResolution,
    StrengthSetSource,
    StrengthSetType,
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
MAX_STRENGTH_SETS: Final = 500
_INDEX_TYPE_ERROR: Final = "index must be an integer"
MAX_STRENGTH_REPS: Final = 1_000
MAX_STRENGTH_WEIGHT_KG: Final = 1_000.0
MAX_WORKOUT_STEP_INDEX: Final = 999
MAX_EXERCISE_NAME_LENGTH: Final = 64
MAX_SENSORS: Final = 16
SENSOR_KEY_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
SENSOR_ORIGIN_PATTERN: Final = re.compile(r"[a-z_]{1,24}")
# Provider exercise codes such as ``BARBELL_BACK_SQUAT``: untrusted text, so only
# upper-case identifiers are kept, never free text.
EXERCISE_NAME_PATTERN: Final = re.compile(r"[A-Z0-9_]{1,64}")

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
    StreamChannel.LATITUDE_DEG: (-90.0, 90.0),
    StreamChannel.LONGITUDE_DEG: (-180.0, 180.0),
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
class ActivitySensor:
    """One sensor a recording named, identified by a hash and never by its serial.

    ``key`` is the SHA-256 of the manufacturer, product and serial number, so the
    same device is recognized across activities while the serial stays unreadable.
    ``connection`` is the transport the file names (``antplus``, ``bluetooth``,
    ``local`` for the recording device itself).
    """

    role: SensorRole
    key: str
    connection: str | None = None
    manufacturer: int | None = None
    product: int | None = None

    def __post_init__(self) -> None:
        require_instance(self.role, SensorRole, "role")
        if not isinstance(self.key, str) or not SENSOR_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("key must be a lowercase SHA-256 hex digest")
        if self.connection is not None and (
            not isinstance(self.connection, str)
            or not SENSOR_ORIGIN_PATTERN.fullmatch(self.connection)
        ):
            raise ValueError("connection must be a short lower-case identifier")
        for name in ("manufacturer", "product"):
            value = getattr(self, name)
            if value is not None:
                bounded_number(value, name, 0, 65_535)


@dataclass(frozen=True, slots=True)
class ActivityStreamSet:
    """Equal-length channels on one strictly increasing time axis (``time_s``).

    ``hr_source`` and ``power_source`` say what measured those channels when the
    recording names it; None means the provider did not say (or the mapper
    predates the field). ``sensors`` lists the sensors the recording named.
    """

    provider_activity_id: str
    provenance: Provenance
    origin: ActivityDetailOrigin
    resolution: StreamResolution
    channels: Mapping[StreamChannel, tuple[float | None, ...]]
    hr_source: HeartRateSource | None = None
    power_source: PowerSource | None = None
    sensors: tuple[ActivitySensor, ...] = ()

    @property
    def kind(self) -> ActivityDetailKind:
        return ActivityDetailKind.STREAMS

    def __post_init__(self) -> None:
        _require_detail_header(self.provider_activity_id, self.provenance, self.origin)
        require_instance(self.resolution, StreamResolution, "resolution")
        if self.hr_source is not None:
            require_instance(self.hr_source, HeartRateSource, "hr_source")
        if self.power_source is not None:
            require_instance(self.power_source, PowerSource, "power_source")
        sensors = tuple(self.sensors)
        if len(sensors) > MAX_SENSORS:
            raise ValueError(f"sensors must hold at most {MAX_SENSORS} entries")
        for sensor in sensors:
            require_instance(sensor, ActivitySensor, "sensor")
        object.__setattr__(self, "sensors", sensors)
        # Mapping is abstract, so it is checked here rather than via require_instance.
        channels = self.channels
        if not isinstance(channels, Mapping):
            raise TypeError("channels must be a Mapping")
        frozen: dict[StreamChannel, tuple[float | None, ...]] = {}
        for channel, values in channels.items():
            require_instance(channel, StreamChannel, "channel")
            frozen[channel] = _validated_series(channel, values)
        time = frozen.get(StreamChannel.TIME_S)
        if time is None:
            raise ValueError("channels must include time_s")
        if not 1 <= len(time) <= MAX_STREAM_POINTS:
            raise ValueError(
                f"time_s must have between 1 and {MAX_STREAM_POINTS} points"
            )
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
            raise ValueError(
                "channels must include at least one channel besides time_s"
            )
        object.__setattr__(self, "channels", MappingProxyType(frozen))


def without_positions(stream_set: ActivityStreamSet) -> ActivityStreamSet | None:
    """Return the set without GPS channels; None when nothing else is left."""
    if not POSITION_CHANNELS.intersection(stream_set.channels):
        return stream_set
    kept = {
        channel: values
        for channel, values in stream_set.channels.items()
        if channel not in POSITION_CHANNELS
    }
    if len(kept) < 2:
        return None
    return replace(stream_set, channels=kept)


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
    max_speed_mps: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError(_INDEX_TYPE_ERROR)
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
    "max_speed_mps": (0.0, MAX_SPEED_MPS),
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
            raise TypeError(_INDEX_TYPE_ERROR)
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


def _optional_index(value: object, field: str, upper: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if not 0 <= value <= upper:
        raise ValueError(f"{field} must be between 0 and {upper}")
    return value


@dataclass(frozen=True, slots=True)
class ActivityStrengthSet:
    """One executed strength set or the rest after it.

    ``weight_kg`` is None when no external load was reported; it is never 0 as
    a stand-in. ``workout_step_index`` links the set to a step of the planned
    workout the device ran, when there was one.
    """

    index: int
    set_type: StrengthSetType
    exercise_category: ExerciseCategory | None = None
    exercise_name: str | None = None
    reps: int | None = None
    weight_kg: float | None = None
    duration_s: float | None = None
    start_offset_s: float | None = None
    workout_step_index: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError(_INDEX_TYPE_ERROR)
        if not 0 <= self.index < MAX_STRENGTH_SETS:
            raise ValueError(f"index must be between 0 and {MAX_STRENGTH_SETS - 1}")
        require_instance(self.set_type, StrengthSetType, "set_type")
        if self.exercise_category is not None:
            require_instance(
                self.exercise_category, ExerciseCategory, "exercise_category"
            )
        name = optional_text(
            self.exercise_name, "exercise_name", max_length=MAX_EXERCISE_NAME_LENGTH
        )
        if name is not None and not EXERCISE_NAME_PATTERN.fullmatch(name):
            raise ValueError("exercise_name must be an upper-case provider code")
        _optional_index(self.reps, "reps", MAX_STRENGTH_REPS)
        _optional_index(
            self.workout_step_index, "workout_step_index", MAX_WORKOUT_STEP_INDEX
        )
        weight = optional_bounded_number(
            self.weight_kg, "weight_kg", 0.0, MAX_STRENGTH_WEIGHT_KG
        )
        if weight == 0:
            raise ValueError("weight_kg must be None when no load was reported")
        object.__setattr__(self, "weight_kg", weight)
        for field in ("duration_s", "start_offset_s"):
            object.__setattr__(
                self,
                field,
                optional_bounded_number(
                    getattr(self, field), field, 0.0, MAX_ACTIVITY_DURATION_S
                ),
            )


def strength_set_accepts(field: str, value: object) -> bool:
    """Whether ActivityStrengthSet accepts one field value, so mappers share its bounds."""
    values: dict[str, object] = {field: value}
    try:
        ActivityStrengthSet(index=0, set_type=StrengthSetType.ACTIVE, **values)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class ActivityStrengthSetSet:
    """The strength sets of one provider activity, from one source only."""

    provider_activity_id: str
    provenance: Provenance
    origin: ActivityDetailOrigin
    source: StrengthSetSource
    sets: tuple[ActivityStrengthSet, ...]

    @property
    def kind(self) -> ActivityDetailKind:
        return ActivityDetailKind.STRENGTH_SETS

    def __post_init__(self) -> None:
        _require_detail_header(self.provider_activity_id, self.provenance, self.origin)
        require_instance(self.source, StrengthSetSource, "source")
        sets = require_instance(self.sets, tuple, "sets")
        if not 1 <= len(sets) <= MAX_STRENGTH_SETS:
            raise ValueError(
                f"sets must contain between 1 and {MAX_STRENGTH_SETS} sets"
            )
        for position, item in enumerate(sets):
            require_instance(item, ActivityStrengthSet, "set")
            if item.index != position:
                raise ValueError("set indexes must be consecutive from 0")


type ActivityDetailSet = (
    ActivityStreamSet | ActivityLapSet | ZoneDistribution | ActivityStrengthSetSet
)
