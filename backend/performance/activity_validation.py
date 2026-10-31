"""Pure validation projections for completed activity performance data."""

from __future__ import annotations

from typing import Any

from backend.activities.activity_summary import summary_duration_s
from backend.activities.identity import activity_datetime
from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.labels import sport_label_de


def _present(item: Any, key: str) -> Any:
    if not isinstance(item, dict):
        return None
    value = item.get(key)
    return None if value in (None, "") else value


def _threshold_pace_seconds(value: Any) -> float | int | None:
    number = _as_number(value)
    if number is None or number <= 0:
        return None
    return round(1000 / number) if number < 20 else number


def activity_pace_seconds_per_km(summary: dict[str, Any]) -> float | int | None:
    """Normalize a summary pace or speed into seconds per kilometre."""
    pace = _present(summary, "pace_mps")
    if pace is not None:
        normalized = _threshold_pace_seconds(pace)
        if normalized is not None and 120 <= float(normalized) <= 1800:
            return normalized
    speed = _as_number(_present(summary, "avg_speed_mps"))
    if speed is None or speed <= 0:
        return None
    normalized = round(1000 / float(speed)) if float(speed) < 20 else float(speed)
    return normalized if 120 <= normalized <= 1800 else None


def latest_activity_for_validation(activities: list[Any]) -> dict[str, Any] | None:
    """Return the newest activity summary with a usable timestamp."""
    dated = [
        item
        for item in (activities if isinstance(activities, list) else ())
        if isinstance(item, dict)
        and activity_datetime(item.get("started_at_local") or item.get("started_at"))
        is not None
    ]
    return max(
        dated,
        key=lambda item: (
            activity_datetime(item.get("started_at_local") or item.get("started_at")),
            str(item.get("id") or ""),
        ),
        default=None,
    )


def bounded_activity_metric(
    value: Any, minimum: float, maximum: float
) -> float | int | None:
    """Normalize a bounded numeric estimate from an untrusted activity record."""
    if isinstance(value, (dict, list)) or (isinstance(value, str) and len(value) > 32):
        return None
    number = _as_number(value)
    return (
        number if number is not None and minimum <= float(number) <= maximum else None
    )


def activity_intensity(value: Any) -> float | int | None:
    """Normalize Intervals.icu fractional or percentage intensity values."""
    intensity = bounded_activity_metric(value, 0, 200)
    if intensity is not None and 0 < float(intensity) <= 2:
        return round(float(intensity) * 100, 1)
    return intensity


def activity_validation_evidence(latest: dict[str, Any], sport: str) -> dict[str, Any]:
    """Return bounded measured evidence from one untrusted activity summary."""
    activity_id = _present(latest, "id")
    evidence: dict[str, Any] = {
        "activity_id": str(activity_id)[:200] if activity_id is not None else None,
        "date": str(
            _present(latest, "started_at_local") or _present(latest, "started_at") or ""
        )[:40],
        "name": str(latest.get("name") or "")[:200],
        "sport": sport,
    }
    duration = summary_duration_s(latest)
    for key, value, minimum, maximum in (
        ("duration_seconds", duration, 1, 604800),
        ("distance", latest.get("distance_m"), 0, 1_000_000),
        ("elevation_gain", latest.get("elevation_gain_m"), 0, 100_000),
        ("training_load", latest.get("training_load"), 0, 100_000),
        ("intensity", latest.get("intensity"), 0, 1_000),
        ("average_heart_rate_bpm", latest.get("avg_hr"), 30, 230),
        ("max_heart_rate_bpm", latest.get("max_hr"), 30, 230),
        ("average_power_watts", latest.get("avg_power"), 0, 5_000),
        (
            "weighted_power_watts",
            latest.get("normalized_power"),
            0,
            5_000,
        ),
        ("rpe", latest.get("rpe"), 0, 10),
    ):
        value = (
            activity_intensity(value)
            if key == "intensity"
            else bounded_activity_metric(value, minimum, maximum)
        )
        if value is not None:
            evidence[key] = value
    return evidence


def activity_direct_estimates(latest: dict[str, Any]) -> dict[str, float | int]:
    """Return only bounded numeric estimates explicitly attached to an activity."""
    estimates: dict[str, float | int] = {}
    for key, summary_key, minimum, maximum in (
        ("activity_vo2max", "vo2max", 10, 100),
        ("activity_eftp_watts", "eftp_w", 20, 2000),
        ("activity_configured_ftp_watts", "ftp_w", 20, 2000),
    ):
        value = bounded_activity_metric(_present(latest, summary_key), minimum, maximum)
        if value is not None:
            estimates[key] = value
    return estimates


def bounded_performance_metric(key: str, value: Any) -> float | int | None:
    """Normalize provider performance values before using them for validation."""
    bounds = {
        "cycling_ftp_watts": (20, 2000),
        "cycling_eftp_watts": (20, 2000),
        "run_threshold_watts": (20, 2000),
        "running_vo2max_ml_kg_min": (10, 100),
        "cycling_vo2max_ml_kg_min": (10, 100),
        "run_threshold_pace_seconds_per_km": (120, 1800),
        "run_zone2_pace_seconds_per_km": (120, 1800),
        "run_threshold_hr_bpm": (80, 230),
        "bike_threshold_hr_bpm": (80, 230),
        "run_5k_seconds": (1, 86400),
        "run_10k_seconds": (1, 86400),
        "run_half_marathon_seconds": (1, 172800),
        "run_marathon_seconds": (1, 345600),
    }
    minimum, maximum = bounds.get(key, (None, None))
    if minimum is None:
        return _as_number(value)
    return bounded_activity_metric(value, minimum, maximum)


def cycling_activity_validation_details(
    activity_evidence: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
) -> tuple[tuple[str, ...], str]:
    ftp_record = (
        metrics.get("cycling_ftp_watts", {}) if isinstance(metrics, dict) else {}
    )
    ftp = bounded_activity_metric(
        ftp_record.get("value") if isinstance(ftp_record, dict) else None,
        20,
        2000,
    )
    weighted_power = activity_evidence.get(
        "weighted_power_watts"
    ) or activity_evidence.get("average_power_watts")
    if weighted_power is not None and ftp is not None:
        power_percent = round(float(weighted_power) / float(ftp) * 100, 1)
        if 0 <= power_percent <= 500:
            activity_evidence["power_as_percent_of_current_ftp"] = power_percent
    return (
        ("cycling_vo2max_ml_kg_min", "cycling_ftp_watts", "cycling_eftp_watts"),
        (
            "Leistung, Herzfrequenz, Dauer und Intensität dieser Einheit sind direkte Belastungsevidenz. "
            "Sie bestätigen oder widerlegen FTP und VO2max aber nur bei einem ausreichend langen "
            "und geeigneten Belastungsprofil; eine normale Ausfahrt ist kein FTP-Test."
        ),
    )


def activity_validation_details(
    latest: dict[str, Any],
    sport: str,
    metrics: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], tuple[str, ...], str]:
    activity_evidence = activity_validation_evidence(latest, sport)
    if sport == "Laufen":
        pace = activity_pace_seconds_per_km(latest)
        if pace is not None:
            activity_evidence["pace_seconds_per_km"] = pace
        return (
            activity_evidence,
            (
                "running_vo2max_ml_kg_min",
                "run_threshold_pace_seconds_per_km",
                "run_zone2_pace_seconds_per_km",
                "run_threshold_hr_bpm",
                "run_5k_seconds",
                "run_10k_seconds",
                "run_half_marathon_seconds",
                "run_marathon_seconds",
            ),
            (
                "Pace und Herzfrequenz dieser Einheit sind direkte Belastungsevidenz. "
                "Sie validieren Schwelle, VO2max, Zone-2-Pace und Wettkampfprognosen nur, "
                "wenn Dauer, Intensität, Profil und Messqualität dafür geeignet sind."
            ),
        )
    if sport == "Radfahren":
        reference_keys, interpretation = cycling_activity_validation_details(
            activity_evidence, metrics
        )
        return activity_evidence, reference_keys, interpretation
    return (
        activity_evidence,
        (),
        "Für diese Sportart ist keine sportartspezifische Leistungsvalidierung hinterlegt.",
    )


def activity_performance_validation(
    activities: list[Any],
    metrics: dict[str, dict[str, Any]],
    comparisons: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    """Expose latest-activity evidence without pretending it is a lab test."""
    latest = latest_activity_for_validation(activities)
    if latest is None:
        return {
            "available": False,
            "status": "no_completed_activity",
            "scope": "Keine abgeschlossene Einheit mit verwertbarem Zeitstempel vorhanden.",
        }

    sport = activity_sport(latest)
    activity_evidence, reference_keys, interpretation = activity_validation_details(
        latest, sport, metrics
    )
    provider_references = []
    metrics_map = metrics if isinstance(metrics, dict) else {}
    comparisons_map = comparisons if isinstance(comparisons, dict) else {}
    for key in reference_keys:
        provider_value = metrics_map.get(key, {})
        provider_value = provider_value if isinstance(provider_value, dict) else {}
        raw_value = provider_value.get("value")
        value = bounded_performance_metric(key, raw_value)
        if raw_value not in (None, "") and value is None:
            continue
        provider_references.append(
            {
                "metric": key,
                "value": value,
                "unit": provider_value.get("unit"),
                "source": provider_value.get("source"),
                "observed_at": provider_value.get("observed_at"),
                "historical_comparison": comparisons_map.get(
                    {"cycling_eftp_watts": "cycling_eftp_30d"}.get(key, f"{key}_30d")
                ),
            }
        )
    return {
        "available": True,
        "status": "needs_coach_interpretation",
        "activity": activity_evidence,
        "provider_references": provider_references,
        "direct_activity_estimates": activity_direct_estimates(latest),
        "interpretation_boundary": interpretation,
        "validation_outcome_enum": [
            "direct_support",
            "plausible_corroboration",
            "conflict",
            "insufficient_evidence",
        ],
        "scope": "Vergleich der analysierten abgeschlossenen Einheit mit Provider-Leistungswerten; keine Laborvalidierung.",
    }


def activity_sport(summary: dict[str, Any]) -> str:
    """Return the German label of the canonical sport of an activity summary."""
    try:
        return sport_label_de(str(summary.get("sport") or "other"))
    except ValueError:
        return sport_label_de("other")
