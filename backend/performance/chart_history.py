"""Bounded, content-free historical series for the public analysis view."""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Final

from backend.athlete.local_date import LocalDate
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import activity_validation, body, eftp, garmin_metric_history
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.display_sources import preferred_providers
from backend.performance.garmin_canonical import GarminCanonicalMetrics

INTERVALS_SOURCE = "Intervals.icu"

METRIC_KEYS = (
    "cycling_ftp_watts",
    "cycling_eftp_watts",
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


def _rows(value: Any) -> list[dict[str, Any]]:
    return (
        [row for row in value if isinstance(row, dict)]
        if isinstance(value, list)
        else []
    )


def _load_history(
    dates: list[str], canonical: GarminCanonicalMetrics
) -> list[dict[str, Any]]:
    """Garmin's acute load per day from the canonical ACUTE_LOAD history."""
    acute = canonical.daily_history.get(MetricKind.ACUTE_LOAD, {})
    values = {day.isoformat(): _number(value) for day, value in acute.items()}
    return [{"date": day, "value": values.get(day)} for day in dates]


def _training_time_history(
    rows: list[dict[str, Any]], dates: list[str]
) -> list[dict[str, Any]]:
    """Daily moving time in hours; each activity counts once, unknown stays a gap."""
    seconds: dict[str, float] = {}
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("id") or "")
        day = _day(row.get("start_date_local"))
        value = row.get("moving_time")
        if (
            day is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 < value <= 86400
            or (key and key in seen)
        ):
            continue
        if key:
            seen.add(key)
        seconds[day.isoformat()] = seconds.get(day.isoformat(), 0) + float(value)
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
    activities: list[dict[str, Any]],
    eftp_by_day: Mapping[date, float] | None,
    dates: list[str],
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics,
) -> list[dict[str, Any]]:
    if key == "cycling_eftp_watts":
        source = INTERVALS_SOURCE
        provider = ProviderId.INTERVALS
        observations = eftp.eftp_daily_values(
            eftp_by_day,
            activities,
            start,
            today,
        )
    else:
        source = "Garmin Connect"
        provider = ProviderId.GARMIN
        observations = _garmin_values(key, start, today, canonical)
    return [
        {
            "source": source,
            "source_provider": provider.value,
            "points": [{"date": day, "value": observations.get(day)} for day in dates],
        }
    ]


def analysis_history(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any],
    today: date,
    *,
    canonical: CanonicalPerformanceInputs,
) -> dict[str, Any]:
    """Use dated provider history, never backfill today's settings into the past.

    ``canonical`` supplies the activity rows, wellness days and Garmin history read
    through the canonical ports. The snapshot supplies sync times and the power
    curve, which has no metric kind yet.
    """
    snapshot = snapshot or {}
    start = today - timedelta(days=89)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(90)]
    load_end = today
    load_start = load_end - timedelta(days=89)
    load_dates = [(load_start + timedelta(days=i)).isoformat() for i in range(90)]
    eftp_by_day = canonical.eftp_by_day
    activities = list(canonical.activity_rows or ())
    garmin_canonical = canonical.garmin or GarminCanonicalMetrics()
    load = _load_history(load_dates, garmin_canonical)
    series = {
        key: _metric_series(
            key, activities, eftp_by_day, dates, start, today, garmin_canonical
        )
        for key in METRIC_KEYS
    }
    return {
        "start": dates[0],
        "end": dates[-1],
        "days": 90,
        "load": {
            "source": "Garmin Connect",
            "start": load_dates[0],
            "end": load_dates[-1],
            "points": load,
        },
        "training_time": {
            "source": INTERVALS_SOURCE,
            "start": load_dates[0],
            "end": load_dates[-1],
            "points": _training_time_history(activities, load_dates),
        },
        # PublicPerformanceStateService exposes this as performance.history.body;
        # the UI can render it in the separate Body tab without another request.
        "body": body.body_history(
            snapshot,
            garmin,
            today,
            canonical=canonical.body,
            wellness_days=canonical.history_wellness_days or (),
            activity_rows=activities,
            garmin_ftp=garmin_canonical.performance_history.get(
                "cycling_ftp_watts", {}
            ),
            eftp_by_day=eftp_by_day,
        ),
        # Remaining snapshot read: the power curve has no metric kind.
        "cycling_power_profile": {
            **(snapshot.get("cycling_power_profile") or {}),
            "points": [
                point
                for point in _rows(
                    (snapshot.get("cycling_power_profile") or {}).get("points")
                )
                if (day := _day(point.get("date"))) is not None
                and start <= day <= today
            ],
        },
        "provider_metrics": _canonical_provider_metrics(
            garmin, start, today, garmin_canonical
        ),
        "metrics": series,
        "preferred_providers": preferred_providers(),
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


def _canonical_provider_metrics(
    garmin: dict[str, Any],
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics,
) -> dict[str, Any]:
    """Build the provider charts from the canonical Garmin history.

    A day with an endurance group value shows the group values only, as the
    group map wins over the overall score in the snapshot reader. The points come
    only from canonical data; a cached chart supplies its sync status only.
    """
    cached = garmin.get("provider_metrics")
    cached = cached if isinstance(cached, dict) else {}
    metrics: dict[str, Any] = {}
    for key, (aggregation, fields) in _CANONICAL_PROVIDER_METRICS.items():
        data = _canonical_metric(
            key,
            aggregation,
            _canonical_values_by_day(fields, canonical, start, today),
            garmin.get("synced_at"),
        )
        previous = cached.get(key)
        status = previous.get("status") if isinstance(previous, dict) else None
        metrics[key] = {**data, "status": status or data["status"]}
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
            "source": garmin_metric_history.GARMIN_SOURCE,
        }
        if key in ("training_readiness_history", "weekly_training_status"):
            point["value"] = next(iter(values.values()))
        points.append(point)
    return {
        "status": "current" if points else "unavailable",
        "aggregation": aggregation,
        "source": garmin_metric_history.GARMIN_SOURCE,
        "unit": "unknown",
        "points": points,
        "observed_at": points[-1]["date"] if points else None,
        "fetched_at": fetched_at,
        "metric": key,
    }


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value
