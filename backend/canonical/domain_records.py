"""Immutable canonical records for provider domains that are not numeric metrics.

Categorical provider statuses, sleep periods, zone configurations and gear.
Validation runs when each record is constructed, as in ``backend.canonical.records``.
Provider records name their provider and source record, because a re-projection
replaces the rows of one source record; none of them is derived locally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.canonical.local_time import local_date
from backend.canonical.records import Provenance, optional_slug, utc_instant
from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_POWER_W,
    MAX_ACTIVITY_SPEED_MPS,
    bounded_number,
    optional_aware_datetime,
    optional_bounded_number,
    optional_text,
    require_date,
    require_instance,
    require_text,
)
from backend.canonical.vocabulary import (
    CategoricalDomain,
    Environment,
    SleepKind,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)

# Provider status codes such as "PRODUCTIVE" or "BALANCED", kept as reported.
_CODE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# IANA time-zone names such as "Europe/Berlin" or "Etc/GMT+1".
_TIMEZONE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_+/-]{0,63}")
MAX_SLEEP_PERIOD: Final = timedelta(hours=24)
MAX_REPORTED_SLEEP_S: Final = 86_400.0
MAX_ZONES: Final = 19
# Percent limits keep a provider's open-top marker such as 999.
ZONE_PERCENT_BOUNDS: Final = (1.0, 1_000.0)
ZONE_VALUE_BOUNDS: Final = {
    ZoneConfigurationMetric.HEART_RATE: HEART_RATE_BOUNDS,
    ZoneConfigurationMetric.POWER: (1.0, MAX_ACTIVITY_POWER_W),
    # Pace zones are speeds in metres per second.
    ZoneConfigurationMetric.PACE: (0.1, MAX_ACTIVITY_SPEED_MPS),
}
MAX_GEAR_DISTANCE_M: Final = 1_000_000_000.0
MAX_GEAR_ACTIVITIES: Final = 1_000_000


def _require_provider_source(provenance: object) -> Provenance:
    provenance = require_instance(provenance, Provenance, "provenance")
    if provenance.provider is None or provenance.source_record_id is None:
        raise ValueError("provider records need a provider and a source record id")
    if provenance.source_kind is SourceKind.DERIVED:
        raise ValueError("provider records must not be derived")
    return provenance


def _time_zone(value: object) -> ZoneInfo | None:
    """Return the IANA zone a name refers to; None stays an unknown zone."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("timezone must be text")
    if _TIMEZONE.fullmatch(value) is None:
        raise ValueError("timezone must be a time-zone name")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timezone must be a known time-zone name") from error


@dataclass(frozen=True, slots=True)
class CategoricalObservation:
    """A provider status code, such as a training status, on one day."""

    domain: CategoricalDomain
    code: str
    observed_on: date
    observed_at: datetime | None
    provenance: Provenance
    sport: Sport | None = None

    def __post_init__(self) -> None:
        require_instance(self.domain, CategoricalDomain, "domain")
        if not isinstance(self.code, str):
            raise TypeError("code must be text")
        if _CODE.fullmatch(self.code) is None:
            raise ValueError("code must be a provider status code")
        require_date(self.observed_on, "observed_on")
        optional_aware_datetime(self.observed_at, "observed_at")
        _require_provider_source(self.provenance)
        if self.sport is not None:
            require_instance(self.sport, Sport, "sport")


@dataclass(frozen=True, slots=True)
class SleepPeriod:
    """One sleep period with its bounds, as one provider reported it.

    The bounds are kept in UTC, so order and length are those of the instants.
    ``wake_date`` is the local date of ``end`` in ``timezone``, the zone the
    period was read in. Without a zone it is only checked to be within a day of
    the UTC date. ``reported_duration_s`` is the provider's sleep time, which
    can be shorter than the bounds; ``bounds_method`` names the provider fields
    the bounds came from.
    """

    start: datetime
    end: datetime
    wake_date: date
    kind: SleepKind
    timezone: str | None
    reported_duration_s: float | None
    bounds_method: str | None
    provenance: Provenance

    def __post_init__(self) -> None:
        start = utc_instant(self.start, "start")
        end = utc_instant(self.end, "end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if end <= start:
            raise ValueError("sleep end must be after its start")
        if end - start > MAX_SLEEP_PERIOD:
            raise ValueError("sleep period must not exceed 24 hours")
        require_date(self.wake_date, "wake_date")
        zone = _time_zone(self.timezone)
        if zone is None:
            # Every UTC offset is under a day, so the local date is at most one
            # day from the UTC date.
            if abs((self.wake_date - end.date()).days) > 1:
                raise ValueError("wake_date must be within a day of the sleep end")
        else:
            try:
                local_wake_date = local_date(end, zone)
            except OverflowError as error:
                raise ValueError("end must have a local date in timezone") from error
            if self.wake_date != local_wake_date:
                raise ValueError("wake_date must be the local date of the sleep end")
        require_instance(self.kind, SleepKind, "kind")
        object.__setattr__(
            self,
            "reported_duration_s",
            optional_bounded_number(
                self.reported_duration_s,
                "reported_duration_s",
                0.0,
                MAX_REPORTED_SLEEP_S,
            ),
        )
        optional_slug(self.bounds_method, "bounds_method")
        _require_provider_source(self.provenance)


def _zone_limits(
    values: object, field: str, lower: float, upper: float
) -> tuple[float, ...] | None:
    if values is None:
        return None
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    if not 1 <= len(values) <= MAX_ZONES:
        raise ValueError(f"{field} must have 1 to {MAX_ZONES} entries")
    limits = tuple(bounded_number(value, field, lower, upper) for value in values)
    if any(later <= earlier for earlier, later in pairwise(limits)):
        raise ValueError(f"{field} must be strictly ascending")
    return limits


@dataclass(frozen=True, slots=True)
class ZoneConfiguration:
    """Zone limits of one metric, as a provider reported them or as set locally.

    ``limits`` are ascending upper zone limits in the metric's unit (beats per
    minute, watts, metres per second). ``percent_limits`` keep limits a provider
    reports as percentages of ``percent_basis``; absolute values are never
    invented for them. A local configuration has no provider.
    """

    metric: ZoneConfigurationMetric
    sport: Sport | None
    environment: Environment | None
    valid_from: date | None
    valid_until: date | None
    threshold: float | None
    maximum: float | None
    resting: float | None
    limits: tuple[float, ...] | None
    percent_limits: tuple[float, ...] | None
    percent_basis: ZonePercentBasis | None
    provenance: Provenance
    model: str | None = None

    def __post_init__(self) -> None:
        require_instance(self.metric, ZoneConfigurationMetric, "metric")
        if self.sport is not None:
            require_instance(self.sport, Sport, "sport")
        if self.environment is not None:
            require_instance(self.environment, Environment, "environment")
        _require_validity(self.valid_from, self.valid_until)
        lower, upper = ZONE_VALUE_BOUNDS[self.metric]
        for field in ("threshold", "maximum", "resting"):
            object.__setattr__(
                self,
                field,
                optional_bounded_number(getattr(self, field), field, lower, upper),
            )
        if (
            self.resting is not None
            and self.metric is not ZoneConfigurationMetric.HEART_RATE
        ):
            raise ValueError("resting applies to heart-rate zones only")
        object.__setattr__(
            self, "limits", _zone_limits(self.limits, "limits", lower, upper)
        )
        object.__setattr__(
            self,
            "percent_limits",
            _zone_limits(self.percent_limits, "percent_limits", *ZONE_PERCENT_BOUNDS),
        )
        if self.limits is None and self.percent_limits is None:
            raise ValueError("zone configurations need limits or percent_limits")
        if (self.percent_limits is None) != (self.percent_basis is None):
            raise ValueError("percent_limits and percent_basis go together")
        if self.percent_basis is not None:
            _require_percent_basis(self.percent_basis, self.metric)
        provenance = require_instance(self.provenance, Provenance, "provenance")
        if provenance.source_kind is SourceKind.DERIVED:
            raise ValueError("zone configurations must not be derived")
        if provenance.provider is not None and provenance.source_record_id is None:
            raise ValueError("provider zone configurations need a source record id")
        optional_slug(self.model, "model")


def _require_validity(valid_from: date | None, valid_until: date | None) -> None:
    if valid_from is not None:
        require_date(valid_from, "valid_from")
    if valid_until is not None:
        require_date(valid_until, "valid_until")
    if valid_from is not None and valid_until is not None and valid_until < valid_from:
        raise ValueError("valid_until must not precede valid_from")


def _require_percent_basis(
    basis: ZonePercentBasis, metric: ZoneConfigurationMetric
) -> None:
    require_instance(basis, ZonePercentBasis, "percent_basis")
    if (
        basis is ZonePercentBasis.RESERVE
        and metric is not ZoneConfigurationMetric.HEART_RATE
    ):
        raise ValueError("reserve percentages apply to heart-rate zones only")


@dataclass(frozen=True, slots=True)
class GearItem:
    """One piece of provider gear with its reported labels and totals.

    ``activity_list_partial`` is None when the provider's list of the gear's
    activities is unknown, True when the known list is truncated or kept from an
    earlier read, and False when it is complete.
    """

    gear_id: str
    name: str | None
    type_label: str | None
    activity_type_label: str | None
    status_label: str | None
    maximum_distance_m: float | None
    total_distance_m: float | None
    total_activities: int | None
    provenance: Provenance
    activity_list_partial: bool | None = None

    def __post_init__(self) -> None:
        require_text(self.gear_id, "gear_id")
        optional_text(self.name, "name", max_length=200)
        optional_text(self.type_label, "type_label", max_length=100)
        optional_text(self.activity_type_label, "activity_type_label", max_length=100)
        optional_text(self.status_label, "status_label", max_length=100)
        for field in ("maximum_distance_m", "total_distance_m"):
            object.__setattr__(
                self,
                field,
                optional_bounded_number(
                    getattr(self, field), field, 0.0, MAX_GEAR_DISTANCE_M
                ),
            )
        if self.total_activities is not None:
            count = self.total_activities
            if isinstance(count, bool) or not isinstance(count, int):
                raise TypeError("total_activities must be an integer")
            if not 0 <= count <= MAX_GEAR_ACTIVITIES:
                raise ValueError("total_activities must be between 0 and 1000000")
        if self.activity_list_partial is not None:
            require_instance(self.activity_list_partial, bool, "activity_list_partial")
        _require_provider_source(self.provenance)


@dataclass(frozen=True, slots=True)
class GearActivityLink:
    """A provider's statement that one of its activities used one piece of gear."""

    gear_id: str
    provider_activity_id: str
    provenance: Provenance

    def __post_init__(self) -> None:
        require_text(self.gear_id, "gear_id")
        require_text(self.provider_activity_id, "provider_activity_id")
        if not _require_provider_source(self.provenance).context.is_unknown:
            raise ValueError("gear activity links have no measurement context")
