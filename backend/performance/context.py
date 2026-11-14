"""Compose the current performance context from canonical daily wellness values."""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.activities.zone_settings import effective_zone_configuration, zone_two_top
from backend.canonical.activity_summary import summary_local_date
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.first_threshold import (
    FIRST_THRESHOLD_FIELD,
    first_threshold_estimated,
    first_threshold_origin,
    first_threshold_percent,
)
from backend.canonical.vocabulary import Sport, ZoneConfigurationMetric
from backend.errors import DatabaseBusyError
from backend.performance import activity_validation, garmin_projection
from backend.performance import comparisons as performance_comparisons
from backend.performance import current_metrics as performance_current_metrics
from backend.performance import daily_health as performance_daily_health
from backend.performance import freshness as performance_freshness
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import load as performance_load
from backend.performance import load_context as performance_load_context
from backend.performance import recovery_context as performance_recovery_context
from backend.performance.canonical_current import NO_CURRENT_INPUTS
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
)
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS, GarminSyncStatus
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.performance.pace_at_hr import LT1_DAYS, output_at_heart_rate
from backend.performance.personal_recovery import personal_recovery
from backend.performance.session_rpe_load import FeedbackLookup, feedback_by_session
from backend.performance.training_focus import training_focus

# The reason an unavailable context gives while the canonical source serves nothing yet.
REASON_CANONICAL_PENDING: Final = "canonical_pending"
PENDING_STATUS: Final = "Daten werden vorbereitet"
# The source of a context built from the stored provider values.
STORED_PROVIDERS_SOURCE: Final = "Gespeicherte Provider-Daten"

# Recovery sources whose freshness comes from the Garmin view, including the
# labelled weekly HRV fallback.
_GARMIN_RECOVERY_SOURCES = frozenset(
    {
        performance_garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
        performance_recovery_context.GARMIN_WEEKLY_HRV_SOURCE,
    }
)


# The oldest rollup window ends 30 days ago and spans 30 days.
_ROLLUP_LOOKBACK_DAYS: Final = 60


def _recent(activities: list[Any], cutoff: date) -> list[Any]:
    """Summaries on or after ``cutoff``, whose feedback the load rollups read."""
    return [
        activity
        for activity in activities
        if isinstance(activity, dict)
        and summary_local_date(activity) >= cutoff.isoformat()
    ]


def _activities(canonical: CanonicalPerformanceInputs) -> list[Any]:
    """Return the canonical activity summaries; none when none were read."""
    return list(canonical.activities or ())


def _garmin_canonical(canonical: CanonicalPerformanceInputs) -> GarminCanonicalMetrics:
    """The canonical Garmin values; empty when none were read."""
    return canonical.garmin or GarminCanonicalMetrics()


def _has_provider_values(canonical: CanonicalPerformanceInputs) -> bool:
    """Return True when the canonical inputs carry a value some provider synced."""
    recovery = canonical.recovery
    return bool(
        canonical.activities
        or canonical.daily_health
        or canonical.current != NO_CURRENT_INPUTS
        or (recovery is not None and any(recovery.observations.values()))
        or _garmin_canonical(canonical) != GarminCanonicalMetrics()
        or canonical.body.garmin_weight_kg
        or canonical.body.garmin_body_fat_pct
    )


def _sync_status(canonical: CanonicalPerformanceInputs) -> dict[str, Any]:
    """The source label and the activity sync time of the stored provider data."""
    return {"source": STORED_PROVIDERS_SOURCE, "as_of": canonical.activities_synced_at}


def _pending_context(
    profile: dict[str, Any], today: date, *, failed: bool = False
) -> dict[str, Any]:
    """The context while the canonical source serves nothing yet: no values at all."""
    return {
        **_unavailable_context(
            NO_GARMIN_SYNC_STATUS, profile, today, EMPTY_PERFORMANCE_INPUTS
        ),
        "reason": REASON_CANONICAL_PENDING,
        "status": "Datenvorbereitung fehlgeschlagen; erneuter Versuch folgt"
        if failed
        else PENDING_STATUS,
    }


def _unavailable_context(
    garmin: GarminSyncStatus,
    profile: dict[str, Any],
    today: date,
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Any]:
    """Projection without canonical inputs: Garmin-only recovery and load."""
    unavailable = {
        "available": False,
        "source": STORED_PROVIDERS_SOURCE,
        "as_of": None,
        "metrics": {},
        "personal_recovery": personal_recovery(
            profile, today, canonical=canonical.recovery
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


def _zone_two_tops(
    configurations: list[ZoneConfiguration],
    metrics: dict[str, Any],
    today: date,
) -> dict[str, float]:
    """The top of zone 2 of the heart-rate, run pace and ride power zones, where set."""
    pace = performance_current_metrics.as_number(
        metrics["run_threshold_pace_seconds_per_km"]["value"]
    )
    tops: dict[str, float] = {}
    for key, metric, sport in (
        ("run_pace", ZoneConfigurationMetric.PACE, Sport.RUN),
        ("ride_power", ZoneConfigurationMetric.POWER, Sport.RIDE),
        ("run_hr", ZoneConfigurationMetric.HEART_RATE, Sport.RUN),
        ("ride_hr", ZoneConfigurationMetric.HEART_RATE, Sport.RIDE),
    ):
        chosen = effective_zone_configuration(configurations, metric, sport, day=today)
        top = zone_two_top(chosen, pace) if chosen is not None else None
        if top is not None and top > 0:
            tops[key] = top
    return tops


def _at_heart_rate(
    records: Callable[[int], Sequence[Mapping[str, Any]]] | None, today: date
) -> performance_current_metrics.OutputAtHeartRate | None:
    """Pace or power at a heart rate from the session records, read at most once.

    A busy database or a missing session source reads as no sessions, so LT1
    falls back to zone 2 or the fixed share instead of failing the projection.
    """
    if records is None:
        return None

    @functools.cache
    def read() -> Sequence[Mapping[str, Any]]:
        try:
            return records(LT1_DAYS)
        except DatabaseBusyError, RuntimeError:
            return ()

    return lambda sport, bpm: output_at_heart_rate(read(), sport, bpm, today)


# The threshold charts' twelve calendar weeks (#2693).
LT1_HISTORY_WEEKS: Final = 12
# Garmin's dated thresholds that decide a past week's LT1.
_LT1_HISTORY_KEYS: Final = (
    "run_threshold_hr_bpm",
    "bike_threshold_hr_bpm",
    "run_threshold_pace_seconds_per_km",
    "cycling_ftp_watts",
)
# The LT1 value of each sport and the key of its origin.
_LT1_MAIN: Final = {
    "run": ("pace_seconds_per_km", "pace_origin"),
    "ride": ("watts", "power_origin"),
}


def _dated_metrics(
    history: Mapping[str, Mapping[date, float]], day: date
) -> dict[str, dict[str, Any]]:
    """Garmin's last dated value of each LT1 input on or before ``day``."""
    metrics: dict[str, dict[str, Any]] = {}
    for key in _LT1_HISTORY_KEYS:
        dated = [item for item in (history.get(key) or {}).items() if item[0] <= day]
        metrics[key] = {"value": max(dated)[1] if dated else None}
    return metrics


def first_threshold_history(
    current: Mapping[str, Mapping[str, Any]],
    profile: Mapping[str, Any],
    today: date,
    *,
    garmin_history: Mapping[str, Mapping[date, float]],
    zone_configurations: Iterable[ZoneConfiguration],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """LT1 per sport at the end of each of the last twelve calendar weeks (#2693).

    The running week's point is today's LT1 (``current``, fallbacks and origins
    included). A past week uses the same rule with the thresholds and zones in
    effect then (Garmin's dated values, the zones valid that day), the stored
    LT1 share for every week, and the sessions up to that day; a week whose LT1
    does not come from at least three own sessions is a gap (athlete decisions,
    2026-11-14). Each point keeps its heart rate and both origins.
    """
    configurations = list(zone_configurations)
    first = today - timedelta(days=7 * LT1_HISTORY_WEEKS + LT1_DAYS)
    # Only sessions the chart's weeks can use; the rule narrows each week further.
    records = [
        row for row in records if str(row.get("date") or "") >= first.isoformat()
    ]
    pct = first_threshold_percent(profile.get(FIRST_THRESHOLD_FIELD))
    origin = first_threshold_origin(profile)
    monday = today - timedelta(days=today.weekday())
    ends = [
        monday + timedelta(days=6 - 7 * weeks)
        for weeks in range(LT1_HISTORY_WEEKS - 1, 0, -1)
    ]
    result: dict[str, list[dict[str, Any]]] = {"run": [], "ride": []}
    for day in ends:
        metrics = _dated_metrics(garmin_history, day)
        values = performance_current_metrics.first_thresholds(
            metrics,
            pct,
            origin,
            _zone_two_tops(configurations, metrics, day),
            functools.partial(output_at_heart_rate, records, today=day),
        )
        for sport, (key, origin_key) in _LT1_MAIN.items():
            own = values.get(sport, {})
            measured = (
                own.get(origin_key) == performance_current_metrics.LT1_OWN_SESSIONS
            )
            result[sport].append(
                _lt1_point(day, own if measured else {}, key, origin_key)
            )
    for sport, (key, origin_key) in _LT1_MAIN.items():
        result[sport].append(_lt1_point(today, current.get(sport, {}), key, origin_key))
    return result


def _lt1_point(
    day: date, values: Mapping[str, Any], key: str, origin_key: str
) -> dict[str, Any]:
    """One chart point; without a value it is a gap with no heart rate."""
    value = values.get(key)
    return {
        "date": day.isoformat(),
        "value": value,
        "origin": values.get(origin_key) if value is not None else None,
        "hr_bpm": values.get("hr_bpm") if value is not None else None,
        "hr_origin": values.get("hr_origin") if value is not None else None,
    }


def current_performance_context(
    garmin: GarminSyncStatus,
    profile: dict[str, Any],
    today: date,
    *,
    canonical: CanonicalPerformanceInputs,
    session_feedback: FeedbackLookup | None = None,
    zone_configurations: Iterable[ZoneConfiguration] = (),
    lt1_session_records: Callable[[int], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Compose the current performance projection from canonical inputs only.

    ``zone_configurations`` give LT1 the top of zone 2 of the sport's heart-rate,
    pace or power zones in effect. ``lt1_session_records(days)`` reads the ride
    and run sessions of the last days with their heart-rate profiles, so LT1 pace and power come from the
    athlete's own steady sessions at the LT1 heart rate; read once, when needed.

    ``session_feedback`` reads the local session feedback, so load rollups can
    report the session-RPE load of sessions without a TSS-scale load.

    The canonical inputs supply activities, load, body, Garmin and
    athlete-setting values and the activity sync time;
    ``EMPTY_PERFORMANCE_INPUTS`` stands for none. ``garmin`` is the Garmin sync
    status and supplies only freshness. The context is unavailable without any
    provider value in the canonical inputs, also when only the athlete's own
    profile holds values, and marked ``canonical_pending`` while the canonical
    source serves nothing yet.
    """
    if canonical.pending:
        return _pending_context(profile, today, failed=canonical.backfill_failed)
    if canonical is EMPTY_PERFORMANCE_INPUTS or not _has_provider_values(canonical):
        return _unavailable_context(garmin, profile, today, canonical)

    activities = _activities(canonical)

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
        garmin_thresholds=_garmin_canonical(canonical).thresholds,
        garmin_body=_garmin_canonical(canonical).body,
        as_of=today,
    )
    feedback = feedback_by_session(
        _recent(activities, today - timedelta(days=_ROLLUP_LOOKBACK_DAYS)),
        session_feedback,
    )
    load_context = performance_load_context.performance_load_context(
        activities,
        today,
        canonical=canonical,
        timezone=str(profile.get("timezone") or "UTC"),
        session_feedback=feedback,
    )
    load = load_context["load"]
    last_7 = load_context["last_7"]
    previous_7 = load_context["previous_7"]
    last_30 = load_context["last_30"]
    previous_30 = load_context["previous_30"]

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
        today,
        # The weight trend uses the body history's per-day Garmin weights.
        garmin_history={
            **_garmin_canonical(canonical).performance_history,
            "weight_kg": canonical.body.garmin_weight_kg,
        },
    )
    activity_performance = activity_validation.activity_performance_validation(
        activities, metrics, comparisons
    )
    return {
        "available": True,
        "personal_recovery": personal_recovery(
            profile, today, canonical=canonical.recovery
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
        **_sync_status(canonical),
        "metrics": metrics,
        "thresholds": {
            **performance_current_metrics.coach_thresholds(
                metrics,
                first_threshold_percent(profile.get(FIRST_THRESHOLD_FIELD)),
                first_threshold_estimated(profile),
            ),
            "weight": metrics["weight_kg"]["value"],
            "first_thresholds": performance_current_metrics.first_thresholds(
                metrics,
                first_threshold_percent(profile.get(FIRST_THRESHOLD_FIELD)),
                first_threshold_origin(profile),
                _zone_two_tops(list(zone_configurations), metrics, today),
                _at_heart_rate(lt1_session_records, today),
            ),
        },
        "current_load": load,
        "recovery": {
            "id": recovery["sleep_date"]
            or recovery["resting_hr_date"]
            or recovery["hrv_date"],
            "resting_hr_bpm": resting_hr,
            "resting_hr_bpm_source": resting_hr_source,
            "hrv_ms": hrv,
            "hrv_ms_source": hrv_source,
            "sleep_score": sleep_score,
            "sleep_score_source": sleep_score_source,
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
            "last_28_days": performance_load.activity_rollup(
                activities, 28, today, session_feedback=feedback
            ),
        },
        "comparisons": comparisons,
        "activity_validation": activity_performance,
    }
