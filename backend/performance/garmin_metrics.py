"""Pure Garmin performance metric projection from canonical values.

The ingest-time parser of a fetched payload lives in
``backend.sync.garmin_payload_metrics``; both build the same metric shape here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.performance import freshness as performance_freshness
from backend.performance.current_metrics import as_number as _as_number
from backend.performance.current_metrics import metric as _metric
from backend.performance.garmin_canonical import (
    ACTIVITY_MAX_HR_CATEGORIES,
    GarminCanonicalMetrics,
    profile_max_hr_for,
)
from backend.providers.source_labels import SourceView, provider_label

GARMIN_PERFORMANCE_SOURCE = provider_label(
    ProviderId.GARMIN, SourceView.PERFORMANCE_NOTE
)
GARMIN_RUN_PREDICTION_SOURCE = "Garmin Connect Laufprognose"
_VO2MAX_UNIT = "ml/kg/min"
RACE_PREDICTION_KEYS = (
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)


def garmin_bounded_metric(
    value: Any, minimum: float, maximum: float
) -> float | int | None:
    number = _as_number(value)
    return (
        number if number is not None and minimum <= float(number) <= maximum else None
    )


def _garmin_canonical_thresholds(
    canonical: GarminCanonicalMetrics,
) -> tuple[
    float | int | None,
    float | int | None,
    float | int | None,
    float | int | None,
    float | int | None,
]:
    """Thresholds from the Garmin observations."""
    return (
        garmin_bounded_metric(canonical.cycling_ftp_watts, 50, 700),
        garmin_bounded_metric(canonical.run_threshold_watts, 50, 800),
        canonical.run_threshold_pace_seconds_per_km,
        garmin_bounded_metric(canonical.run_threshold_hr_bpm, 80, 230),
        garmin_bounded_metric(canonical.bike_threshold_hr_bpm, 80, 230),
    )


def _garmin_canonical_max_hr_samples(
    canonical: GarminCanonicalMetrics,
) -> tuple[dict[str, float | int], dict[str, list[float | int]], dict[str, str | None]]:
    """Profile max HR, else the max HR derived from the Garmin activity records."""
    profile_max_hr: dict[str, float | int] = dict(canonical.profile_max_hr)
    values: dict[str, list[float | int]] = {"cycling": [], "running": []}
    observed_at: dict[str, str | None] = {}
    for kind, samples in values.items():
        profile_value = profile_max_hr_for(profile_max_hr, kind)
        derived = canonical.activity_max_hr.get(kind)
        if profile_value is not None:
            samples.append(profile_value)
        elif derived is not None:
            samples.append(derived.value)
        observed_at[kind] = None if derived is None else derived.observed_on.isoformat()
    return profile_max_hr, values, observed_at


def _garmin_performance_units(
    weight: dict[str, Any],
    max_hr_values: dict[str, list[float | int]],
    profile_max_hr: dict[str, float | int],
    cycling_vo2: float | None,
    running_vo2: float | None,
    race_values: dict[str, float | int | None],
    thresholds: tuple[
        float | int | None,
        float | int | None,
        float | int | None,
        float | int | None,
        float | int | None,
    ],
) -> dict[str, tuple[float | int | None, str, str]]:
    cycling_ftp, running_power, running_pace, running_hr, cycling_hr = thresholds
    return {
        "weight_kg": (weight["value"], "kg", "Garmin Connect Körpergewicht"),
        "cycling_max_hr_bpm": (
            max(max_hr_values["cycling"], default=None),
            "bpm",
            "Garmin Connect Herzfrequenzzonen"
            if profile_max_hr_for(profile_max_hr, "cycling") is not None
            else "Garmin Connect Radaktivitäten",
        ),
        "running_max_hr_bpm": (
            max(max_hr_values["running"], default=None),
            "bpm",
            "Garmin Connect Herzfrequenzzonen"
            if profile_max_hr_for(profile_max_hr, "running") is not None
            else "Garmin Connect Laufaktivitäten",
        ),
        "cycling_vo2max_ml_kg_min": (
            cycling_vo2,
            _VO2MAX_UNIT,
            "Garmin Connect max metrics",
        ),
        "running_vo2max_ml_kg_min": (
            running_vo2,
            _VO2MAX_UNIT,
            "Garmin Connect max metrics",
        ),
        "run_5k_seconds": (
            race_values["run_5k_seconds"],
            "s",
            GARMIN_RUN_PREDICTION_SOURCE,
        ),
        "run_10k_seconds": (
            race_values["run_10k_seconds"],
            "s",
            GARMIN_RUN_PREDICTION_SOURCE,
        ),
        "run_half_marathon_seconds": (
            race_values["run_half_marathon_seconds"],
            "s",
            GARMIN_RUN_PREDICTION_SOURCE,
        ),
        "run_marathon_seconds": (
            race_values["run_marathon_seconds"],
            "s",
            GARMIN_RUN_PREDICTION_SOURCE,
        ),
        "cycling_ftp_watts": (cycling_ftp, "W", "Garmin Connect FTP"),
        "run_threshold_watts": (
            running_power,
            "W",
            "Garmin Connect Lauf-Schwellenleistung",
        ),
        "run_threshold_pace_seconds_per_km": (
            running_pace,
            "s/km",
            "Garmin Connect Lauf-Schwellenpace",
        ),
        "bike_threshold_hr_bpm": (
            cycling_hr,
            "bpm",
            "Garmin Connect Rad-Schwellenpuls",
        ),
        "run_threshold_hr_bpm": (
            running_hr,
            "bpm",
            "Garmin Connect Lauf-Schwellenpuls",
        ),
    }


def _garmin_performance_source_keys(
    profile_max_hr: dict[str, float | int],
) -> dict[str, str]:
    return {
        "weight_kg": "weight",
        "cycling_ftp_watts": "cycling_ftp",
        **{
            f"{kind}_max_hr_bpm": (
                "heart_rate_zones"
                if profile_max_hr_for(profile_max_hr, kind) is not None
                else "activities"
            )
            for kind in ACTIVITY_MAX_HR_CATEGORIES
        },
    }


def _garmin_performance_freshness(
    status: performance_freshness.GarminSyncStatus,
    metrics: dict[str, dict[str, Any]],
    source_keys: dict[str, str],
    race_values: dict[str, float | int | None],
    current_date: date,
) -> dict[str, dict[str, Any]]:
    for key, value in metrics.items():
        source = source_keys.get(key)
        if not source:
            if "vo2max" in key:
                source = "max_metrics"
            elif key in race_values:
                source = "race_predictions"
            else:
                source = "running_threshold"
        metrics[key] = performance_freshness.garmin_metric_freshness(
            status, source, value, current_date
        )
    return metrics


def assemble_garmin_metrics(
    status: performance_freshness.GarminSyncStatus,
    current_date: date,
    weight: dict[str, Any],
    vo2: tuple[float | int | None, float | int | None],
    race_values: dict[str, float | int | None],
    thresholds: tuple[
        float | int | None,
        float | int | None,
        float | int | None,
        float | int | None,
        float | int | None,
    ],
    max_hr: tuple[
        dict[str, float | int], dict[str, list[float | int]], dict[str, str | None]
    ],
) -> dict[str, dict[str, Any]]:
    """Build the labelled, freshness-stamped Garmin metrics from extracted values."""
    profile_max_hr, max_hr_values, activity_observed_at = max_hr
    units = _garmin_performance_units(
        weight,
        max_hr_values,
        profile_max_hr,
        vo2[0],
        vo2[1],
        race_values,
        thresholds,
    )
    source_keys = _garmin_performance_source_keys(profile_max_hr)
    result = {
        key: _metric(
            value, unit, GARMIN_PERFORMANCE_SOURCE, note, provider=ProviderId.GARMIN
        )
        for key, (value, unit, note) in units.items()
    }
    for kind in ("cycling", "running"):
        key = f"{kind}_max_hr_bpm"
        if source_keys[key] == "activities":
            result[key]["observed_at"] = activity_observed_at[kind]
    return _garmin_performance_freshness(
        status, result, source_keys, race_values, current_date
    )


def garmin_performance_metrics(
    status: performance_freshness.GarminSyncStatus,
    current_date: date,
    canonical: GarminCanonicalMetrics,
) -> dict[str, dict[str, Any]]:
    """Return the current Garmin performance metrics from the canonical values.

    Weight, FTP, VO2max, thresholds, profile max heart rate, race predictions and
    the activity max heart rate fallback come from ``canonical``; ``status``
    supplies only the freshness.
    """
    races: dict[str, float | int | None] = dict.fromkeys(RACE_PREDICTION_KEYS)
    races.update(canonical.race_predictions)
    return assemble_garmin_metrics(
        status,
        current_date,
        {"value": canonical.weight_kg},
        (canonical.cycling_vo2max, canonical.running_vo2max),
        races,
        _garmin_canonical_thresholds(canonical),
        _garmin_canonical_max_hr_samples(canonical),
    )


def garmin_performance_context(
    status: performance_freshness.GarminSyncStatus,
    current_date: date,
    canonical: GarminCanonicalMetrics,
) -> dict[str, Any]:
    """Project normalized Garmin performance metrics for public contexts."""
    metrics = garmin_performance_metrics(status, current_date, canonical)
    return {
        "source": GARMIN_PERFORMANCE_SOURCE,
        "weight": metrics["weight_kg"],
        "max_heart_rate": {
            "cycling_bpm": metrics["cycling_max_hr_bpm"],
            "running_bpm": metrics["running_max_hr_bpm"],
        },
        "vo2max": {
            "cycling_ml_kg_min": metrics["cycling_vo2max_ml_kg_min"],
            "running_ml_kg_min": metrics["running_vo2max_ml_kg_min"],
        },
        "estimated_run_times": {
            "5k_seconds": metrics["run_5k_seconds"],
            "10k_seconds": metrics["run_10k_seconds"],
            "half_marathon_seconds": metrics["run_half_marathon_seconds"],
            "marathon_seconds": metrics["run_marathon_seconds"],
        },
        "thresholds": {
            "cycling_ftp_watts": metrics["cycling_ftp_watts"],
            "run_threshold_watts": metrics["run_threshold_watts"],
            "run_threshold_pace_seconds_per_km": metrics[
                "run_threshold_pace_seconds_per_km"
            ],
            "bike_threshold_hr_bpm": metrics["bike_threshold_hr_bpm"],
            "run_threshold_hr_bpm": metrics["run_threshold_hr_bpm"],
        },
    }
