"""Immutable canonical records. Validation runs when each record is constructed."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
    bounded_number,
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
    ObservationAggregation,
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


# Method names and context slugs are short lowercase identifiers such as
# "rmssd" or "optical_wrist".
_SLUG: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_FIRMWARE: Final = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,31}")
# A long hex or digit run in a model name is a serial, unit or owner id.
_IDENTIFIER_RUN: Final = re.compile(r"[0-9A-Fa-f]{8,}|\d{6,}", re.ASCII)
_FINGERPRINT: Final = re.compile(r"[0-9a-f]{64}")
_CONTEXT_FIELDS: Final = (
    "device_model",
    "firmware",
    "algorithm",
    "sensor",
    "window",
    "protocol",
)
MAX_METHOD_VERSION: Final = 10_000
MAX_OBSERVATION_PERIOD: Final = timedelta(days=366)


def optional_slug(value: object, field: str) -> str | None:
    """Return a lowercase identifier such as a method or sensor name, or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    if _SLUG.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase identifier")
    return value


def utc_instant(value: object, field: str) -> datetime:
    """Return an aware datetime as the same instant in UTC.

    Aware datetimes that share a tzinfo compare and subtract by wall time, which
    is wrong across a DST change; UTC values give the true order and duration.
    """
    moment = require_aware_datetime(value, field)
    try:
        return moment.astimezone(UTC)
    except OverflowError as error:
        raise ValueError(f"{field} must be within the datetime range") from error


def fingerprint_inputs(inputs: Mapping[str, object]) -> str:
    """Return the SHA-256 of the canonical JSON of a derivation's inputs."""
    encoded = json.dumps(
        dict(inputs),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# FORM derived as CTL minus ATL when a wellness row reports no form.
FORM_METHOD: Final = "ctl_minus_atl"
FORM_METHOD_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class MeasurementContext:
    """How a value was measured. None means the provider did not report it.

    Fields are never guessed from the provider brand. A device model that
    contains a serial-like identifier is rejected, so no device or owner id is
    stored.
    """

    device_model: str | None = None
    firmware: str | None = None
    algorithm: str | None = None
    sensor: str | None = None
    window: str | None = None
    protocol: str | None = None

    def __post_init__(self) -> None:
        if self.device_model is not None:
            model = require_text(self.device_model, "device_model", max_length=100)
            if not model.isprintable() or model != model.strip():
                raise ValueError("device_model must be trimmed printable text")
            if _IDENTIFIER_RUN.search(model) is not None:
                raise ValueError("device_model must not contain a device identifier")
        if self.firmware is not None:
            if not isinstance(self.firmware, str):
                raise TypeError("firmware must be text")
            if _FIRMWARE.fullmatch(self.firmware) is None:
                raise ValueError("firmware must be a short version text")
        for field in _CONTEXT_FIELDS[2:]:
            optional_slug(getattr(self, field), field)

    @property
    def is_unknown(self) -> bool:
        return all(getattr(self, field) is None for field in _CONTEXT_FIELDS)

    @property
    def identity(self) -> str:
        """Stable hash of every field, unknown ones included; differs when any changes."""
        values = ["measurement-context-v1"]
        values.extend(getattr(self, field) for field in _CONTEXT_FIELDS)
        encoded = json.dumps(values, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def as_details(self) -> dict[str, str]:
        """Return the known fields only; an unknown context is empty."""
        return {
            field: value
            for field in _CONTEXT_FIELDS
            if (value := getattr(self, field)) is not None
        }

    @classmethod
    def from_details(cls, details: object) -> MeasurementContext:
        """Rebuild a context from ``as_details`` output; other keys are rejected."""
        if not isinstance(details, dict):
            raise TypeError("measurement context must be an object")
        if not set(details) <= set(_CONTEXT_FIELDS):
            raise ValueError("measurement context has unsupported fields")
        return cls(**details)


UNKNOWN_CONTEXT: Final = MeasurementContext()


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
    context: MeasurementContext = UNKNOWN_CONTEXT

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
        require_instance(self.context, MeasurementContext, "context")


@dataclass(frozen=True, slots=True)
class ObservationPeriod:
    """The interval a value summarizes, such as one night for overnight HRV.

    The bounds are kept in UTC, so order and length are those of the instants.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", utc_instant(self.start, "period start"))
        object.__setattr__(self, "end", utc_instant(self.end, "period end"))
        if self.end <= self.start:
            raise ValueError("period end must be after its start")
        if self.end - self.start > MAX_OBSERVATION_PERIOD:
            raise ValueError("period must not exceed 366 days")


@dataclass(frozen=True, slots=True)
class Observation:
    kind: MetricKind
    value: MetricValue
    observed_on: date
    observed_at: datetime | None
    provenance: Provenance
    sport: Sport | None = None
    # How the value was produced. A derived value must name its method, the
    # method version and the fingerprint of its inputs (see fingerprint_inputs).
    method: str | None = None
    aggregation: ObservationAggregation | None = None
    method_version: int | None = None
    input_fingerprint: str | None = None
    period: ObservationPeriod | None = None

    def __post_init__(self) -> None:
        require_instance(self.kind, MetricKind, "kind")
        metric = require_instance(self.value, MetricValue, "value")
        validate_metric_value(self.kind, metric.value, metric.unit)
        require_date(self.observed_on, "observed_on")
        optional_aware_datetime(self.observed_at, "observed_at")
        require_instance(self.provenance, Provenance, "provenance")
        if self.sport is not None:
            require_instance(self.sport, Sport, "sport")
        optional_slug(self.method, "method")
        if self.aggregation is not None:
            require_instance(self.aggregation, ObservationAggregation, "aggregation")
        _require_method_identity(self.method_version, self.input_fingerprint)
        if self.method is None and (
            self.method_version is not None or self.input_fingerprint is not None
        ):
            raise ValueError("method_version and input_fingerprint require a method")
        if self.provenance.source_kind is SourceKind.DERIVED and (
            self.method is None
            or self.method_version is None
            or self.input_fingerprint is None
        ):
            raise ValueError(
                "derived observations require method, method_version and input_fingerprint"
            )
        if self.period is not None:
            require_instance(self.period, ObservationPeriod, "period")


def _require_method_identity(method_version: object, input_fingerprint: object) -> None:
    if method_version is not None:
        if isinstance(method_version, bool) or not isinstance(method_version, int):
            raise TypeError("method_version must be an integer")
        if not 1 <= method_version <= MAX_METHOD_VERSION:
            raise ValueError("method_version must be between 1 and 10000")
    if input_fingerprint is not None and (
        not isinstance(input_fingerprint, str)
        or _FINGERPRINT.fullmatch(input_fingerprint) is None
    ):
        raise ValueError("input_fingerprint must be a lowercase SHA-256 hex digest")


type ZoneSeconds = tuple[tuple[str, float], ...]

MAX_ZONE_COUNT: Final = 20
MAX_ZONE_ID_LENGTH: Final = 20
_SUMMARY_VALUE_BOUNDS: Final = (
    ("intensity", 0.0, 1_000.0),
    ("rpe", 0.0, 10.0),
    ("feel", 0.0, 10.0),
    ("avg_speed_mps", 0.0, MAX_ACTIVITY_SPEED_MPS),
    ("weighted_avg_speed_mps", 0.0, MAX_ACTIVITY_SPEED_MPS),
    ("pace_mps", 0.0, MAX_ACTIVITY_SPEED_MPS),
    ("ftp_w", 0.0, MAX_ACTIVITY_POWER_W),
    ("eftp_w", 0.0, MAX_ACTIVITY_POWER_W),
    ("vo2max", 0.0, 100.0),
    ("avg_temp_c", -60.0, 70.0),
)
_ZONE_FIELDS: Final = ("power_zone_times_s", "hr_zone_times_s", "pace_zone_times_s")


def _zone_seconds(value: object, field: str) -> ZoneSeconds | None:
    """Validate (zone id, seconds) pairs; an empty tuple is None."""
    if value is None:
        return None
    if not isinstance(value, tuple) or len(value) > MAX_ZONE_COUNT:
        raise ValueError(f"{field} must be a tuple of at most {MAX_ZONE_COUNT} zones")
    zones: list[tuple[str, float]] = []
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError(f"{field} items must be (zone id, seconds) pairs")
        zone_id, seconds = item
        require_text(zone_id, field, max_length=MAX_ZONE_ID_LENGTH)
        zones.append(
            (zone_id, bounded_number(seconds, field, 0.0, MAX_ACTIVITY_DURATION_S))
        )
    return tuple(zones) or None


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
    # Elapsed time including pauses, whichever provider reported it; None if unknown.
    elapsed_duration_s: float | None = None
    max_hr: float | None = None
    max_speed_mps: float | None = None
    max_power_w: float | None = None
    min_hr: float | None = None
    elevation_high_m: float | None = None
    elevation_low_m: float | None = None
    steps: float | None = None
    device_type: DeviceType | None = None
    # Summary values a provider reports besides the measurements above.
    # Intensity is the provider's intensity factor in percent of FTP.
    intensity: float | None = None
    rpe: float | None = None
    feel: float | None = None
    avg_speed_mps: float | None = None
    weighted_avg_speed_mps: float | None = None
    pace_mps: float | None = None
    ftp_w: float | None = None
    eftp_w: float | None = None
    vo2max: float | None = None
    avg_temp_c: float | None = None
    # Seconds per zone as (zone id, seconds) pairs, ids such as "Z1".
    power_zone_times_s: ZoneSeconds | None = None
    hr_zone_times_s: ZoneSeconds | None = None
    pace_zone_times_s: ZoneSeconds | None = None
    # The provider calendar event the activity was paired with, if any.
    planned_event_id: str | None = None

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
        for field, lower, upper in _SUMMARY_VALUE_BOUNDS:
            object.__setattr__(
                self,
                field,
                optional_bounded_number(getattr(self, field), field, lower, upper),
            )
        for field in _ZONE_FIELDS:
            object.__setattr__(self, field, _zone_seconds(getattr(self, field), field))
        optional_text(self.planned_event_id, "planned_event_id", max_length=200)
