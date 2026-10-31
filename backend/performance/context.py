"""Compose the current performance context from canonical daily wellness values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Final

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
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
)
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.performance.personal_recovery import personal_recovery
from backend.performance.training_focus import training_focus
from backend.performance.wellness_days import WellnessDay, latest

_SUBJECTIVE_RATINGS = (
    ("fatigue", MetricKind.SUBJECTIVE_FATIGUE),
    ("soreness", MetricKind.SUBJECTIVE_SORENESS),
    ("stress", MetricKind.SUBJECTIVE_STRESS),
    ("mood", MetricKind.SUBJECTIVE_MOOD),
)

# The reason an unavailable context gives while the canonical source serves nothing yet.
REASON_CANONICAL_PENDING: Final = "canonical_pending"
PENDING_STATUS: Final = "Daten werden vorbereitet"
INTERVALS_SNAPSHOT_SOURCE: Final = "Letzter gespeicherter Intervals.icu-Snapshot"
# The source of a context without an Intervals.icu sync, e.g. a Garmin-only setup.
STORED_PROVIDERS_SOURCE: Final = "Gespeicherte Provider-Daten"

# Recovery sources whose freshness comes from the Garmin view, including the
# labelled weekly HRV fallback.
_GARMIN_RECOVERY_SOURCES = frozenset(
    {
        performance_garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
        performance_recovery_context.GARMIN_WEEKLY_HRV_SOURCE,
    }
)


def _activities(canonical: CanonicalPerformanceInputs) -> list[Any]:
    """Return the canonical activity summaries; none when none were read."""
    return list(canonical.activities or ())


def _sleep_timing_rows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Stored wellness rows for the pre-sleep-period timing fallback only (D7)."""
    stored = (snapshot or {}).get("recent_wellness")
    if not isinstance(stored, list):
        return []
    return [row for row in stored if isinstance(row, dict)]


def _day_id(day: WellnessDay | None) -> str | None:
    return None if day is None else day.day.isoformat()


def _subjective_ratings(day: WellnessDay | None) -> dict[str, float | None]:
    return {
        key: None if day is None else day.value(kind)
        for key, kind in _SUBJECTIVE_RATINGS
    }


def _canonical_day_series(
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Mapping[date, float] | None]:
    """The canonical eFTP and form day series."""
    return {
        "eftp_by_day": canonical.eftp_by_day,
        "form_by_day": canonical.form_by_day,
        "run_eftp_by_day": canonical.run_eftp_by_day,
    }


def _garmin_canonical(canonical: CanonicalPerformanceInputs) -> GarminCanonicalMetrics:
    """The canonical Garmin values; empty when none were read."""
    return canonical.garmin or GarminCanonicalMetrics()


def _as_of(canonical: CanonicalPerformanceInputs) -> str | None:
    """The instant of the latest canonical Intervals.icu sync, None without one."""
    synced_at = canonical.current.synced_at
    return None if synced_at is None else synced_at.isoformat()


def _pending_context(profile: dict[str, Any], today: date) -> dict[str, Any]:
    """The context while the canonical source serves nothing yet: no values at all."""
    return {
        **_unavailable_context({}, profile, today, EMPTY_PERFORMANCE_INPUTS),
        "reason": REASON_CANONICAL_PENDING,
        "status": PENDING_STATUS,
    }


def _unavailable_context(
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Any]:
    """Projection without canonical inputs: Garmin-only recovery and load."""
    unavailable = {
        "available": False,
        "source": performance_current_metrics.PROVIDER_INTERVALS_NAME,
        "as_of": None,
        "metrics": {},
        "activities_need_refresh": canonical.activities_need_refresh,
        "personal_recovery": personal_recovery(
            [],
            garmin,
            profile,
            today,
            canonical=canonical.recovery,
        ),
        "training_focus": training_focus(
            garmin,
            today,
            str(profile.get("timezone") or "UTC"),
            activities=_activities(canonical),
        ),
    }
    load_projection = garmin_projection.garmin_training_load_projection(
        garmin, today, _garmin_canonical(canonical)
    )
    if load_projection:
        unavailable["garmin_training_load"] = load_projection
    return unavailable


def current_performance_context(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
    *,
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Any]:
    """Compose the current performance projection from explicit inputs.

    The canonical inputs supply activities, wellness, load, body, Garmin and
    athlete-setting values; ``EMPTY_PERFORMANCE_INPUTS`` stands for none. The
    context is unavailable without canonical inputs, and marked
    ``canonical_pending`` while the canonical source serves nothing yet. The
    stored snapshot, which may be None, remains only the source of the
    pre-sleep-period timing fallback.
    """
    if canonical.pending:
        return _pending_context(profile, today)
    if canonical is EMPTY_PERFORMANCE_INPUTS:
        return _unavailable_context(garmin, profile, today, canonical)

    activities = _activities(canonical)
    days = canonical.wellness_days or ()
    latest_wellness = latest(days)

    recovery = performance_recovery_context.performance_recovery_context(
        canonical.recovery, today
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

    current = canonical.current
    metrics = performance_current_metrics.current_performance_metrics(
        profile,
        performance_garmin_metrics.garmin_performance_metrics(
            garmin, today, _garmin_canonical(canonical)
        ),
        canonical=current,
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
            health_by_date=canonical.daily_health or {},
        )
    )
    comparisons = performance_comparisons.performance_comparisons(
        metrics,
        recovery,
        load_context,
        days,
        activities,
        today,
        # The weight trend uses the body history's per-day Garmin weights.
        garmin_history={
            **_garmin_canonical(canonical).performance_history,
            "weight_kg": canonical.body.garmin_weight_kg,
        },
        **_canonical_day_series(canonical),
    )
    activity_performance = activity_validation.activity_performance_validation(
        activities, metrics, comparisons
    )
    return {
        "available": True,
        "personal_recovery": personal_recovery(
            _sleep_timing_rows(snapshot),
            garmin,
            profile,
            today,
            canonical=canonical.recovery,
        ),
        "garmin_training_load": garmin_projection.garmin_training_load_projection(
            garmin, today, _garmin_canonical(canonical)
        ),
        "training_focus": training_focus(
            garmin,
            today,
            str(profile.get("timezone") or "UTC"),
            activities=_activities(canonical),
        ),
        "source": INTERVALS_SNAPSHOT_SOURCE
        if canonical.current.synced_at is not None
        else STORED_PROVIDERS_SOURCE,
        "as_of": _as_of(canonical),
        "activities_need_refresh": canonical.activities_need_refresh,
        "metrics": metrics,
        "thresholds": {
            "ftp_w": metrics["cycling_ftp_watts"]["value"],
            **performance_current_metrics.athlete_thresholds(current),
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
            or _day_id(latest_wellness),
            "resting_hr_bpm": resting_hr,
            "resting_hr_bpm_source": resting_hr_source,
            "hrv_ms": hrv,
            "hrv_ms_source": hrv_source,
            "sleep_score": sleep_score,
            "sleep_score_source": sleep_score_source,
            **_subjective_ratings(latest_wellness),
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
