"""Stateless composition of the current performance context."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.performance import activity_validation
from backend.performance import comparisons as performance_comparisons
from backend.performance import current_metrics as performance_current_metrics
from backend.performance import daily_health as performance_daily_health
from backend.performance import freshness as performance_freshness
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import load as performance_load
from backend.performance import load_context as performance_load_context
from backend.performance import recovery_context as performance_recovery_context


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def current_performance_context(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Compose the current performance projection from explicit inputs."""
    if not snapshot:
        return {
            "available": False,
            "source": performance_current_metrics.PROVIDER_INTERVALS_NAME,
            "as_of": None,
            "metrics": {},
        }

    athlete = (
        snapshot.get("athlete") if isinstance(snapshot.get("athlete"), dict) else {}
    )
    activities = (
        snapshot.get("recent_activities")
        if isinstance(snapshot.get("recent_activities"), list)
        else []
    )
    wellness_rows = (
        [row for row in snapshot.get("recent_wellness", []) if isinstance(row, dict)]
        if isinstance(snapshot.get("recent_wellness"), list)
        else []
    )
    latest_wellness = max(
        wellness_rows,
        key=lambda row: str(row.get("id") or ""),
        default={},
    )

    recovery = performance_recovery_context.performance_recovery_context(
        garmin, latest_wellness, wellness_rows, today
    )
    sleep_hours = recovery["sleep_hours"]
    sleep_source = recovery["sleep_source"]
    sleep_score = recovery["sleep_score"]
    sleep_score_source = recovery["sleep_score_source"]
    resting_hr = recovery["resting_hr"]
    resting_hr_source = recovery["resting_hr_source"]
    hrv = recovery["hrv"]
    hrv_source = recovery["hrv_source"]
    readiness_current = recovery["readiness"]
    readiness_source = recovery["readiness_source"]

    metrics = performance_current_metrics.current_performance_metrics(
        snapshot,
        profile,
        performance_garmin_metrics.garmin_performance_metrics(garmin, today),
    )
    load_context = performance_load_context.performance_load_context(
        activities, wellness_rows, latest_wellness, today
    )
    load = load_context["load"]
    last_7 = load_context["last_7"]
    previous_7 = load_context["previous_7"]
    last_30 = load_context["last_30"]
    previous_30 = load_context["previous_30"]
    actual_atl_date = load_context["actual_atl_date"]
    actual_atl_current = load_context["actual_atl_current"]

    metrics.update(
        performance_daily_health.garmin_daily_health_metrics(
            garmin,
            7,
            today - timedelta(days=1),
            today,
        )
    )
    comparisons = performance_comparisons.performance_comparisons(
        snapshot,
        garmin,
        metrics,
        recovery,
        load_context,
        wellness_rows,
        activities,
        today,
    )
    activity_performance = activity_validation.activity_performance_validation(
        activities, metrics, comparisons
    )
    return {
        "available": True,
        "source": "Letzter gespeicherter Intervals.icu-Snapshot",
        "as_of": snapshot.get("synced_at"),
        "metrics": metrics,
        "thresholds": {
            "icu_ftp": metrics["cycling_ftp_watts"]["value"],
            "icu_w_prime": athlete.get("icu_w_prime"),
            "max_hr": athlete.get("max_hr"),
            "lthr": athlete.get("lthr"),
            "weight": metrics["weight_kg"]["value"],
        },
        "current_load": load,
        "actual_load": {
            "atl": actual_atl_current,
            "as_of": actual_atl_date.isoformat() if actual_atl_date else None,
            "source": "Abgeschlossene Aktivitäten (berechnet)",
        },
        "recovery": {
            "id": recovery["sleep_date"]
            or recovery["resting_hr_date"]
            or recovery["hrv_date"]
            or latest_wellness.get("id"),
            "restingHR": resting_hr,
            "restingHR_source": resting_hr_source,
            "hrv": hrv,
            "hrv_source": hrv_source,
            "sleepScore": sleep_score,
            "sleepScore_source": sleep_score_source,
            "fatigue": _first_present(latest_wellness, ("fatigue",)),
            "soreness": _first_present(latest_wellness, ("soreness",)),
            "stress": _first_present(latest_wellness, ("stress",)),
            "mood": _first_present(latest_wellness, ("mood",)),
            "readiness": readiness_current,
            "readiness_source": readiness_source,
            "sleep_hours": sleep_hours,
            "sleep_source": sleep_source,
            "source_freshness": {
                key: performance_freshness.garmin_metric_freshness(
                    garmin, section, {"value": value}, today
                )
                for key, section, value, source in (
                    ("readiness", "readiness", readiness_current, readiness_source),
                    ("sleep_hours", "sleep", sleep_hours, sleep_source),
                    ("sleepScore", "sleep", sleep_score, sleep_score_source),
                    ("restingHR", "resting_hr", resting_hr, resting_hr_source),
                    ("hrv", "hrv", hrv, hrv_source),
                )
                if source == performance_garmin_metrics.GARMIN_PERFORMANCE_SOURCE
            },
        },
        "rolling_training": {
            "last_7_days": last_7,
            "previous_7_days": previous_7,
            "last_30_days": last_30,
            "previous_30_days": previous_30,
            "last_28_days": performance_load.activity_rollup(activities, 28, today),
        },
        "comparisons": comparisons,
        "activity_validation": activity_performance,
    }
