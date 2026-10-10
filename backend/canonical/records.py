"""Immutable canonical records. Validation runs when each record is constructed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
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

    def __post_init__(self) -> None:
        require_instance(self.kind, MetricKind, "kind")
        metric = require_instance(self.value, MetricValue, "value")
        validate_metric_value(self.kind, metric.value, metric.unit)
        require_date(self.observed_on, "observed_on")
        optional_aware_datetime(self.observed_at, "observed_at")
        require_instance(self.provenance, Provenance, "provenance")


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
        optional_text(self.name, "name", max_length=200)
