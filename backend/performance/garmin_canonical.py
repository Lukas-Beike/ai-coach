"""Garmin health values read through the canonical observation port.

The Garmin snapshot sections that have canonical observations (sleep, HRV, resting
HR, readiness, weight, FTP, VO2max, thresholds including the running threshold
power, profile max HR and race predictions) are read here from the observations of
the Garmin provider, so the readers no longer depend on those snapshot sections.
Which source serves the observations (the canonical tables, or nothing before
the first completed backfill) is decided by the injected reader.

Selection follows the legacy readers: the latest observed day wins, and on one day
a timestamped record beats an untimed one and a later record beats an earlier one.
Garmin's training load and load balance are read here too, as the latest value
of each kind with its day. The max heart rate fallback is derived from the
canonical Garmin activity records. Freshness is sync status and stays on the
snapshot path of its owners.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.sports import legacy_activity_family
from backend.canonical.vocabulary import (
    CategoricalDomain,
    MetricKind,
    ProviderId,
    Sport,
)
from backend.runtime.ports import (
    ActivityMaxHrReader,
    CategoricalObservationReader,
    ObservationReader,
    ObservationSourceSelector,
)

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
# Garmin's daily training status and four-week load balance.
DAILY_STATUS_KINDS: tuple[MetricKind, ...] = (
    MetricKind.ACUTE_LOAD,
    MetricKind.CHRONIC_LOAD,
    MetricKind.ACUTE_CHRONIC_RATIO,
)
LOAD_BALANCE_KINDS: tuple[MetricKind, ...] = (
    MetricKind.LOAD_BALANCE_AEROBIC_LOW,
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MIN,
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MAX,
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH,
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MIN,
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MAX,
    MetricKind.LOAD_BALANCE_ANAEROBIC,
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MIN,
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MAX,
)
TRAINING_LOAD_KINDS: tuple[MetricKind, ...] = (*DAILY_STATUS_KINDS, *LOAD_BALANCE_KINDS)
# Kinds the Garmin history charts show day by day; running tolerance is running.
HISTORY_KINDS: Mapping[MetricKind, Sport | None] = {
    MetricKind.ACUTE_LOAD: None,
    MetricKind.READINESS: None,
    MetricKind.RUNNING_TOLERANCE: Sport.RUN,
    MetricKind.ENDURANCE_SCORE: None,
    MetricKind.ENDURANCE_SCORE_GROUP_AVERAGE: None,
    MetricKind.ENDURANCE_SCORE_GROUP_MAX: None,
}
_MAX_HR_CATEGORIES: Mapping[Sport | None, str] = {
    Sport.RIDE: "cycling",
    Sport.RUN: "running",
    None: "generic",
}
ACTIVITY_MAX_HR_CATEGORIES = ("cycling", "running")


@dataclass(frozen=True, slots=True)
class ActivityMaxHr:
    """The highest max heart rate of a category's Garmin activities.

    ``observed_on`` is the start day of the newest activity with that value.
    """

    value: float
    observed_on: date


@dataclass(frozen=True, slots=True)
class GarminCanonicalMetrics:
    """Garmin performance values that have canonical observations.

    ``profile_max_hr`` maps the legacy categories ``cycling``, ``running`` and
    ``generic`` to the profile max heart rate of the latest day of that category;
    the highest value resolves records of that one day. ``race_predictions`` maps
    the legacy keys ``run_5k_seconds`` and so on to the latest predicted time.
    ``activity_max_hr`` maps ``cycling`` and ``running`` to the derived activity
    max heart rate; it is read only for a category without a profile value.
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
    # Latest (day, value) of each training-load and load-balance kind.
    training_load: Mapping[MetricKind, tuple[date, float]] = field(default_factory=dict)
    activity_max_hr: Mapping[str, ActivityMaxHr] = field(default_factory=dict)
    # Legacy performance-history key -> day -> the value the current metric would
    # show on that day (same kind, sport, bounds and unit).
    performance_history: Mapping[str, Mapping[date, float]] = field(
        default_factory=dict
    )
    # Day -> value of the history charts' kinds, the latest record of each day.
    daily_history: Mapping[MetricKind, Mapping[date, float]] = field(
        default_factory=dict
    )


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
    """Read the Garmin observations once, from one source, inside ``db``'s unit of work.

    When the source also stores activities and a category has no profile max heart
    rate, the max heart rate fallback is read from the same source.
    """
    reader = _resolved(reader, db)
    by_kind = {kind: _garmin_only(reader, db, kind) for kind in _READ_KINDS}
    sleep = [item for kind in _SLEEP_KINDS for item in by_kind[kind]]
    metrics = _metrics(by_kind)
    if isinstance(reader, ActivityMaxHrReader) and any(
        profile_max_hr_for(metrics.profile_max_hr, category) is None
        for category in ACTIVITY_MAX_HR_CATEGORIES
    ):
        low, high = _MAX_HR_RANGE
        metrics = replace(
            metrics,
            activity_max_hr=activity_max_hr(
                reader.activity_max_hr(db, ProviderId.GARMIN, low=low, high=high)
            ),
        )
    return GarminCanonicalState(
        metrics=metrics,
        has_sleep=bool(sleep),
        has_hrv=bool(
            by_kind[MetricKind.HRV_RMSSD] or by_kind[MetricKind.HRV_WEEKLY_AVERAGE]
        ),
        has_resting_hr=bool(by_kind[MetricKind.RESTING_HR]),
        has_readiness=bool(by_kind[MetricKind.READINESS]),
        sleep_observed_on=max((item.observed_on for item in sleep), default=None),
    )


# Coach recovery section -> ((field, kind), ...) and its status domain, if any.
_RECOVERY_RECORDS: Mapping[
    str, tuple[tuple[tuple[str, MetricKind], ...], tuple[str, CategoricalDomain] | None]
] = {
    "sleep": (
        (
            ("sleep_seconds", MetricKind.SLEEP_DURATION),
            ("sleep_score", MetricKind.SLEEP_SCORE),
        ),
        None,
    ),
    "hrv": (
        (
            ("last_night_avg_ms", MetricKind.HRV_RMSSD),
            ("weekly_avg_ms", MetricKind.HRV_WEEKLY_AVERAGE),
        ),
        ("status", CategoricalDomain.HRV_STATUS),
    ),
    "resting_hr": ((("resting_hr_bpm", MetricKind.RESTING_HR),), None),
    "readiness": (
        (("score", MetricKind.READINESS),),
        ("level", CategoricalDomain.READINESS_LEVEL),
    ),
}


def read_garmin_recovery(
    reader: ObservationReader, db: Any, *, start: date
) -> dict[str, dict[str, Any]]:
    """Return the latest Garmin recovery record of each section since ``start``.

    A section's record is the latest day with any of its kinds or its status; it
    holds that day's values, each the day's latest observation. A section without
    any is an empty mapping. Status codes are read only from a source that stores
    them.
    """
    reader = _resolved(reader, db)
    records: dict[str, dict[str, Any]] = {}
    for section, (fields, status) in _RECOVERY_RECORDS.items():
        values = _recovery_kind_values(reader, db, fields, start=start)
        if status is not None and isinstance(reader, CategoricalObservationReader):
            _add_recovery_status(reader, db, status, values, start=start)
        if not values:
            records[section] = {}
            continue
        day = max(values)
        records[section] = {"date": day.isoformat(), **values[day]}
    return records


def _recovery_kind_values(
    reader: ObservationReader,
    db: Any,
    fields: tuple[tuple[str, MetricKind], ...],
    *,
    start: date,
) -> dict[date, dict[str, Any]]:
    """Each day's latest Garmin value of every field, keyed by day."""
    values: dict[date, dict[str, Any]] = {}
    for name, kind in fields:
        for day, value in _daily_values(
            item
            for item in reader.observations(db, kind, start=start)
            if item.provenance.provider is ProviderId.GARMIN
        ).items():
            values.setdefault(day, {})[name] = _number(value)
    return values


def _add_recovery_status(
    reader: CategoricalObservationReader,
    db: Any,
    status: tuple[str, CategoricalDomain],
    values: dict[date, dict[str, Any]],
    *,
    start: date,
) -> None:
    """Add each day's Garmin status code of ``status`` to ``values``."""
    name, domain = status
    for item in reader.categorical_observations(db, domain, start=start):
        if item.provenance.provider is ProviderId.GARMIN:
            values.setdefault(item.observed_on, {})[name] = item.code


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


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
    MetricKind.HRV_WEEKLY_AVERAGE,
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
    *TRAINING_LOAD_KINDS,
    *(kind for kind in HISTORY_KINDS if kind not in TRAINING_LOAD_KINDS),
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
        training_load={
            kind: (latest.observed_on, latest.value.value)
            for kind in TRAINING_LOAD_KINDS
            if (latest := max(by_kind[kind], key=_order, default=None)) is not None
        },
        performance_history=_performance_history(by_kind),
        daily_history={
            kind: values
            for kind, sport in HISTORY_KINDS.items()
            if (
                values := _daily_values(
                    item for item in by_kind[kind] if item.sport is sport
                )
            )
        },
    )


def _per_day(
    observations: Iterable[Observation],
    pick: Callable[[list[Observation]], float | None],
) -> dict[date, float]:
    """Apply a latest-value rule to each day's observations alone."""
    days: dict[date, list[Observation]] = {}
    for item in observations:
        days.setdefault(item.observed_on, []).append(item)
    return {
        day: value
        for day, items in sorted(days.items())
        if (value := pick(items)) is not None
    }


def _performance_history(
    by_kind: Mapping[MetricKind, tuple[Observation, ...]],
) -> dict[str, dict[date, float]]:
    """Return each legacy performance-history key's value per day.

    Each day uses the rule that ``_metrics`` applies to the latest values, so a day
    shows what the current Garmin metric would have shown on it.
    """
    vo2 = by_kind[MetricKind.VO2MAX]
    threshold_hr = by_kind[MetricKind.THRESHOLD_HR]
    rules: dict[
        str, tuple[Iterable[Observation], Callable[[list[Observation]], Any]]
    ] = {
        "weight_kg": (
            by_kind[MetricKind.WEIGHT],
            lambda items: _bounded(_latest_value(items), _WEIGHT_KG_RANGE),
        ),
        "cycling_ftp_watts": (
            by_kind[MetricKind.FTP],
            lambda items: _latest_value(items, Sport.RIDE),
        ),
        "cycling_vo2max_ml_kg_min": (
            vo2,
            lambda items: _bounded(_latest_value(items, Sport.RIDE), _VO2MAX_RANGE),
        ),
        "running_vo2max_ml_kg_min": (
            vo2,
            lambda items: _bounded(_running_vo2max(items), _VO2MAX_RANGE),
        ),
        "run_threshold_watts": (
            by_kind[MetricKind.RUN_THRESHOLD_POWER],
            lambda items: _bounded(
                _latest_value(items, Sport.RUN), _RUN_THRESHOLD_POWER_RANGE
            ),
        ),
        "run_threshold_pace_seconds_per_km": (
            by_kind[MetricKind.THRESHOLD_PACE],
            lambda items: _pace_seconds_per_km(_latest_value(items, Sport.RUN)),
        ),
        "run_threshold_hr_bpm": (
            threshold_hr,
            lambda items: _latest_value(items, Sport.RUN),
        ),
        "bike_threshold_hr_bpm": (
            threshold_hr,
            lambda items: _latest_value(items, Sport.RIDE),
        ),
        "cycling_max_hr_bpm": (
            by_kind[MetricKind.MAX_HR],
            lambda items: _profile_category_max_hr(items, "cycling"),
        ),
        "running_max_hr_bpm": (
            by_kind[MetricKind.MAX_HR],
            lambda items: _profile_category_max_hr(items, "running"),
        ),
        "readiness": (
            by_kind[MetricKind.READINESS],
            lambda items: _bounded(_latest_value(items), (0, 100)),
        ),
        **{
            key: (by_kind[kind], lambda items: _latest_value(items, Sport.RUN))
            for kind, key in RACE_PREDICTION_KEYS.items()
        },
    }
    return {
        key: values
        for key, (observations, pick) in rules.items()
        if (values := _per_day(observations, pick))
    }


def profile_max_hr_for(profile: Mapping[str, float], category: str) -> float | None:
    """A category's profile max heart rate, else the generic one."""
    return profile.get(category) or profile.get("generic")


def activity_max_hr(
    by_sport: Iterable[tuple[Sport, float, date]],
) -> dict[str, ActivityMaxHr]:
    """Group the per-sport activity max heart rates into the legacy categories.

    The highest value wins; on equal values the newest start day is kept.
    """
    derived: dict[str, ActivityMaxHr] = {}
    for sport, value, day in by_sport:
        category = legacy_activity_family(sport)
        if category not in ACTIVITY_MAX_HR_CATEGORIES:
            continue
        kept = derived.get(category)
        if kept is None or (value, day) > (kept.value, kept.observed_on):
            derived[category] = ActivityMaxHr(value, day)
    return derived


def _profile_category_max_hr(
    observations: Iterable[Observation], category: str
) -> float | None:
    """A category's profile max heart rate, else the generic one, as the metric reads it.

    The day history keeps only the profile value; the activity fallback is current only.
    """
    return profile_max_hr_for(_profile_max_hr(observations), category)


def _daily_values(observations: Iterable[Observation]) -> dict[date, float]:
    """Return the value of each day's latest observation."""
    days: dict[date, Observation] = {}
    for item in observations:
        kept = days.get(item.observed_on)
        if kept is None or _order(item) >= _order(kept):
            days[item.observed_on] = item
    return {day: item.value.value for day, item in sorted(days.items())}


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
