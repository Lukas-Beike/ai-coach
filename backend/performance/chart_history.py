"""Bounded, content-free historical series for the public analysis view."""

from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import LocalDate
from backend.canonical.vocabulary import ProviderId
from backend.performance import activity_validation, body, eftp, garmin_metric_history
from backend.performance.canonical_body import CanonicalBodyInputs
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.display_sources import preferred_providers
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


def _load_history(dates: list[str], garmin: dict[str, Any]) -> list[dict[str, Any]]:
    # Remaining snapshot read: Garmin training status (acute load) has no metric kind.
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
    key: str, garmin: dict[str, Any], start: date, today: date
) -> dict[str, float]:
    # Remaining snapshot read: the performance history and the FTP history are
    # accumulated across syncs and have no observation series with equal history.
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
        observations = _garmin_values(key, garmin, start, today)
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
    load = _load_history(load_dates, garmin)
    series = {
        key: _metric_series(key, activities, garmin, wellness, dates, start, today)
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
        "provider_metrics": _provider_metrics(garmin, start, today),
        "metrics": series,
        "preferred_providers": preferred_providers(),
    }


def _provider_metrics(
    garmin: dict[str, Any], start: date, today: date
) -> dict[str, Any]:
    # Remaining snapshot read: ENDURANCE_SCORE carries only the overall score, not
    # the scalar fields and weekly records shown here; running tolerance has no kind.
    cached = garmin.get("provider_metrics") or {}
    metrics = dict(cached) if isinstance(cached, dict) else {}
    for key, aggregation in (
        ("endurance_score", "weekly"),
        ("running_tolerance", "weekly"),
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
