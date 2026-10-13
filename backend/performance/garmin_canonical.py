"""Garmin health values read through the canonical observation port.

The Garmin snapshot sections that have canonical observations (sleep, HRV, resting
HR, readiness, weight, FTP, VO2max, thresholds and profile max HR) are read here
from the observations of the Garmin provider, so the readers no longer depend on
those snapshot sections. Which source serves the observations (the legacy
projection or the canonical tables) is decided by the injected reader.

Selection follows the legacy readers: the latest observed day wins, and on one day
a timestamped record beats an untimed one and a later record beats an earlier one.
Values with no canonical form (the running threshold power, the heart rate
fallbacks from activities, race predictions, Body Battery, training status and
freshness) stay on the snapshot path of their owners.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.runtime.ports import ObservationReader, ObservationSourceSelector

_SLEEP_KINDS = (MetricKind.SLEEP_DURATION, MetricKind.SLEEP_SCORE)
_PACE_SECONDS_PER_KM_RANGE = (120, 900)
# The legacy readers bounded the profile max heart rate and the weight tighter than
# the canonical validation does at ingest.
_MAX_HR_RANGE = (80, 260)
_WEIGHT_KG_RANGE = (30, 300)
_MAX_HR_CATEGORIES: Mapping[Sport | None, str] = {
    Sport.RIDE: "cycling",
    Sport.RUN: "running",
    None: "generic",
}


@dataclass(frozen=True, slots=True)
class GarminCanonicalMetrics:
    """Garmin performance values that have canonical observations.

    ``profile_max_hr`` maps the legacy categories ``cycling``, ``running`` and
    ``generic`` to the highest profile max heart rate of that category.
    """

    weight_kg: float | None = None
    cycling_ftp_watts: float | None = None
    cycling_vo2max: float | None = None
    running_vo2max: float | None = None
    run_threshold_pace_seconds_per_km: int | None = None
    run_threshold_hr_bpm: float | None = None
    bike_threshold_hr_bpm: float | None = None
    profile_max_hr: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GarminCanonicalState:
    """Garmin recovery presence, the sleep day and the canonical performance values."""

    metrics: GarminCanonicalMetrics
    has_sleep: bool = False
    has_hrv: bool = False
    has_resting_hr: bool = False
    has_readiness: bool = False
    sleep_observed_on: date | None = None


def read_garmin_state(reader: ObservationReader, db: Any) -> GarminCanonicalState:
    """Read the Garmin observations once, from one source, inside ``db``'s unit of work."""
    reader = _resolved(reader, db)
    by_kind = {kind: _garmin_only(reader, db, kind) for kind in _READ_KINDS}
    sleep = [item for kind in _SLEEP_KINDS for item in by_kind[kind]]
    return GarminCanonicalState(
        metrics=_metrics(by_kind),
        has_sleep=bool(sleep),
        has_hrv=bool(by_kind[MetricKind.HRV_RMSSD]),
        has_resting_hr=bool(by_kind[MetricKind.RESTING_HR]),
        has_readiness=bool(by_kind[MetricKind.READINESS]),
        sleep_observed_on=max((item.observed_on for item in sleep), default=None),
    )


def read_garmin_sleep_day(reader: ObservationReader, db: Any) -> date | None:
    """Return the latest day with a Garmin sleep observation, or None."""
    reader = _resolved(reader, db)
    return max(
        (
            item.observed_on
            for kind in _SLEEP_KINDS
            for item in _garmin_only(reader, db, kind)
        ),
        default=None,
    )


def _resolved(reader: ObservationReader, db: Any) -> ObservationReader:
    """Choose the serving source once when the reader selects one."""
    if isinstance(reader, ObservationSourceSelector):
        return reader.reader_for(db)
    return reader


_READ_KINDS = (
    MetricKind.SLEEP_DURATION,
    MetricKind.SLEEP_SCORE,
    MetricKind.HRV_RMSSD,
    MetricKind.RESTING_HR,
    MetricKind.READINESS,
    MetricKind.WEIGHT,
    MetricKind.FTP,
    MetricKind.VO2MAX,
    MetricKind.THRESHOLD_HR,
    MetricKind.THRESHOLD_PACE,
    MetricKind.MAX_HR,
)


def _garmin_only(
    reader: ObservationReader, db: Any, kind: MetricKind
) -> tuple[Observation, ...]:
    return tuple(
        item
        for item in reader.observations(db, kind)
        if item.provenance.provider is ProviderId.GARMIN
    )


def _metrics(
    by_kind: Mapping[MetricKind, tuple[Observation, ...]],
) -> GarminCanonicalMetrics:
    vo2 = by_kind[MetricKind.VO2MAX]
    threshold_hr = by_kind[MetricKind.THRESHOLD_HR]
    running_vo2 = _latest_value(vo2, Sport.RUN)
    return GarminCanonicalMetrics(
        weight_kg=_bounded(_latest_value(by_kind[MetricKind.WEIGHT]), _WEIGHT_KG_RANGE),
        cycling_ftp_watts=_latest_value(by_kind[MetricKind.FTP], Sport.RIDE),
        cycling_vo2max=_latest_value(vo2, Sport.RIDE),
        # The legacy reader takes the generic VO2max for running unless a running one exists.
        running_vo2max=running_vo2
        if running_vo2 is not None
        else _latest_value(vo2, None),
        run_threshold_pace_seconds_per_km=_pace_seconds_per_km(
            _latest_value(by_kind[MetricKind.THRESHOLD_PACE], Sport.RUN)
        ),
        run_threshold_hr_bpm=_latest_value(threshold_hr, Sport.RUN),
        bike_threshold_hr_bpm=_latest_value(threshold_hr, Sport.RIDE),
        profile_max_hr=_profile_max_hr(by_kind[MetricKind.MAX_HR]),
    )


def _latest_value(
    observations: Iterable[Observation], sport: Sport | None = None
) -> float | None:
    """Return the value of the latest observation of ``sport`` (None means no sport)."""
    latest = max(
        (item for item in observations if item.sport is sport),
        key=_order,
        default=None,
    )
    return None if latest is None else latest.value.value


def _bounded(value: float | None, bounds: tuple[int, int]) -> float | None:
    return value if value is not None and bounds[0] <= value <= bounds[1] else None


def _order(item: Observation) -> tuple[date, bool, float, int]:
    suffix = (item.provenance.source_record_id or "").rsplit(":", 1)[-1]
    stamp = item.observed_at.timestamp() if item.observed_at is not None else 0.0
    return (
        item.observed_on,
        item.observed_at is not None,
        stamp,
        int(suffix) if suffix.isdigit() else 0,
    )


def _pace_seconds_per_km(speed_m_s: float | None) -> int | None:
    """Convert Garmin's threshold speed to the legacy seconds per kilometre."""
    if speed_m_s is None or speed_m_s <= 0:
        return None
    pace = round(1000 / speed_m_s)
    low, high = _PACE_SECONDS_PER_KM_RANGE
    return pace if low <= pace <= high else None


def _profile_max_hr(observations: Iterable[Observation]) -> dict[str, float]:
    values: dict[str, float] = {}
    low, high = _MAX_HR_RANGE
    for item in observations:
        category = _MAX_HR_CATEGORIES.get(item.sport)
        if category is not None and low <= item.value.value <= high:
            values[category] = max(
                values.get(category, item.value.value), item.value.value
            )
    return values
