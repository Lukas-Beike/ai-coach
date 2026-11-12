"""Current performance metric composition from canonical inputs.

Thresholds resolve by the source policy (local, Garmin, Wahoo), Garmin values come
from the Garmin metrics, and activity values from the canonical activity rows.
Intervals.icu is never a source. No snapshot section is read.
"""

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Any, Final

from backend.activities.hr_cap import effective_caps, resolved_range
from backend.activities.identity import activity_kind
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.canonical_current import CanonicalCurrentInputs
from backend.performance.current_thresholds import (
    ThresholdKey,
    resolve_current_thresholds,
)
from backend.performance.garmin_canonical import ActivityMaxHr
from backend.performance.source_policy import (
    NO_PREFERENCES,
    Candidate,
    Resolved,
    SourcePreferences,
    resolve_candidates,
    source_order,
)
from backend.providers.source_labels import (
    SourceView,
    observation_source_label,
    provider_label,
)

PROVIDER_INTERVALS_NAME = provider_label(
    ProviderId.INTERVALS, SourceView.CURRENT_METRIC
)
GARMIN_PERFORMANCE_SOURCE = provider_label(ProviderId.GARMIN, SourceView.CURRENT_METRIC)
# Activity summaries name each value's source by the provider's activity label;
# only Garmin and Wahoo summaries serve the max HR fallback (Intervals.icu is an
# output target, #1732).
_ACTIVITY_LABEL_PROVIDERS = {
    provider_label(provider, SourceView.ACTIVITY_DETAIL): provider
    for provider in (ProviderId.GARMIN, ProviderId.WAHOO)
}
VO2MAX_UNIT = "ml/kg/min"
# The label of a locally confirmed zone configuration's value.
LOCAL_SOURCE_LABEL = "Lokal"
# The label of a profile value.
PROFILE_SOURCE_LABEL = "Manuell"


def _with_resolved_bpm(cap: dict[str, Any], lthr: float | None) -> dict[str, Any]:
    """The stored cap value plus its current bpm range, when a threshold HR is known."""
    resolved = resolved_range(cap, lthr)
    if resolved is None:
        return cap
    return {**cap, "low_bpm": resolved[0], "bpm": resolved[1]}


def coach_thresholds(
    metrics: Mapping[str, Mapping[str, Any]],
    first_threshold_pct: float | None = None,
    first_threshold_estimated: bool = False,
) -> dict[str, Any]:
    """Return the thresholds plans use, with the FTP's source and alternatives.

    FTP, LTHR and max heart rate are the source-policy current values, the same
    ones plans read. A different current FTP of another
    source is listed under ``ftp_alternatives``, and ``ftp_conflict`` marks a
    material difference.
    """
    ftp = metrics["cycling_ftp_watts"]
    result: dict[str, Any] = {
        "ftp_w": ftp["value"],
        "ftp_source": ftp["source"],
        "max_hr": metrics["max_hr_bpm"]["value"],
        "lthr": metrics["bike_threshold_hr_bpm"]["value"],
        "run_lthr": metrics["run_threshold_hr_bpm"]["value"],
    }
    # The heart-rate cap of each easy run type, in percent (what the Coach writes,
    # with its source), and the bpm it currently resolves to for the run LTHR.
    run_lthr = result["run_lthr"]
    lthr = run_lthr if isinstance(run_lthr, int | float) and run_lthr > 0 else None
    result["run_hr_caps"] = {
        focus: _with_resolved_bpm(cap, lthr)
        for focus, cap in effective_caps(
            first_threshold_pct, first_threshold_estimated
        ).items()
    }
    if ftp.get("alternatives"):
        result["ftp_alternatives"] = [
            {"source": item["source"], "value": item["value"]}
            for item in ftp["alternatives"]
        ]
        result["ftp_conflict"] = ftp["conflict"]
    return result


# LT1 as a fixed share of LT2 when no measured or adopted value exists (athlete
# decision 2026-11-12, #2427): heart rate of the threshold HR, cycling power of
# the FTP and running speed of the threshold speed. Change them here only.
LT1_HR_SHARE: Final = 0.90
LT1_POWER_SHARE: Final = 0.75
LT1_RUN_SPEED_SHARE: Final = 0.88
# Where an LT1 value comes from: the profile value (measured, or the adopted
# DFA-a1 estimate), the top of the configured zone 2, or a fixed share of LT2.
LT1_ZONE_TWO: Final = "zone_2"
LT1_FIXED_SHARE: Final = "fixed_share"


def first_thresholds(
    metrics: Mapping[str, Mapping[str, Any]],
    first_threshold_pct: float | None,
    origin: str,
    zone_two_tops: Mapping[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """LT1 of running and cycling with the origin of each value.

    Heart rate: the stored share of the threshold HR (``origin``, measured or
    estimated) or else ``LT1_HR_SHARE``. Pace and power: the top of zone 2 when
    ``zone_two_tops`` has one for the sport (``"run"`` in s/km, ``"ride"`` in W),
    otherwise the fixed share of the threshold pace or the FTP. A value without
    its LT2 is left out.
    """
    tops = zone_two_tops or {}
    result: dict[str, dict[str, Any]] = {}
    for sport, lthr_key, lt2_key, main_key, main_origin_key, share in (
        ("run", "run_threshold_hr_bpm", "run_threshold_pace_seconds_per_km",
         "pace_seconds_per_km", "pace_origin", 1 / LT1_RUN_SPEED_SHARE),
        ("ride", "bike_threshold_hr_bpm", "cycling_ftp_watts",
         "watts", "power_origin", LT1_POWER_SHARE),
    ):  # fmt: skip
        values: dict[str, Any] = {}
        lthr = as_number(metrics.get(lthr_key, {}).get("value"))
        if lthr is not None and lthr > 0:
            pct = first_threshold_pct
            values["hr_bpm"] = round(lthr * (pct / 100 if pct else LT1_HR_SHARE))
            values["hr_origin"] = origin if pct else LT1_FIXED_SHARE
        lt2 = as_number(metrics.get(lt2_key, {}).get("value"))
        if tops.get(sport):
            values[main_key] = round(tops[sport])
            values[main_origin_key] = LT1_ZONE_TWO
        elif lt2 is not None and lt2 > 0:
            values[main_key] = round(lt2 * share)
            values[main_origin_key] = LT1_FIXED_SHARE
        if values:
            result[sport] = values
    return result


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
    sports: tuple[tuple[dict[str, Any], bool], ...],
    preferences: SourcePreferences = NO_PREFERENCES,
) -> dict[str, Any]:
    """The highest sport max HR among those of the best-ranked source.

    ``sports`` pairs each sport's metric with whether it is an activity maximum.
    Sources rank as the max HR rule orders them (local, Garmin), and every
    activity maximum last, whichever provider it came from, so a threshold wins
    before sports are compared and activity maxima compare by value.
    """
    order = [
        None if source is None else source.value
        for source in source_order(MetricKind.MAX_HR, None, preferences)
    ]

    def rank(item: dict[str, Any], from_activity: bool) -> int:
        if from_activity:
            return len(order)
        if item.get("source") == LOCAL_SOURCE_LABEL:
            return order.index(None)
        provider = item.get("source_provider")
        return order.index(provider) if provider in order else len(order)

    present = [(item, flag) for item, flag in sports if item["value"] is not None]
    if not present:
        return metric(None, "bpm", None)
    best = min(rank(item, flag) for item, flag in present)
    return max(
        (item for item, flag in present if rank(item, flag) == best),
        key=lambda item: item["value"],
    )


def _max_hr_metric(
    category: str,
    sport: Sport,
    activities: list[Any],
    thresholds: Mapping[ThresholdKey, Resolved],
    garmin_metrics: dict[str, dict[str, Any]],
    wahoo_activity_max_hr: Mapping[str, ActivityMaxHr] | None = None,
) -> dict[str, Any]:
    """Return sport max HR: the source-policy winner, else the activity maximum.

    The winner is the local zone configuration, then Garmin's profile value.
    Without any, the highest stored activity maximum of Garmin and Wahoo over the
    whole history wins, dated on its newest start day; Garmin wins a tie (#1686).
    Only when neither provider stores one, the highest Garmin or Wahoo session
    summary value is used.
    """
    key = f"{category}_max_hr_bpm"
    resolved = thresholds.get((MetricKind.MAX_HR, sport))
    if resolved is not None:
        return _resolved_metric(garmin_metrics, key, resolved)
    garmin = garmin_metrics[key]
    # Only Garmin's activity maximum (it carries ``observed_at``) is a fallback;
    # its profile max HR is a threshold the resolver has already aged.
    garmin_value = (
        float(garmin["value"])
        if garmin["value"] is not None and garmin.get("observed_at")
        else None
    )
    wahoo = (wahoo_activity_max_hr or {}).get(category)
    if wahoo is not None and (garmin_value is None or wahoo.value > garmin_value):
        entry = metric(
            wahoo.value,
            "bpm",
            provider_label(ProviderId.WAHOO, SourceView.CURRENT_METRIC),
            provider=ProviderId.WAHOO,
        )
        entry["observed_at"] = wahoo.observed_on.isoformat()
        return entry
    if garmin_value is not None:
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


def _height_in_cm(value: Any) -> float | int | None:
    number = as_number(value)
    if number is not None and 1.2 <= float(number) <= 2.5:
        return round(float(number) * 100, 1)
    return number


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
    profile_value: Any,
    wahoo: Observation | None = None,
) -> tuple[Candidate, ...]:
    """Weight or body fat of each source, in source order.

    Garmin's latest measurement is dated; the profile and Wahoo's profile weight
    are not.
    """
    garmin = next((item for item in garmin_body if item.kind is kind), None)
    return (
        *_dated(garmin),
        *_profile_candidate(profile_value),
        *_undated(wahoo),
    )


def _performance_body_metrics(
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    canonical: CanonicalCurrentInputs,
    garmin_body: tuple[Observation, ...],
    as_of: date | None,
) -> dict[str, dict[str, Any]]:
    """Weight and body fat by recency across sources (``source_policy``)."""
    weight = resolve_candidates(
        MetricKind.WEIGHT,
        _body_candidates(
            MetricKind.WEIGHT,
            garmin_body,
            profile.get("weight_kg"),
            canonical.wahoo_weight,
        ),
        as_of=as_of,
        preferences=canonical.preferences,
    )
    body_fat = resolve_candidates(
        MetricKind.BODY_FAT,
        _body_candidates(MetricKind.BODY_FAT, garmin_body, profile.get("body_fat_pct")),
        as_of=as_of,
        preferences=canonical.preferences,
    )
    # The canonical height is in cm; only the profile may hold metres.
    height_value, height_source, height_provider = _first_performance_source(
        ((_height_in_cm(profile.get("height_cm")), PROFILE_SOURCE_LABEL, None),)
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
    """VO2max and race predictions: Garmin's value, else the fallback."""
    current = garmin_metrics[key]
    return current if current["value"] is not None else fallback


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
    """A threshold's source-policy winner as a metric (``_resolved_entry``).

    Garmin's own metric (label, note, freshness) stands for a Garmin winner only
    while it shows the same value; the watch zone set can lead a different one.
    """
    _, unit, convert = _THRESHOLD_METRICS[key]
    garmin = garmin_metrics.get(key)
    if (
        garmin
        and resolved is not None
        and garmin["value"] != convert(resolved.winner.value)
    ):
        garmin = None
    return _resolved_entry(resolved, unit, convert, garmin)


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
    thresholds: Mapping[ThresholdKey, Resolved],
) -> dict[str, dict[str, Any]]:
    resolved = {
        key: _resolved_metric(garmin_metrics, key, thresholds.get(threshold))
        for key, (threshold, _, _) in _THRESHOLD_METRICS.items()
        if "max_hr" not in key
    }
    return resolved


def _performance_vo2_and_prediction_metrics(
    garmin_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        key: _preferred_performance_metric(
            garmin_metrics, key, metric(None, unit, None)
        )
        for key, unit in (
            ("cycling_vo2max_ml_kg_min", VO2MAX_UNIT),
            ("running_vo2max_ml_kg_min", VO2MAX_UNIT),
            ("run_5k_seconds", "s"),
            ("run_10k_seconds", "s"),
            ("run_half_marathon_seconds", "s"),
            ("run_marathon_seconds", "s"),
        )
    }


def current_performance_metrics(
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    *,
    canonical: CanonicalCurrentInputs,
    activities: list[Any],
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
    thresholds = resolve_current_thresholds(
        (*canonical.threshold_candidates, *garmin_thresholds),
        canonical.configured_thresholds,
        as_of=as_of,
        preferences=canonical.preferences,
    )
    wahoo = canonical.wahoo_activity_max_hr
    cycling_max_hr = _max_hr_metric(
        "cycling", Sport.RIDE, activities, thresholds, garmin_metrics, wahoo
    )
    running_max_hr = _max_hr_metric(
        "running", Sport.RUN, activities, thresholds, garmin_metrics, wahoo
    )
    max_hr = _overall_max_hr(
        (
            (cycling_max_hr, thresholds.get((MetricKind.MAX_HR, Sport.RIDE)) is None),
            (running_max_hr, thresholds.get((MetricKind.MAX_HR, Sport.RUN)) is None),
        ),
        canonical.preferences,
    )
    return {
        **_performance_body_metrics(
            profile, garmin_metrics, canonical, tuple(garmin_body), as_of
        ),
        **_performance_threshold_metrics(garmin_metrics, thresholds),
        "cycling_max_hr_bpm": cycling_max_hr,
        "running_max_hr_bpm": running_max_hr,
        "max_hr_bpm": max_hr,
        **_performance_vo2_and_prediction_metrics(garmin_metrics),
    }
