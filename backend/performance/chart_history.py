"""Bounded, content-free historical series for the public analysis view."""

from datetime import date, timedelta
from typing import Any

from backend.performance import activity_validation, eftp

INTERVALS_SOURCE = "Intervals.icu"

METRIC_KEYS = (
    "cycling_ftp_watts",
    "cycling_eftp_watts",
    "run_threshold_pace_seconds_per_km",
    "cycling_vo2max_ml_kg_min",
    "running_vo2max_ml_kg_min",
)


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _rows(value: Any) -> list[dict[str, Any]]:
    return (
        [row for row in value if isinstance(row, dict)]
        if isinstance(value, list)
        else []
    )


def _wellness_history(
    raw: dict[str, Any], snapshot: dict[str, Any], start: date, today: date
) -> dict[date, dict[str, Any]]:
    return {
        day: row
        for row in _rows(raw.get("wellness")) + _rows(snapshot.get("recent_wellness"))
        if (day := _day(row.get("id") or row.get("date"))) is not None
        and start <= day <= today
    }


def _load_values(row: dict[str, Any]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for key, aliases in (("ctl", ("ctl", "ctLoad")), ("atl", ("atl", "atlLoad"))):
        value = next((row[name] for name in aliases if row.get(name) is not None), None)
        values[key] = activity_validation.bounded_activity_metric(value, 0, 10000)
    ctl, atl = values["ctl"], values["atl"]
    values["tsb"] = round(ctl - atl, 2) if ctl is not None and atl is not None else None
    return values


def _load_history(
    dates: list[str], wellness: dict[date, dict[str, Any]], today: date
) -> list[dict[str, Any]]:
    today_key = today.isoformat()
    load = []
    for date_key in dates:
        row = wellness.get(date.fromisoformat(date_key), {})
        # Today's provider load can include planned workouts, so end at yesterday.
        if date_key == today_key:
            row = {}
        load.append({"date": date_key, **_load_values(row)})
    return load


def _garmin_values(
    key: str, garmin: dict[str, Any], start: date, today: date
) -> dict[str, float]:
    observations = {}
    for row in _rows(garmin.get("performance_history")):
        day = _day(row.get("date"))
        metrics = row.get("metrics")
        if day is None or not start <= day <= today or not isinstance(metrics, dict):
            continue
        value = activity_validation.bounded_performance_metric(key, metrics.get(key))
        if value is not None:
            observations[day.isoformat()] = value
    return observations


def _metric_series(
    key: str,
    raw: dict[str, Any],
    snapshot: dict[str, Any],
    garmin: dict[str, Any],
    wellness: dict[date, dict[str, Any]],
    dates: list[str],
    start: date,
    today: date,
) -> list[dict[str, Any]]:
    if key == "cycling_eftp_watts":
        source = INTERVALS_SOURCE
        observations = eftp.eftp_daily_values(
            list(wellness.values()),
            _rows(raw.get("activities")) + _rows(snapshot.get("recent_activities")),
            start,
            today,
        )
    else:
        source = "Garmin Connect"
        observations = _garmin_values(key, garmin, start, today)
    return [
        {
            "source": source,
            "points": [{"date": day, "value": observations.get(day)} for day in dates],
        }
    ]


def analysis_history(
    snapshot: dict[str, Any] | None, garmin: dict[str, Any], today: date
) -> dict[str, Any]:
    """Use dated provider history, never backfill today's settings into the past."""
    snapshot = snapshot or {}
    start = today - timedelta(days=89)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(90)]
    raw = snapshot.get("raw_provider_data")
    raw = raw if isinstance(raw, dict) else {}
    # Raw provider rows retain the history that the compact Coach projection trims.
    wellness = _wellness_history(raw, snapshot, start, today)
    load = _load_history(dates, wellness, today)
    series = {
        key: _metric_series(key, raw, snapshot, garmin, wellness, dates, start, today)
        for key in METRIC_KEYS
    }
    return {
        "start": dates[0],
        "end": dates[-1],
        "days": 90,
        "load": {"source": INTERVALS_SOURCE, "points": load},
        "metrics": series,
    }
