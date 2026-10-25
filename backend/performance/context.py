"""Stateless composition of the current performance context."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.performance import activity_validation, garmin_projection
from backend.performance import comparisons as performance_comparisons
from backend.performance import current_metrics as performance_current_metrics
from backend.performance import daily_health as performance_daily_health
from backend.performance import freshness as performance_freshness
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import load as performance_load
from backend.performance import load_context as performance_load_context
from backend.performance import recovery_context as performance_recovery_context
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.personal_recovery import personal_recovery
from backend.performance.training_focus import training_focus
from backend.providers import intervals_performance_fields as intervals_perf_fields

# Recovery sources whose freshness comes from the Garmin view, including the
# labelled weekly HRV fallback.
_GARMIN_RECOVERY_SOURCES = frozenset(
    {
        performance_garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
        performance_recovery_context.GARMIN_WEEKLY_HRV_SOURCE,
    }
)


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _activities_and_wellness(
    snapshot: dict[str, Any], canonical: CanonicalPerformanceInputs | None
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Return the compact activities and wellness rows of the performance context.

    Canonical inputs hold the rows rebuilt from the canonical read ports; without
    them the snapshot sections are read as before.
    """
    if canonical is not None and canonical.activities is not None:
        activities: list[Any] = list(canonical.activities)
    else:
        raw_activities = snapshot.get("recent_activities")
        activities = raw_activities if isinstance(raw_activities, list) else []
    if canonical is not None and canonical.wellness_rows is not None:
        return activities, list(canonical.wellness_rows)
    raw_wellness = snapshot.get("recent_wellness")
    wellness_rows = (
        [row for row in raw_wellness if isinstance(row, dict)]
        if isinstance(raw_wellness, list)
        else []
    )
    return activities, wellness_rows


def _unavailable_context(
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
    canonical: CanonicalPerformanceInputs | None,
) -> dict[str, Any]:
    """Projection without an Intervals.icu snapshot: Garmin-only recovery and load."""
    unavailable = {
        "available": False,
        "source": performance_current_metrics.PROVIDER_INTERVALS_NAME,
        "as_of": None,
        "metrics": {},
        "personal_recovery": personal_recovery(
            [],
            garmin,
            profile,
            today,
            canonical=None if canonical is None else canonical.recovery,
        ),
        "training_focus": training_focus(
            None, garmin, today, str(profile.get("timezone") or "UTC")
        ),
    }
    load_projection = garmin_projection.garmin_training_load_projection(garmin, today)
    if load_projection:
        unavailable["garmin_training_load"] = load_projection
    return unavailable


def current_performance_context(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
    *,
    canonical: CanonicalPerformanceInputs | None = None,
) -> dict[str, Any]:
    """Compose the current performance projection from explicit inputs.

    ``canonical`` replaces CTL and ATL in the load context, the sport thresholds and
    VO2max, the Garmin performance values and the daily totals, when given. The
    recovery values and personal baselines come only from its recovery
    observations; without them they are absent.
    """
    if not snapshot:
        return _unavailable_context(garmin, profile, today, canonical)

    athlete_value = snapshot.get("athlete")
    athlete: dict[str, Any] = athlete_value if isinstance(athlete_value, dict) else {}
    activities, wellness_rows = _activities_and_wellness(snapshot, canonical)
    latest_wellness = max(
        wellness_rows,
        key=lambda row: str(row.get("id") or ""),
        default={},
    )

    recovery = performance_recovery_context.performance_recovery_context(
        None if canonical is None else canonical.recovery, today
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
        performance_garmin_metrics.garmin_performance_metrics(
            garmin, today, None if canonical is None else canonical.garmin
        ),
        canonical=None if canonical is None else canonical.current,
        activities=activities,
        wellness_rows=wellness_rows,
    )
    load_context = performance_load_context.performance_load_context(
        activities, wellness_rows, latest_wellness, today, canonical=canonical
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
            health_by_date=None if canonical is None else canonical.daily_health,
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
        "personal_recovery": personal_recovery(
            wellness_rows,
            garmin,
            profile,
            today,
            canonical=None if canonical is None else canonical.recovery,
        ),
        "garmin_training_load": garmin_projection.garmin_training_load_projection(
            garmin, today
        ),
        "training_focus": training_focus(
            snapshot,
            garmin,
            today,
            str(profile.get("timezone") or "UTC"),
            activity_rows=None if canonical is None else canonical.activity_rows,
        ),
        "source": "Letzter gespeicherter Intervals.icu-Snapshot",
        "as_of": snapshot.get("synced_at"),
        "metrics": metrics,
        "thresholds": {
            intervals_perf_fields.CONFIGURED_FTP: metrics["cycling_ftp_watts"]["value"],
            intervals_perf_fields.W_PRIME: athlete.get(intervals_perf_fields.W_PRIME),
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
                if source in _GARMIN_RECOVERY_SOURCES
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
