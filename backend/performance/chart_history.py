"""Bounded, content-free historical series for the public analysis view."""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.activities.activity_summary import summary_duration_s
from backend.athlete.local_date import LocalDate
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import activity_validation, body
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.display_sources import preferred_providers
from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.providers.garmin_health_mapping import GARMIN_LABEL
from backend.providers.source_labels import SESSION_SOURCES_LABEL

METRIC_KEYS = (
    "cycling_ftp_watts",
    "run_threshold_pace_seconds_per_km",
    "cycling_vo2max_ml_kg_min",
    "running_vo2max_ml_kg_min",
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)


def _day(value: Any) -> date | None:
    try:
        return LocalDate.parse(value).to_date()
    except ValueError:
        return None


def _load_history(
    dates: list[str], canonical: GarminCanonicalMetrics
) -> list[dict[str, Any]]:
    """Garmin's acute load per day from the canonical ACUTE_LOAD history."""
    acute = canonical.daily_history.get(MetricKind.ACUTE_LOAD, {})
    values = {day.isoformat(): _number(value) for day, value in acute.items()}
    return [{"date": day, "value": values.get(day)} for day in dates]


def _daily_activity_history(
    dates: list[str], canonical: GarminCanonicalMetrics
) -> dict[str, Any]:
    """Garmin's daily steps and floors climbed; a day without a value is a gap."""
    series = {}
    for key, kind in (("steps", MetricKind.STEPS), ("floors", MetricKind.FLOORS)):
        history = canonical.daily_history.get(kind, {})
        values = {day.isoformat(): _number(value) for day, value in history.items()}
        series[key] = [{"date": day, "value": values.get(day)} for day in dates]
    return {
        "source": GARMIN_LABEL,
        "source_provider": ProviderId.GARMIN.value,
        "start": dates[0],
        "end": dates[-1],
        **series,
    }


def _training_time_history(
    summaries: Sequence[Mapping[str, Any]], dates: list[str]
) -> list[dict[str, Any]]:
    """Daily moving time in hours; unknown stays a gap."""
    seconds: dict[str, float] = {}
    for summary in summaries:
        day = _day(summary.get("started_at_local"))
        value = summary_duration_s(summary)
        if day is None or value is None or not 0 < value <= 86400:
            continue
        seconds[day.isoformat()] = seconds.get(day.isoformat(), 0) + value
    return [
        {
            "date": day,
            "value": round(seconds[day] / 3600, 2) if day in seconds else None,
        }
        for day in dates
    ]


def _garmin_values(
    key: str, start: date, today: date, canonical: GarminCanonicalMetrics
) -> dict[str, float]:
    """Garmin's daily values of one metric from the canonical history."""
    return {
        day.isoformat(): value
        for day, value in canonical.performance_history.get(key, {}).items()
        if start <= day <= today
        and activity_validation.bounded_performance_metric(key, value) is not None
    }


def _metric_series(
    key: str,
    dates: list[str],
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics,
) -> list[dict[str, Any]]:
    observations = _garmin_values(key, start, today, canonical)
    return [
        {
            "source": GARMIN_LABEL,
            "source_provider": ProviderId.GARMIN.value,
            "points": [{"date": day, "value": observations.get(day)} for day in dates],
        }
    ]


def analysis_history(
    garmin: GarminSyncStatus,
    today: date,
    *,
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Any]:
    """Use dated provider history, never backfill today's settings into the past.

    ``canonical`` supplies the activity summaries and Garmin
    history read through the canonical ports; ``garmin`` is the Garmin sync
    status.
    """
    start = today - timedelta(days=89)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(90)]
    load_end = today
    load_start = load_end - timedelta(days=89)
    load_dates = [(load_start + timedelta(days=i)).isoformat() for i in range(90)]
    activities = list(canonical.activities or ())
    garmin_canonical = canonical.garmin or GarminCanonicalMetrics()
    load = _load_history(load_dates, garmin_canonical)
    series = {
        key: _metric_series(key, dates, start, today, garmin_canonical)
        for key in METRIC_KEYS
    }
    return {
        "start": dates[0],
        "end": dates[-1],
        "days": 90,
        "load": {
            "source": GARMIN_LABEL,
            "source_provider": ProviderId.GARMIN.value,
            "start": load_dates[0],
            "end": load_dates[-1],
            "points": load,
        },
        "daily_activity": _daily_activity_history(load_dates, garmin_canonical),
        "training_time": {
            "source": SESSION_SOURCES_LABEL,
            "start": load_dates[0],
            "end": load_dates[-1],
            "points": _training_time_history(activities, load_dates),
        },
        # PublicPerformanceStateService exposes this as performance.history.body;
        # the UI can render it in the separate Body tab without another request.
        "body": body.body_history(
            garmin,
            today,
            canonical=canonical.body,
            garmin_ftp=garmin_canonical.performance_history.get(
                "cycling_ftp_watts", {}
            ),
            preferences=canonical.preferences,
        ),
        "provider_metrics": _canonical_provider_metrics(
            garmin, start, today, garmin_canonical
        ),
        "metrics": series,
        "preferred_providers": preferred_providers(canonical.preferences),
    }


# Provider chart -> (aggregation, ((value field, kind), ...)). The point value
# fields are the ones the analysis view reads; readiness and the weekly status
# carry their value in the point itself.
_CANONICAL_PROVIDER_METRICS: Final = {
    "endurance_score": (
        "daily",
        (
            ("groupAverage", MetricKind.ENDURANCE_SCORE_GROUP_AVERAGE),
            ("groupMax", MetricKind.ENDURANCE_SCORE_GROUP_MAX),
            ("overallScore", MetricKind.ENDURANCE_SCORE),
        ),
    ),
    "running_tolerance": (
        "daily",
        (("toleranceScore", MetricKind.RUNNING_TOLERANCE),),
    ),
    "training_readiness_history": ("daily", (("score", MetricKind.READINESS),)),
    "weekly_training_status": (
        "weekly",
        (("dailyTrainingLoadAcute", MetricKind.ACUTE_LOAD),),
    ),
}


# Cached chart states that describe the provider fetch, not the snapshot's points.
_FETCH_OUTCOMES: Final = frozenset({"stale", "failed", "unsupported"})


def _canonical_provider_metrics(
    garmin: GarminSyncStatus,
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics,
) -> dict[str, Any]:
    """Build the provider charts from the canonical Garmin history.

    A day with an endurance group value shows the group values only, as the
    group map wins over the overall score in the snapshot reader. The points come
    only from canonical data. A cached chart supplies its fetch outcome (stale,
    failed or unsupported); otherwise the status follows the canonical points.
    """
    metrics: dict[str, Any] = {}
    for key, (aggregation, fields) in _CANONICAL_PROVIDER_METRICS.items():
        data = _canonical_metric(
            key,
            aggregation,
            _canonical_values_by_day(fields, canonical, start, today),
            garmin.synced_at,
        )
        status = garmin.chart_status.get(key)
        if status not in _FETCH_OUTCOMES:
            status = data["status"]
        metrics[key] = {**data, "status": status}
    return metrics


def _canonical_values_by_day(
    fields: tuple[tuple[str, MetricKind], ...],
    canonical: GarminCanonicalMetrics,
    start: date,
    today: date,
) -> dict[date, dict[str, Any]]:
    by_day: dict[date, dict[str, Any]] = {}
    for name, kind in fields:
        for day, value in canonical.daily_history.get(kind, {}).items():
            if not start <= day <= today:
                continue
            values = by_day.setdefault(day, {})
            if kind is MetricKind.ENDURANCE_SCORE and values:
                continue
            values[name] = _number(value)
    return by_day


def _canonical_metric(
    key: str,
    aggregation: str,
    by_day: dict[date, dict[str, Any]],
    fetched_at: Any,
) -> dict[str, Any]:
    points = []
    for day, values in sorted(by_day.items()):
        point: dict[str, Any] = {
            "date": day.isoformat(),
            "values": values,
            "source": GARMIN_LABEL,
        }
        if key in ("training_readiness_history", "weekly_training_status"):
            point["value"] = next(iter(values.values()))
        points.append(point)
    return {
        "status": "current" if points else "unavailable",
        "aggregation": aggregation,
        "source": GARMIN_LABEL,
        "unit": "unknown",
        "points": points,
        "observed_at": points[-1]["date"] if points else None,
        "fetched_at": fetched_at,
        "metric": key,
    }


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value
