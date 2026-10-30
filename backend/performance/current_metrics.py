"""Current performance metric composition from canonical inputs.

Intervals.icu athlete settings come from the canonical observations of the latest
sync, Garmin values from the Garmin metrics, and activity values from the
canonical activity rows. No snapshot section is read.
"""

import math
from typing import Any

from backend.activities.identity import activity_kind
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.canonical_current import CanonicalCurrentInputs
from backend.performance.wellness_days import WellnessDay
from backend.providers import intervals_performance_fields as intervals_perf_fields
from backend.providers.source_labels import (
    SourceView,
    observation_source_label,
    provider_label,
)

PROVIDER_INTERVALS_NAME = provider_label(
    ProviderId.INTERVALS, SourceView.CURRENT_METRIC
)
# provider_label has no view for this wellness label, so it stays a literal.
PROVIDER_INTERVALS_WELLNESS_NAME = "Intervals.icu Wellness"
GARMIN_PERFORMANCE_SOURCE = provider_label(ProviderId.GARMIN, SourceView.CURRENT_METRIC)
VO2MAX_UNIT = "ml/kg/min"


def athlete_thresholds(canonical: CanonicalCurrentInputs) -> dict[str, Any]:
    """Return the athlete record's W′, max heart rate and LTHR for threshold context."""
    return {
        "w_prime_j": _observation_number(canonical.athlete_value(MetricKind.W_PRIME)),
        "max_hr": _observation_number(canonical.athlete_value(MetricKind.MAX_HR)),
        "lthr": _observation_number(canonical.athlete_threshold_hr),
    }


def _observation_number(observation: Observation | None) -> float | int | None:
    return None if observation is None else as_number(observation.value.value)


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def as_number(value: Any) -> float | int | None:
    """Return a finite number parsed from a provider value, or None."""
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def metric(
    value: Any,
    unit: str,
    source: str | None,
    note: str = "",
    provider: ProviderId | None = None,
) -> dict[str, Any]:
    """Return a metric entry whose source fields are set only for a value."""
    number = as_number(value)
    return {
        "value": number,
        "unit": unit,
        "source": source if number is not None else None,
        "source_provider": (
            provider.value if provider is not None and number is not None else None
        ),
        "note": note if number is not None else "",
    }


def _canonical_metric(observation: Observation, unit: str) -> dict[str, Any]:
    """Return a metric for a canonical observation, labelled as the legacy view."""
    return metric(
        observation.value.value,
        unit,
        observation_source_label(observation, SourceView.CURRENT_METRIC),
        provider=observation.provenance.provider,
    )


def _observation_metric(observation: Observation | None, unit: str) -> dict[str, Any]:
    """Return the canonical metric of an observation, or an empty metric."""
    if observation is None:
        return metric(None, unit, None)
    return _canonical_metric(observation, unit)


def _first(candidates: tuple[Observation, ...]) -> Observation | None:
    """Return the first sport candidate; the mapper keeps one setting per sport."""
    return next(iter(candidates), None)


def _threshold_hr_metric(
    canonical_sport: tuple[Observation, ...], canonical_athlete: Observation | None
) -> dict[str, Any]:
    """Sport threshold HR, then the athlete-wide value."""
    return _observation_metric(_first(canonical_sport) or canonical_athlete, "bpm")


def _canonical_eftp_value(canonical: CanonicalCurrentInputs) -> float | None:
    """Return the athlete-record ride eFTP, else the latest wellness day's."""
    for observation in (canonical.athlete_eftp, canonical.wellness_eftp):
        if observation is not None:
            return observation.value.value
    return None


def _intervals_max_hr_metric(
    category: str,
    sport: Sport,
    activities: list[Any],
    canonical: CanonicalCurrentInputs,
) -> dict[str, Any]:
    """Return sport max HR: setting, then activities, then the athlete record."""
    max_hr_keys = ("max_hr", "maxHR", "maxHeartRate", "max_heartrate")
    activity_values: list[float | int] = []
    for activity in activities:
        if activity_kind(activity) != category:
            continue
        value = as_number(_first_present(activity, max_hr_keys))
        if value is not None and 80 <= float(value) <= 260:
            activity_values.append(value)
    candidates = (
        _observation_number(canonical.athlete_value(MetricKind.MAX_HR, sport)),
        max(activity_values, default=None),
        _observation_number(canonical.athlete_value(MetricKind.MAX_HR)),
    )
    for number in candidates:
        if number is not None and 80 <= float(number) <= 260:
            return metric(
                number, "bpm", PROVIDER_INTERVALS_NAME, provider=ProviderId.INTERVALS
            )
    return metric(None, "bpm", None)


def _pace_seconds(observation: Observation | None) -> float | int | None:
    """Return a canonical pace in metres per second as seconds per kilometre."""
    speed = None if observation is None else observation.value.value
    return None if not speed or speed <= 0 else round(1000 / speed)


def _zone2_pace_seconds(observation: Observation | None) -> float | int | None:
    pace = _pace_seconds(observation)
    return pace if pace is not None and 120 <= float(pace) <= 1800 else None


def _height_in_cm(value: Any) -> float | int | None:
    number = as_number(value)
    if number is not None and 1.2 <= float(number) <= 2.5:
        return round(float(number) * 100, 1)
    return number


def _latest_ride_activity(activities: list[Any]) -> dict[str, Any]:
    ride_terms = ("ride", "rad", "bike", "cycling")
    valid_activities = (
        activity for activity in activities if isinstance(activity, dict)
    )
    ordered = sorted(
        valid_activities,
        key=lambda item: str(item.get("start_date_local") or ""),
        reverse=True,
    )
    return next(
        (
            activity
            for activity in ordered
            if any(
                term
                in str(
                    _first_present(
                        activity,
                        ("type", "sport", "sport_type", "activity_type", "name"),
                    )
                    or ""
                ).casefold()
                for term in ride_terms
            )
        ),
        {},
    )


def _first_performance_source(
    sources: tuple[tuple[Any, str | None, ProviderId | None], ...],
) -> tuple[Any, str | None, ProviderId | None]:
    return next(
        (
            (value, source, provider)
            for value, source, provider in sources
            if as_number(value) is not None
        ),
        (None, None, None),
    )


def _observation_source(
    observation: Observation | None,
) -> tuple[Any, str | None, ProviderId | None]:
    """Return a canonical observation's value, label and provider, else empties."""
    if observation is None:
        return None, None, None
    return (
        observation.value.value,
        observation_source_label(observation, SourceView.CURRENT_METRIC),
        observation.provenance.provider,
    )


def _wellness_source(
    observation: Observation | None,
    latest_wellness: WellnessDay | None,
    kind: MetricKind,
) -> tuple[Any, str | None, ProviderId | None]:
    """Return this sync's wellness-row value, else the latest wellness day's."""
    if observation is not None:
        return _observation_source(observation)
    return (
        None if latest_wellness is None else latest_wellness.value(kind),
        PROVIDER_INTERVALS_WELLNESS_NAME,
        ProviderId.INTERVALS,
    )


def _performance_body_metrics(
    latest_wellness: WellnessDay | None,
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    canonical: CanonicalCurrentInputs,
) -> dict[str, dict[str, Any]]:
    weight_value, weight_source, weight_provider = _first_performance_source(
        (
            (
                garmin_metrics["weight_kg"]["value"],
                GARMIN_PERFORMANCE_SOURCE,
                ProviderId.GARMIN,
            ),
            _wellness_source(
                canonical.wellness_weight, latest_wellness, MetricKind.WEIGHT
            ),
            _observation_source(canonical.athlete_weight),
            (profile.get("weight_kg"), "Manuell", None),
            _observation_source(canonical.wahoo_weight),
        )
    )
    body_fat_value, body_fat_source, body_fat_provider = _first_performance_source(
        (
            _wellness_source(None, latest_wellness, MetricKind.BODY_FAT),
            _observation_source(canonical.athlete_value(MetricKind.BODY_FAT)),
            (profile.get("body_fat_pct"), "Manuell", None),
        )
    )
    height_value, height_source, height_provider = _first_performance_source(
        (
            _observation_source(canonical.athlete_value(MetricKind.HEIGHT)),
            # The canonical height is in cm; only the profile may hold metres.
            (_height_in_cm(profile.get("height_cm")), "Manuell", None),
        )
    )
    weight_metric = (
        garmin_metrics["weight_kg"]
        if weight_source == GARMIN_PERFORMANCE_SOURCE
        else metric(weight_value, "kg", weight_source, provider=weight_provider)
    )
    return {
        "weight_kg": weight_metric,
        "body_fat_pct": metric(
            body_fat_value, "%", body_fat_source, provider=body_fat_provider
        ),
        "height_cm": metric(
            height_value,
            "cm",
            height_source,
            provider=height_provider,
        ),
    }


def _preferred_performance_metric(
    garmin_metrics: dict[str, dict[str, Any]], key: str, fallback: dict[str, Any]
) -> dict[str, Any]:
    current = garmin_metrics[key]
    return current if current["value"] is not None else fallback


def _intervals_metric(value: Any, unit: str) -> dict[str, Any]:
    return metric(value, unit, PROVIDER_INTERVALS_NAME, provider=ProviderId.INTERVALS)


def _performance_threshold_metrics(
    garmin_metrics: dict[str, dict[str, Any]], canonical: CanonicalCurrentInputs
) -> dict[str, dict[str, Any]]:
    run_pace = canonical.athlete_value(MetricKind.THRESHOLD_PACE, Sport.RUN)
    run_zone2_pace = canonical.athlete_value(MetricKind.ZONE2_PACE, Sport.RUN)
    return {
        "cycling_ftp_watts": _preferred_performance_metric(
            garmin_metrics,
            "cycling_ftp_watts",
            _observation_metric(
                canonical.athlete_value(MetricKind.FTP, Sport.RIDE)
                or canonical.wahoo_ftp,
                "W",
            ),
        ),
        "run_threshold_watts": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_watts",
            _observation_metric(
                canonical.athlete_value(MetricKind.FTP, Sport.RUN), "W"
            ),
        ),
        "run_threshold_pace_seconds_per_km": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_pace_seconds_per_km",
            _intervals_metric(_pace_seconds(run_pace), "s/km"),
        ),
        "run_zone2_pace_seconds_per_km": _intervals_metric(
            _zone2_pace_seconds(run_zone2_pace), "s/km"
        ),
        "bike_threshold_hr_bpm": _preferred_performance_metric(
            garmin_metrics,
            "bike_threshold_hr_bpm",
            _threshold_hr_metric(
                canonical.bike_threshold_hr, canonical.athlete_threshold_hr
            ),
        ),
        "run_threshold_hr_bpm": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_hr_bpm",
            _threshold_hr_metric(
                canonical.run_threshold_hr, canonical.athlete_threshold_hr
            ),
        ),
    }


def _sport_vo2max(
    canonical: CanonicalCurrentInputs, sport: Sport
) -> Observation | None:
    """The sport's VO2max (setting, then athlete sport field), else the athlete-wide one."""
    candidates = (
        canonical.cycling_vo2max if sport is Sport.RIDE else canonical.running_vo2max
    )
    return _first(candidates) or canonical.athlete_value(MetricKind.VO2MAX)


def _performance_vo2_and_prediction_metrics(
    garmin_metrics: dict[str, dict[str, Any]], canonical: CanonicalCurrentInputs
) -> dict[str, dict[str, Any]]:
    return {
        "cycling_vo2max_ml_kg_min": _preferred_performance_metric(
            garmin_metrics,
            "cycling_vo2max_ml_kg_min",
            _observation_metric(_sport_vo2max(canonical, Sport.RIDE), VO2MAX_UNIT),
        ),
        "running_vo2max_ml_kg_min": _preferred_performance_metric(
            garmin_metrics,
            "running_vo2max_ml_kg_min",
            _observation_metric(_sport_vo2max(canonical, Sport.RUN), VO2MAX_UNIT),
        ),
        **{
            key: _preferred_performance_metric(
                garmin_metrics, key, metric(None, "s", None)
            )
            for key in (
                "run_5k_seconds",
                "run_10k_seconds",
                "run_half_marathon_seconds",
                "run_marathon_seconds",
            )
        },
    }


def current_performance_metrics(
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    *,
    canonical: CanonicalCurrentInputs,
    activities: list[Any],
    latest_wellness: WellnessDay | None = None,
) -> dict[str, dict[str, Any]]:
    """Compose current metrics from canonical inputs, Garmin metrics and the profile."""
    latest_ride_activity = _latest_ride_activity(activities)
    latest_ride_eftp = _first_present(
        latest_ride_activity, intervals_perf_fields.ESTIMATED_FTP_ALIASES
    )
    current_ride_eftp = _canonical_eftp_value(canonical)
    cycling_max_hr = _intervals_max_hr_metric(
        "cycling", Sport.RIDE, activities, canonical
    )
    running_max_hr = _intervals_max_hr_metric(
        "running", Sport.RUN, activities, canonical
    )
    if garmin_metrics["cycling_max_hr_bpm"]["value"] is not None:
        cycling_max_hr = garmin_metrics["cycling_max_hr_bpm"]
    if garmin_metrics["running_max_hr_bpm"]["value"] is not None:
        running_max_hr = garmin_metrics["running_max_hr_bpm"]
    garmin_max_hr = [
        garmin_metrics[key]
        for key in ("cycling_max_hr_bpm", "running_max_hr_bpm")
        if garmin_metrics[key]["value"] is not None
    ]
    max_hr = max(
        garmin_max_hr
        or [
            item
            for item in (cycling_max_hr, running_max_hr)
            if item["value"] is not None
        ],
        key=lambda item: item["value"],
        default=metric(None, "bpm", None),
    )
    return {
        **_performance_body_metrics(
            latest_wellness, profile, garmin_metrics, canonical
        ),
        **_performance_threshold_metrics(garmin_metrics, canonical),
        "cycling_eftp_watts": _intervals_metric(
            current_ride_eftp or latest_ride_eftp, "W"
        ),
        "cycling_max_hr_bpm": cycling_max_hr,
        "running_max_hr_bpm": running_max_hr,
        "max_hr_bpm": max_hr,
        **_performance_vo2_and_prediction_metrics(garmin_metrics, canonical),
    }
