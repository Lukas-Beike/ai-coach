"""Garmin health values read through the canonical observation port.

The Garmin snapshot sections that have canonical observations (sleep, HRV, resting
HR, readiness, weight, FTP, VO2max, thresholds including the running threshold
power, profile max HR and race predictions) are read here from the observations of
the Garmin provider, so the readers no longer depend on those snapshot sections.
Which source serves the observations (the legacy projection or the canonical
tables) is decided by the injected reader.

Selection follows the legacy readers: the latest observed day wins, and on one day
a timestamped record beats an untimed one and a later record beats an earlier one.
Values with no canonical form (the heart rate fallbacks from Garmin activities,
Body Battery, training status and freshness) stay on the snapshot path of their
owners.
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
_VO2MAX_RANGE = (20, 100)
_RUN_THRESHOLD_POWER_RANGE = (50, 800)
# Race prediction kinds by the legacy metric key that shows them.
RACE_PREDICTION_KEYS: Mapping[MetricKind, str] = {
    MetricKind.RACE_PREDICTION_5K: "run_5k_seconds",
    MetricKind.RACE_PREDICTION_10K: "run_10k_seconds",
    MetricKind.RACE_PREDICTION_HALF: "run_half_marathon_seconds",
    MetricKind.RACE_PREDICTION_FULL: "run_marathon_seconds",
}
_MAX_HR_CATEGORIES: Mapping[Sport | None, str] = {
    Sport.RIDE: "cycling",
    Sport.RUN: "running",
    None: "generic",
}


@dataclass(frozen=True, slots=True)
class GarminCanonicalMetrics:
    """Garmin performance values that have canonical observations.

    ``profile_max_hr`` maps the legacy categories ``cycling``, ``running`` and
    ``generic`` to the profile max heart rate of the latest day of that category;
    the highest value resolves records of that one day. ``race_predictions`` maps
    the legacy keys ``run_5k_seconds`` and so on to the latest predicted time.
    """

    weight_kg: float | None = None
    cycling_ftp_watts: float | None = None
    cycling_vo2max: float | None = None
    running_vo2max: float | None = None
    run_threshold_watts: float | None = None
    run_threshold_pace_seconds_per_km: int | None = None
    run_threshold_hr_bpm: float | None = None
    bike_threshold_hr_bpm: float | None = None
    profile_max_hr: Mapping[str, float] = field(default_factory=dict)
    race_predictions: Mapping[str, float] = field(default_factory=dict)


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
    MetricKind.RUN_THRESHOLD_POWER,
    *RACE_PREDICTION_KEYS,
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
    return GarminCanonicalMetrics(
        weight_kg=_bounded(_latest_value(by_kind[MetricKind.WEIGHT]), _WEIGHT_KG_RANGE),
        cycling_ftp_watts=_latest_value(by_kind[MetricKind.FTP], Sport.RIDE),
        cycling_vo2max=_bounded(_latest_value(vo2, Sport.RIDE), _VO2MAX_RANGE),
        running_vo2max=_bounded(_running_vo2max(vo2), _VO2MAX_RANGE),
        run_threshold_watts=_bounded(
            _latest_value(by_kind[MetricKind.RUN_THRESHOLD_POWER], Sport.RUN),
            _RUN_THRESHOLD_POWER_RANGE,
        ),
        run_threshold_pace_seconds_per_km=_pace_seconds_per_km(
            _latest_value(by_kind[MetricKind.THRESHOLD_PACE], Sport.RUN)
        ),
        run_threshold_hr_bpm=_latest_value(threshold_hr, Sport.RUN),
        bike_threshold_hr_bpm=_latest_value(threshold_hr, Sport.RIDE),
        profile_max_hr=_profile_max_hr(by_kind[MetricKind.MAX_HR]),
        race_predictions={
            key: value
            for kind, key in RACE_PREDICTION_KEYS.items()
            if (value := _latest_value(by_kind[kind], Sport.RUN)) is not None
        },
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


def _running_vo2max(observations: Iterable[Observation]) -> float | None:
    """Return the newest running or generic VO2max; running wins on the same day.

    The legacy reader took the generic value of the current snapshot unless it held
    a running one, so an older running value must not hide a newer generic one.
    """
    latest = max(
        (item for item in observations if item.sport in (Sport.RUN, None)),
        key=lambda item: (item.observed_on, item.sport is Sport.RUN, *_order(item)[1:]),
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
    """Return the max heart rate of each category's latest day, so a lowered value wins."""
    latest: dict[str, tuple[date, float]] = {}
    low, high = _MAX_HR_RANGE
    for item in observations:
        category = _MAX_HR_CATEGORIES.get(item.sport)
        if category is None or not low <= item.value.value <= high:
            continue
        candidate = (item.observed_on, item.value.value)
        latest[category] = max(latest.get(category, candidate), candidate)
    return {category: value for category, (_, value) in latest.items()}
