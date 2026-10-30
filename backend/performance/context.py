"""Compose the current performance context from canonical daily wellness values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.canonical.vocabulary import MetricKind
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
from backend.performance.wellness_days import WellnessDay, latest

_SUBJECTIVE_RATINGS = (
    ("fatigue", MetricKind.SUBJECTIVE_FATIGUE),
    ("soreness", MetricKind.SUBJECTIVE_SORENESS),
    ("stress", MetricKind.SUBJECTIVE_STRESS),
    ("mood", MetricKind.SUBJECTIVE_MOOD),
)

# Recovery sources whose freshness comes from the Garmin view, including the
# labelled weekly HRV fallback.
_GARMIN_RECOVERY_SOURCES = frozenset(
    {
        performance_garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
        performance_recovery_context.GARMIN_WEEKLY_HRV_SOURCE,
    }
)


def _activities(
    snapshot: dict[str, Any], canonical: CanonicalPerformanceInputs | None
) -> list[Any]:
    """Return canonical compact activities or the stored activity projection."""
    if canonical is not None and canonical.activities is not None:
        activities: list[Any] = list(canonical.activities)
    else:
        raw_activities = snapshot.get("recent_activities")
        activities = raw_activities if isinstance(raw_activities, list) else []
    return activities


def _canonical_day_series(
    canonical: CanonicalPerformanceInputs | None,
) -> dict[str, Mapping[date, float] | None]:
    """The canonical eFTP and form day series; both absent without canonical inputs."""
    if canonical is None:
        return {"eftp_by_day": None, "form_by_day": None, "run_eftp_by_day": None}
    return {
        "eftp_by_day": canonical.eftp_by_day,
        "form_by_day": canonical.form_by_day,
        "run_eftp_by_day": canonical.run_eftp_by_day,
    }


def _activity_rows(canonical: CanonicalPerformanceInputs | None) -> Sequence[Any]:
    """The canonical activity rows, none without canonical inputs."""
    return (
        ()
        if canonical is None or canonical.activity_rows is None
        else canonical.activity_rows
    )


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
            garmin,
            today,
            str(profile.get("timezone") or "UTC"),
            activity_rows=_activity_rows(canonical),
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

    Canonical days supply wellness, load and body values. The stored snapshot
    remains the source for athlete settings, activities without a row reader and
    the pre-sleep-period timing fallback.
    """
    if not snapshot:
        return _unavailable_context(garmin, profile, today, canonical)

    athlete_value = snapshot.get("athlete")
    athlete: dict[str, Any] = athlete_value if isinstance(athlete_value, dict) else {}
    activities = _activities(snapshot, canonical)
    days: tuple[WellnessDay, ...] = (
        () if canonical is None else canonical.wellness_days or ()
    )
    latest_wellness = latest(days)
    stored_wellness = snapshot.get("recent_wellness")
    sleep_timing_rows = (
        [row for row in stored_wellness if isinstance(row, dict)]
        if isinstance(stored_wellness, list)
        else []
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
        latest_wellness=latest_wellness,
    )
    load_context = performance_load_context.performance_load_context(
        activities, days, today, canonical=canonical
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
        days,
        activities,
        today,
        garmin_history=None
        if canonical is None or canonical.garmin is None
        else canonical.garmin.performance_history,
        **_canonical_day_series(canonical),
    )
    activity_performance = activity_validation.activity_performance_validation(
        activities, metrics, comparisons
    )
    return {
        "available": True,
        "personal_recovery": personal_recovery(
            sleep_timing_rows,
            garmin,
            profile,
            today,
            canonical=None if canonical is None else canonical.recovery,
        ),
        "garmin_training_load": garmin_projection.garmin_training_load_projection(
            garmin, today, None if canonical is None else canonical.garmin
        ),
        "training_focus": training_focus(
            garmin,
            today,
            str(profile.get("timezone") or "UTC"),
            activity_rows=_activity_rows(canonical),
        ),
        "source": "Letzter gespeicherter Intervals.icu-Snapshot",
        "as_of": snapshot.get("synced_at"),
        "metrics": metrics,
        "thresholds": {
            "ftp_w": metrics["cycling_ftp_watts"]["value"],
            "w_prime_j": performance_current_metrics.athlete_w_prime(athlete),
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
            or (latest_wellness.day.isoformat() if latest_wellness else None),
            "resting_hr_bpm": resting_hr,
            "resting_hr_bpm_source": resting_hr_source,
            "hrv_ms": hrv,
            "hrv_ms_source": hrv_source,
            "sleep_score": sleep_score,
            "sleep_score_source": sleep_score_source,
            **{
                key: None if latest_wellness is None else latest_wellness.value(kind)
                for key, kind in _SUBJECTIVE_RATINGS
            },
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
                    ("sleep_score", "sleep", sleep_score, sleep_score_source),
                    ("resting_hr_bpm", "resting_hr", resting_hr, resting_hr_source),
                    ("hrv_ms", "hrv", hrv, hrv_source),
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
