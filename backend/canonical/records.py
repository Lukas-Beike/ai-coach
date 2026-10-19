"""Immutable canonical records. Validation runs when each record is constructed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_ALTITUDE_M,
    MAX_ACTIVITY_CADENCE_RPM,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_ELEVATION_M,
    MAX_ACTIVITY_ENERGY_KJ,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
    MAX_ACTIVITY_SPEED_MPS,
    MAX_ACTIVITY_STEPS,
    MIN_ACTIVITY_ALTITUDE_M,
    finite_number,
    optional_aware_datetime,
    optional_bounded_number,
    optional_text,
    require_aware_datetime,
    require_date,
    require_instance,
    require_text,
    validate_metric_value,
)
from backend.canonical.vocabulary import (
    DeviceType,
    Environment,
    LoadModel,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)


@dataclass(frozen=True, slots=True)
class MetricValue:
    """A number with its unit. The unit is checked against a MetricKind by Observation."""

    value: float
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", finite_number(self.value, "value"))
        require_text(self.unit, "unit", max_length=16)


# Provider-reported and device-measured values must name the provider that
# supplied them. Athlete-entered, AI-estimated and profile values must not be
# attributed to a provider; derived values may name the provider they came from.
_PROVIDER_REQUIRED: Final = frozenset(
    {SourceKind.PROVIDER_REPORTED, SourceKind.DEVICE_MEASURED}
)
_PROVIDER_FORBIDDEN: Final = frozenset(
    {SourceKind.ATHLETE_ENTERED, SourceKind.AI_ESTIMATE, SourceKind.PROFILE}
)


@dataclass(frozen=True, slots=True)
class Provenance:
    provider: ProviderId | None
    source_kind: SourceKind
    source_record_id: str | None
    recorded_by: RecordingOrigin
    retrieved_at: datetime | None
    label: str | None

    def __post_init__(self) -> None:
        require_instance(self.source_kind, SourceKind, "source_kind")
        if self.provider is None:
            if self.source_kind in _PROVIDER_REQUIRED:
                raise ValueError(
                    f"provider is required for {self.source_kind.value} values"
                )
        else:
            require_instance(self.provider, ProviderId, "provider")
            if self.source_kind in _PROVIDER_FORBIDDEN:
                raise ValueError(
                    f"provider must be None for {self.source_kind.value} values"
                )
        require_instance(self.recorded_by, RecordingOrigin, "recorded_by")
        optional_text(self.source_record_id, "source_record_id")
        optional_aware_datetime(self.retrieved_at, "retrieved_at")
        optional_text(self.label, "label")


@dataclass(frozen=True, slots=True)
class Observation:
    kind: MetricKind
    value: MetricValue
    observed_on: date
    observed_at: datetime | None
    provenance: Provenance
    sport: Sport | None = None

    def __post_init__(self) -> None:
        require_instance(self.kind, MetricKind, "kind")
        metric = require_instance(self.value, MetricValue, "value")
        validate_metric_value(self.kind, metric.value, metric.unit)
        require_date(self.observed_on, "observed_on")
        optional_aware_datetime(self.observed_at, "observed_at")
        require_instance(self.provenance, Provenance, "provenance")
        if self.sport is not None:
            require_instance(self.sport, Sport, "sport")


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    activity_id: str
    provenance: Provenance
    sport: Sport
    environment: Environment
    started_at: datetime
    duration_s: float | None
    distance_m: float | None
    load: float | None
    load_model: LoadModel
    avg_hr: float | None
    avg_power: float | None
    name: str | None
    moving_duration_s: float | None = None
    elevation_gain_m: float | None = None
    normalized_power: float | None = None
    avg_cadence: float | None = None
    energy_kj: float | None = None
    # Elapsed time when ``duration_s`` is moving time (Intervals.icu); otherwise None.
    elapsed_duration_s: float | None = None
    max_hr: float | None = None
    max_speed_mps: float | None = None
    max_power_w: float | None = None
    min_hr: float | None = None
    elevation_high_m: float | None = None
    elevation_low_m: float | None = None
    steps: float | None = None
    device_type: DeviceType | None = None

    def __post_init__(self) -> None:
        require_text(self.activity_id, "activity_id")
        require_instance(self.provenance, Provenance, "provenance")
        require_instance(self.sport, Sport, "sport")
        require_instance(self.environment, Environment, "environment")
        require_aware_datetime(self.started_at, "started_at")
        object.__setattr__(
            self,
            "duration_s",
            optional_bounded_number(
                self.duration_s, "duration_s", 0.0, MAX_ACTIVITY_DURATION_S
            ),
        )
        object.__setattr__(
            self,
            "distance_m",
            optional_bounded_number(
                self.distance_m, "distance_m", 0.0, MAX_ACTIVITY_DISTANCE_M
            ),
        )
        object.__setattr__(
            self,
            "load",
            optional_bounded_number(self.load, "load", 0.0, MAX_ACTIVITY_LOAD),
        )
        require_instance(self.load_model, LoadModel, "load_model")
        object.__setattr__(
            self,
            "avg_hr",
            optional_bounded_number(self.avg_hr, "avg_hr", *HEART_RATE_BOUNDS),
        )
        object.__setattr__(
            self,
            "avg_power",
            optional_bounded_number(
                self.avg_power, "avg_power", 0.0, MAX_ACTIVITY_POWER_W
            ),
        )
        object.__setattr__(
            self,
            "moving_duration_s",
            optional_bounded_number(
                self.moving_duration_s,
                "moving_duration_s",
                0.0,
                MAX_ACTIVITY_DURATION_S,
            ),
        )
        object.__setattr__(
            self,
            "elevation_gain_m",
            optional_bounded_number(
                self.elevation_gain_m, "elevation_gain_m", 0.0, MAX_ACTIVITY_ELEVATION_M
            ),
        )
        object.__setattr__(
            self,
            "normalized_power",
            optional_bounded_number(
                self.normalized_power, "normalized_power", 0.0, MAX_ACTIVITY_POWER_W
            ),
        )
        object.__setattr__(
            self,
            "avg_cadence",
            optional_bounded_number(
                self.avg_cadence, "avg_cadence", 0.0, MAX_ACTIVITY_CADENCE_RPM
            ),
        )
        object.__setattr__(
            self,
            "energy_kj",
            optional_bounded_number(
                self.energy_kj, "energy_kj", 0.0, MAX_ACTIVITY_ENERGY_KJ
            ),
        )
        object.__setattr__(
            self,
            "elapsed_duration_s",
            optional_bounded_number(
                self.elapsed_duration_s,
                "elapsed_duration_s",
                0.0,
                MAX_ACTIVITY_DURATION_S,
            ),
        )
        object.__setattr__(
            self,
            "max_hr",
            optional_bounded_number(self.max_hr, "max_hr", *HEART_RATE_BOUNDS),
        )
        object.__setattr__(
            self,
            "max_speed_mps",
            optional_bounded_number(
                self.max_speed_mps, "max_speed_mps", 0.0, MAX_ACTIVITY_SPEED_MPS
            ),
        )
        object.__setattr__(
            self,
            "max_power_w",
            optional_bounded_number(
                self.max_power_w, "max_power_w", 0.0, MAX_ACTIVITY_POWER_W
            ),
        )
        object.__setattr__(
            self,
            "min_hr",
            optional_bounded_number(self.min_hr, "min_hr", *HEART_RATE_BOUNDS),
        )
        object.__setattr__(
            self,
            "elevation_high_m",
            optional_bounded_number(
                self.elevation_high_m,
                "elevation_high_m",
                MIN_ACTIVITY_ALTITUDE_M,
                MAX_ACTIVITY_ALTITUDE_M,
            ),
        )
        object.__setattr__(
            self,
            "elevation_low_m",
            optional_bounded_number(
                self.elevation_low_m,
                "elevation_low_m",
                MIN_ACTIVITY_ALTITUDE_M,
                MAX_ACTIVITY_ALTITUDE_M,
            ),
        )
        if (
            self.elevation_low_m is not None
            and self.elevation_high_m is not None
            and self.elevation_low_m > self.elevation_high_m
        ):
            raise ValueError("elevation_low_m must not exceed elevation_high_m")
        object.__setattr__(
            self,
            "steps",
            optional_bounded_number(self.steps, "steps", 0.0, MAX_ACTIVITY_STEPS),
        )
        if self.device_type is not None:
            require_instance(self.device_type, DeviceType, "device_type")
        optional_text(self.name, "name", max_length=200)
