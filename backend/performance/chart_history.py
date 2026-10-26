"""Bounded, content-free historical series for the public analysis view."""

from datetime import date, timedelta
from typing import Any, Final

from backend.athlete.local_date import LocalDate
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import activity_validation, body, eftp, garmin_metric_history
from backend.performance.canonical_body import CanonicalBodyInputs
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.display_sources import preferred_providers
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.performance.garmin_load import acute_load_value
from backend.providers import garmin_performance_fields as garmin_perf_fields

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


def _garmin_day(row: dict[str, Any]) -> date | None:
    for field in garmin_perf_fields.RECORD_DATE_KEYS:
        if (day := _day(row.get(field))) is not None:
            return day
    return None


def _activity_history_rows(
    raw: dict[str, Any],
    snapshot: dict[str, Any],
    canonical: CanonicalPerformanceInputs | None,
) -> list[dict[str, Any]]:
    """Raw activity rows: the canonical reader's, or the snapshot's sections."""
    if canonical is not None and canonical.activity_rows is not None:
        return list(canonical.activity_rows)
    return _rows(raw.get("activities")) + _rows(snapshot.get("recent_activities"))


def _wellness_history(
    raw: dict[str, Any],
    snapshot: dict[str, Any],
    start: date,
    today: date,
    canonical: CanonicalPerformanceInputs | None = None,
) -> dict[date, dict[str, Any]]:
    if canonical is not None and canonical.history_wellness_rows is not None:
        rows = list(canonical.history_wellness_rows)
    else:
        rows = _rows(raw.get("wellness")) + _rows(snapshot.get("recent_wellness"))
    return {
        day: row
        for row in rows
        if (day := _day(row.get("id") or row.get("date"))) is not None
        and start <= day <= today
    }


def _load_history(
    dates: list[str],
    garmin: dict[str, Any],
    canonical: GarminCanonicalMetrics | None = None,
) -> list[dict[str, Any]]:
    """Garmin's acute load per day: canonical ACUTE_LOAD, else the snapshot rows."""
    if canonical is not None:
        acute = canonical.daily_history.get(MetricKind.ACUTE_LOAD, {})
        values = {day.isoformat(): _number(value) for day, value in acute.items()}
        return [{"date": day, "value": values.get(day)} for day in dates]
    observations = {
        day.isoformat(): acute_load_value(row)
        for row in _rows(garmin.get("training_status"))
        if (day := _garmin_day(row)) is not None
    }
    return [{"date": day, "value": observations.get(day)} for day in dates]


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
    key: str,
    garmin: dict[str, Any],
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics | None = None,
) -> dict[str, float]:
    """Garmin's daily values of one metric: canonical history, else the snapshot's
    accumulated performance history and FTP history."""
    if canonical is not None:
        return {
            day.isoformat(): value
            for day, value in canonical.performance_history.get(key, {}).items()
            if start <= day <= today
            and activity_validation.bounded_performance_metric(key, value) is not None
        }
    observations = {}
    for row in _rows(garmin.get("performance_history")):
        day = _day(row.get("date"))
        metrics = row.get("metrics")
        if day is None or not start <= day <= today or not isinstance(metrics, dict):
            continue
        value = activity_validation.bounded_performance_metric(key, metrics.get(key))
        if value is not None:
            observations[day.isoformat()] = value
    if key == "cycling_ftp_watts":
        observations.update(
            {
                row["date"]: row["value"]
                for row in garmin_metric_history.ftp_points(
                    garmin.get("cycling_ftp_history"), start=start, end=today
                )
            }
        )
    return observations


def _metric_series(
    key: str,
    activities: list[dict[str, Any]],
    garmin: dict[str, Any],
    wellness: dict[date, dict[str, Any]],
    dates: list[str],
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics | None = None,
) -> list[dict[str, Any]]:
    if key == "cycling_eftp_watts":
        source = INTERVALS_SOURCE
        provider = ProviderId.INTERVALS
        observations = eftp.eftp_daily_values(
            list(wellness.values()),
            activities,
            start,
            today,
        )
    else:
        source = "Garmin Connect"
        provider = ProviderId.GARMIN
        observations = _garmin_values(key, garmin, start, today, canonical)
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
    canonical_body: CanonicalBodyInputs | None = None,
    canonical: CanonicalPerformanceInputs | None = None,
) -> dict[str, Any]:
    """Use dated provider history, never backfill today's settings into the past.

    ``canonical`` supplies the activity and wellness rows read through the canonical
    ports; without them the snapshot sections are read.
    """
    snapshot = snapshot or {}
    start = today - timedelta(days=89)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(90)]
    load_end = today
    load_start = load_end - timedelta(days=89)
    load_dates = [(load_start + timedelta(days=i)).isoformat() for i in range(90)]
    raw = snapshot.get("raw_provider_data")
    raw = raw if isinstance(raw, dict) else {}
    # Raw provider rows retain the history that the compact Coach projection trims.
    wellness = _wellness_history(raw, snapshot, load_start, today, canonical)
    activities = _activity_history_rows(raw, snapshot, canonical)
    garmin_canonical = None if canonical is None else canonical.garmin
    load = _load_history(load_dates, garmin, garmin_canonical)
    series = {
        key: _metric_series(
            key, activities, garmin, wellness, dates, start, today, garmin_canonical
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
            canonical=canonical_body,
            wellness_rows=None
            if canonical is None
            else canonical.history_wellness_rows,
            activity_rows=None if canonical is None else canonical.activity_rows,
            garmin_ftp=None
            if garmin_canonical is None
            else garmin_canonical.performance_history.get("cycling_ftp_watts", {}),
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
        "provider_metrics": _provider_metrics(garmin, start, today, garmin_canonical),
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
    group map wins over the overall score in the snapshot reader. A cached chart
    keeps its status, as the snapshot path does, and takes the sync time.
    """
    cached = garmin.get("provider_metrics") or {}
    cached = cached if isinstance(cached, dict) else {}
    metrics = dict(cached)
    for key, (aggregation, fields) in _CANONICAL_PROVIDER_METRICS.items():
        data = _canonical_metric(
            key,
            aggregation,
            _canonical_values_by_day(fields, canonical, start, today),
            garmin.get("synced_at"),
        )
        if data["points"] or (not cached and key not in metrics):
            previous = metrics.get(key, {})
            metrics[key] = {
                **previous,
                **data,
                "status": previous.get("status", data["status"]),
            }
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


def _provider_metrics(
    garmin: dict[str, Any],
    start: date,
    today: date,
    canonical: GarminCanonicalMetrics | None = None,
) -> dict[str, Any]:
    if canonical is not None:
        return _canonical_provider_metrics(garmin, start, today, canonical)
    cached = garmin.get("provider_metrics") or {}
    metrics = dict(cached) if isinstance(cached, dict) else {}
    for key, aggregation in (
        ("endurance_score", "daily"),
        ("running_tolerance", "daily"),
        ("training_readiness_history", "daily"),
        ("weekly_training_status", "weekly"),
    ):
        data = garmin_metric_history.projected_metric(
            garmin.get(key),
            start=start,
            end=today,
            aggregation=aggregation,
            metric=key,
            synced_at=garmin.get("synced_at"),
        )
        if data["points"] or (not cached and key not in metrics):
            previous = metrics.get(key, {})
            metrics[key] = {
                **previous,
                **data,
                "status": previous.get("status", data["status"]),
            }
    return metrics
