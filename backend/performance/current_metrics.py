"""Current performance metric composition from canonical inputs.

Intervals.icu athlete settings come from the canonical observations of the latest
sync, Garmin values from the Garmin metrics, and activity values from the
canonical activity rows. No snapshot section is read.
"""

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Any, Final

from backend.activities.identity import activity_kind
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.canonical_current import CanonicalCurrentInputs
from backend.performance.current_thresholds import (
    ThresholdKey,
    resolve_current_thresholds,
)
from backend.performance.source_policy import (
    NO_PREFERENCES,
    Candidate,
    Resolved,
    SourcePreferences,
    resolve_candidates,
    source_order,
)
from backend.performance.wellness_days import WellnessDay
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
# Activity summaries name each value's source by the provider's activity label.
_ACTIVITY_LABEL_PROVIDERS = {
    provider_label(provider, SourceView.ACTIVITY_DETAIL): provider
    for provider in ProviderId
}
VO2MAX_UNIT = "ml/kg/min"
# The label of a locally confirmed zone configuration's value.
LOCAL_SOURCE_LABEL = "Lokal"
# The label of a profile value.
PROFILE_SOURCE_LABEL = "Manuell"


def coach_thresholds(
    metrics: Mapping[str, Mapping[str, Any]], canonical: CanonicalCurrentInputs
) -> dict[str, Any]:
    """Return the thresholds plans use, with the FTP's source and alternatives.

    FTP, LTHR and max heart rate are the source-policy current values, the same
    ones plans read; W′ is the athlete record's. A different current FTP of another
    source is listed under ``ftp_alternatives``, and ``ftp_conflict`` marks a
    material difference.
    """
    ftp = metrics["cycling_ftp_watts"]
    result: dict[str, Any] = {
        "ftp_w": ftp["value"],
        "ftp_source": ftp["source"],
        "w_prime_j": _observation_number(canonical.athlete_value(MetricKind.W_PRIME)),
        "max_hr": metrics["max_hr_bpm"]["value"],
        "lthr": metrics["bike_threshold_hr_bpm"]["value"],
        "run_lthr": metrics["run_threshold_hr_bpm"]["value"],
    }
    if ftp.get("alternatives"):
        result["ftp_alternatives"] = [
            {"source": item["source"], "value": item["value"]}
            for item in ftp["alternatives"]
        ]
        result["ftp_conflict"] = ftp["conflict"]
    return result


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


def _canonical_eftp_value(canonical: CanonicalCurrentInputs) -> float | None:
    """Return the athlete-record ride eFTP, else the latest wellness day's."""
    for observation in (canonical.athlete_eftp, canonical.wellness_eftp):
        if observation is not None:
            return observation.value.value
    return None


def _activity_max_hr(activity: Any) -> tuple[float, ProviderId] | None:
    """Return a summary's plausible max HR and the provider that reported it."""
    sources = activity.get("sources") if isinstance(activity, dict) else None
    if not isinstance(sources, dict):
        return None
    provider = _ACTIVITY_LABEL_PROVIDERS.get(str(sources.get("max_hr")))
    value = as_number(activity.get("max_hr"))
    if provider is None or value is None or not 80 <= float(value) <= 260:
        return None
    return float(value), provider


def _overall_max_hr(
    sports: tuple[dict[str, Any], ...],
    preferences: SourcePreferences = NO_PREFERENCES,
) -> dict[str, Any]:
    """The highest sport max HR among those of the best-ranked source.

    Sources rank as the max HR rule orders them (local, Garmin, Intervals), and
    activity maxima last, so a Garmin value wins before sports are compared.
    """
    order = [
        None if source is None else source.value
        for source in source_order(MetricKind.MAX_HR, None, preferences)
    ]

    def rank(item: dict[str, Any]) -> int:
        if item.get("source") == LOCAL_SOURCE_LABEL:
            return order.index(None)
        provider = item.get("source_provider")
        return order.index(provider) if provider in order else len(order)

    present = [item for item in sports if item["value"] is not None]
    if not present:
        return metric(None, "bpm", None)
    best = min(rank(item) for item in present)
    return max(
        (item for item in present if rank(item) == best), key=lambda item: item["value"]
    )


def _max_hr_metric(
    category: str,
    sport: Sport,
    activities: list[Any],
    thresholds: Mapping[ThresholdKey, Resolved],
    garmin_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return sport max HR: the source-policy winner, else the activity maximum.

    The winner is the local zone configuration, Garmin's profile value, then the
    Intervals setting or athlete record. Without any, the Garmin activity maximum,
    else the highest activity value, which keeps the provider its summary names.
    """
    key = f"{category}_max_hr_bpm"
    resolved = thresholds.get((MetricKind.MAX_HR, sport))
    if resolved is not None:
        return _resolved_metric(garmin_metrics, key, resolved)
    garmin = garmin_metrics[key]
    # Only Garmin's activity maximum (it carries ``observed_at``) is a fallback;
    # its profile max HR is a threshold the resolver has already aged.
    if garmin["value"] is not None and garmin.get("observed_at"):
        return garmin
    activity_values = [
        found
        for activity in activities
        if activity_kind(activity) == category
        and (found := _activity_max_hr(activity)) is not None
    ]
    best = max(activity_values, default=None, key=lambda item: item[0])
    if best is None:
        return metric(None, "bpm", None)
    number, provider = best
    return metric(
        number,
        "bpm",
        provider_label(provider, SourceView.CURRENT_METRIC),
        provider=provider,
    )


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


def _latest_ride_eftp(activities: list[Any]) -> Any:
    """Return the eFTP of the newest ride summary, or None."""
    rides = (
        activity
        for activity in activities
        if isinstance(activity, dict) and activity.get("sport") == Sport.RIDE.value
    )
    latest = max(
        rides, key=lambda item: str(item.get("started_at_local") or ""), default={}
    )
    return latest.get("eftp_w")


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


def _dated(observation: Observation | None) -> tuple[Candidate, ...]:
    if observation is None or observation.provenance.provider is None:
        return ()
    value = float(observation.value.value)
    return (
        Candidate(
            observation.provenance.provider, value, observation.observed_on, observation
        ),
    )


def _undated(observation: Observation | None) -> tuple[Candidate, ...]:
    """A value that is no dated measurement: only a fallback for the recency rule."""
    if observation is None or observation.provenance.provider is None:
        return ()
    value = float(observation.value.value)
    return (Candidate(observation.provenance.provider, value, None, observation),)


def _profile_candidate(value: Any) -> tuple[Candidate, ...]:
    number = as_number(value)
    return () if number is None else (Candidate(None, float(number)),)


def _body_candidates(
    kind: MetricKind,
    garmin_body: Iterable[Observation],
    wellness: Observation | None,
    athlete: Observation | None,
    profile_value: Any,
    wahoo: Observation | None = None,
) -> tuple[Candidate, ...]:
    """Weight or body fat of each source, in source order.

    Garmin's latest measurement and the Intervals wellness value are dated; the
    Intervals athlete record, the profile and Wahoo's profile weight are not.
    """
    garmin = next((item for item in garmin_body if item.kind is kind), None)
    return (
        *_dated(garmin),
        *_dated(wellness),
        *_undated(athlete),
        *_profile_candidate(profile_value),
        *_undated(wahoo),
    )


def _performance_body_metrics(
    latest_wellness: WellnessDay | None,
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    canonical: CanonicalCurrentInputs,
    garmin_body: tuple[Observation, ...],
    as_of: date | None,
) -> dict[str, dict[str, Any]]:
    """Weight and body fat by recency across sources (``source_policy``)."""

    def wellness(kind: MetricKind) -> Observation | None:
        return (
            None if latest_wellness is None else latest_wellness.observations.get(kind)
        )

    weight = resolve_candidates(
        MetricKind.WEIGHT,
        _body_candidates(
            MetricKind.WEIGHT,
            garmin_body,
            canonical.wellness_weight or wellness(MetricKind.WEIGHT),
            canonical.athlete_weight,
            profile.get("weight_kg"),
            canonical.wahoo_weight,
        ),
        as_of=as_of,
        preferences=canonical.preferences,
    )
    body_fat = resolve_candidates(
        MetricKind.BODY_FAT,
        _body_candidates(
            MetricKind.BODY_FAT,
            garmin_body,
            wellness(MetricKind.BODY_FAT),
            canonical.athlete_value(MetricKind.BODY_FAT),
            profile.get("body_fat_pct"),
        ),
        as_of=as_of,
        preferences=canonical.preferences,
    )
    height_value, height_source, height_provider = _first_performance_source(
        (
            _observation_source(canonical.athlete_value(MetricKind.HEIGHT)),
            # The canonical height is in cm; only the profile may hold metres.
            (_height_in_cm(profile.get("height_cm")), PROFILE_SOURCE_LABEL, None),
        )
    )
    return {
        "weight_kg": _resolved_entry(
            weight,
            "kg",
            as_number,
            garmin_metrics.get("weight_kg"),
            PROFILE_SOURCE_LABEL,
        ),
        "body_fat_pct": _resolved_entry(
            body_fat, "%", as_number, None, PROFILE_SOURCE_LABEL
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
    """VO2max and race predictions: Garmin, the originator, before Intervals."""
    current = garmin_metrics[key]
    return current if current["value"] is not None else fallback


def _intervals_metric(value: Any, unit: str) -> dict[str, Any]:
    return metric(value, unit, PROVIDER_INTERVALS_NAME, provider=ProviderId.INTERVALS)


def _speed_to_pace(value: float) -> float | int | None:
    return round(1000 / value) if value > 0 else None


# Display key -> (threshold key, unit, display conversion of the canonical value).
_THRESHOLD_METRICS: Final[
    Mapping[str, tuple[ThresholdKey, str, Callable[[float], float | int | None]]]
] = {
    "cycling_ftp_watts": ((MetricKind.FTP, Sport.RIDE), "W", as_number),
    "run_threshold_watts": ((MetricKind.FTP, Sport.RUN), "W", as_number),
    "run_threshold_pace_seconds_per_km": (
        (MetricKind.THRESHOLD_PACE, Sport.RUN),
        "s/km",
        _speed_to_pace,
    ),
    "bike_threshold_hr_bpm": ((MetricKind.THRESHOLD_HR, Sport.RIDE), "bpm", as_number),
    "run_threshold_hr_bpm": ((MetricKind.THRESHOLD_HR, Sport.RUN), "bpm", as_number),
    "cycling_max_hr_bpm": ((MetricKind.MAX_HR, Sport.RIDE), "bpm", as_number),
    "running_max_hr_bpm": ((MetricKind.MAX_HR, Sport.RUN), "bpm", as_number),
}


def _candidate_label(
    candidate: Candidate, local_label: str = LOCAL_SOURCE_LABEL
) -> str:
    if candidate.source is None:
        return local_label
    if candidate.observation is not None:
        label = observation_source_label(
            candidate.observation, SourceView.CURRENT_METRIC
        )
        if label:
            return label
    return provider_label(candidate.source, SourceView.CURRENT_METRIC)


def _resolved_metric(
    garmin_metrics: dict[str, dict[str, Any]],
    key: str,
    resolved: Resolved | None,
) -> dict[str, Any]:
    """A threshold's source-policy winner as a metric (``_resolved_entry``)."""
    _, unit, convert = _THRESHOLD_METRICS[key]
    return _resolved_entry(resolved, unit, convert, garmin_metrics.get(key))


def _resolved_entry(
    resolved: Resolved | None,
    unit: str,
    convert: Callable[[float], float | int | None],
    garmin: Mapping[str, Any] | None,
    local_label: str = LOCAL_SOURCE_LABEL,
) -> dict[str, Any]:
    """The source-policy winner as a metric, with the other sources' values.

    A Garmin winner keeps the ``garmin`` metric (label, note and freshness). Other
    sources' current values are listed as ``alternatives``; ``conflict`` marks a
    material difference (``source_policy`` conflict tolerances).
    """
    if resolved is None:
        return metric(None, unit, None)
    winner = resolved.winner
    if winner.source is ProviderId.GARMIN and garmin and garmin["value"] is not None:
        entry = dict(garmin)
    else:
        entry = metric(
            convert(winner.value),
            unit,
            _candidate_label(winner, local_label),
            provider=winner.source,
        )
    if resolved.alternatives:
        entry["alternatives"] = [
            {
                "value": convert(item.value),
                "source": _candidate_label(item, local_label),
                "source_provider": None if item.source is None else item.source.value,
            }
            for item in resolved.alternatives
        ]
        entry["conflict"] = resolved.conflict
    return entry


def _performance_threshold_metrics(
    garmin_metrics: dict[str, dict[str, Any]],
    canonical: CanonicalCurrentInputs,
    thresholds: Mapping[ThresholdKey, Resolved],
) -> dict[str, dict[str, Any]]:
    run_zone2_pace = canonical.athlete_value(MetricKind.ZONE2_PACE, Sport.RUN)
    resolved = {
        key: _resolved_metric(garmin_metrics, key, thresholds.get(threshold))
        for key, (threshold, _, _) in _THRESHOLD_METRICS.items()
        if "max_hr" not in key
    }
    return {
        **resolved,
        "run_zone2_pace_seconds_per_km": _intervals_metric(
            _zone2_pace_seconds(run_zone2_pace), "s/km"
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
    garmin_thresholds: Iterable[Observation] = (),
    garmin_body: Iterable[Observation] = (),
    as_of: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Compose current metrics from canonical inputs, Garmin metrics and the profile.

    Thresholds are resolved by the source policy from the current inputs'
    candidates and local values and the ``garmin_thresholds`` of the same read,
    current on ``as_of`` (None applies no age limit). Weight and body fat are
    resolved by recency with Garmin's latest ``garmin_body`` measurements.
    """
    latest_ride_eftp = _latest_ride_eftp(activities)
    current_ride_eftp = _canonical_eftp_value(canonical)
    thresholds = resolve_current_thresholds(
        (*canonical.threshold_candidates, *garmin_thresholds),
        canonical.local_thresholds,
        as_of=as_of,
        preferences=canonical.preferences,
    )
    cycling_max_hr = _max_hr_metric(
        "cycling", Sport.RIDE, activities, thresholds, garmin_metrics
    )
    running_max_hr = _max_hr_metric(
        "running", Sport.RUN, activities, thresholds, garmin_metrics
    )
    max_hr = _overall_max_hr((cycling_max_hr, running_max_hr), canonical.preferences)
    return {
        **_performance_body_metrics(
            latest_wellness,
            profile,
            garmin_metrics,
            canonical,
            tuple(garmin_body),
            as_of,
        ),
        **_performance_threshold_metrics(garmin_metrics, canonical, thresholds),
        "cycling_eftp_watts": _intervals_metric(
            current_ride_eftp or latest_ride_eftp, "W"
        ),
        "cycling_max_hr_bpm": cycling_max_hr,
        "running_max_hr_bpm": running_max_hr,
        "max_hr_bpm": max_hr,
        **_performance_vo2_and_prediction_metrics(garmin_metrics, canonical),
    }
