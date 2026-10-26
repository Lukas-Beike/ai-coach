"""Builders for canonical sleep, zone, provider status and gear records.

This is a helper module, not a test module. Every value is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.canonical.domain_records import (
    CategoricalObservation,
    GearActivityLink,
    GearItem,
    SleepPeriod,
    ZoneConfiguration,
)
from backend.canonical.records import UNKNOWN_CONTEXT, MeasurementContext, Provenance
from backend.canonical.vocabulary import (
    CategoricalDomain,
    ProviderId,
    RecordingOrigin,
    SleepKind,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
)

RETRIEVED_AT = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
NOW = "2026-10-20T06:00:00+00:00"
LATER = "2026-10-21T06:00:00+00:00"
WELLNESS_SOURCE = "wellness-2026-10-20"
SETTINGS_SOURCE = "sport-settings"
GEAR_SOURCE = "gear-list"
SLEEP_START = datetime(2026, 10, 19, 22, 30, tzinfo=UTC)
WATCH_CONTEXT = MeasurementContext(
    device_model="Forerunner 965", firmware="21.19", sensor="optical_wrist"
)


def provenance(
    source_record_id: str | None = WELLNESS_SOURCE,
    *,
    provider: ProviderId | None = ProviderId.GARMIN,
    context: MeasurementContext = UNKNOWN_CONTEXT,
    source_kind: SourceKind | None = None,
) -> Provenance:
    if source_kind is None:
        source_kind = (
            SourceKind.PROVIDER_REPORTED
            if provider is not None
            else SourceKind.ATHLETE_ENTERED
        )
    return Provenance(
        provider=provider,
        source_kind=source_kind,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=RETRIEVED_AT,
        label=None,
        context=context,
    )


def sleep_period(**overrides: Any) -> SleepPeriod:
    values: dict[str, Any] = {
        "start": SLEEP_START,
        "end": SLEEP_START + timedelta(hours=8),
        "wake_date": date(2026, 10, 20),
        "kind": SleepKind.NIGHT,
        "timezone": "Europe/Berlin",
        "reported_duration_s": 27_000.0,
        "bounds_method": "sleep_start_end",
        "provenance": provenance(),
    }
    values.update(overrides)
    return SleepPeriod(**values)


def status(**overrides: Any) -> CategoricalObservation:
    values: dict[str, Any] = {
        "domain": CategoricalDomain.TRAINING_STATUS,
        "code": "PRODUCTIVE",
        "observed_on": date(2026, 10, 20),
        "observed_at": None,
        "provenance": provenance(),
    }
    values.update(overrides)
    return CategoricalObservation(**values)


def zone_configuration(**overrides: Any) -> ZoneConfiguration:
    values: dict[str, Any] = {
        "metric": ZoneConfigurationMetric.HEART_RATE,
        "sport": Sport.RUN,
        "environment": None,
        "valid_from": None,
        "valid_until": None,
        "threshold": 172.0,
        "maximum": 192.0,
        "resting": 48.0,
        "limits": (130.0, 145.0, 160.0, 172.0, 192.0),
        "percent_limits": None,
        "percent_basis": None,
        "provenance": provenance(SETTINGS_SOURCE, provider=ProviderId.INTERVALS),
    }
    values.update(overrides)
    return ZoneConfiguration(**values)


def local_zone_configuration(**overrides: Any) -> ZoneConfiguration:
    return zone_configuration(provenance=provenance(None, provider=None), **overrides)


def gear_item(**overrides: Any) -> GearItem:
    values: dict[str, Any] = {
        "gear_id": "b1",
        "name": "Road bike",
        "type_label": "Bike",
        "activity_type_label": "Ride",
        "status_label": "active",
        "maximum_distance_m": 30_000_000.0,
        "total_distance_m": 12_345_000.0,
        "total_activities": 321,
        "provenance": provenance(GEAR_SOURCE, provider=ProviderId.INTERVALS),
    }
    values.update(overrides)
    return GearItem(**values)


def gear_link(
    provider_activity_id: str = "i1001", **overrides: Any
) -> GearActivityLink:
    values: dict[str, Any] = {
        "gear_id": "b1",
        "provider_activity_id": provider_activity_id,
        "provenance": provenance(GEAR_SOURCE, provider=ProviderId.INTERVALS),
    }
    values.update(overrides)
    return GearActivityLink(**values)
