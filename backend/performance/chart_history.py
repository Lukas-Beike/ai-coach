"""Bounded, content-free historical series for the public analysis view."""

from datetime import date, timedelta
from typing import Any

from backend.performance import activity_validation, eftp

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
    wellness = {
        day: row
        for row in _rows(raw.get("wellness")) + _rows(snapshot.get("recent_wellness"))
        if (day := _day(row.get("id") or row.get("date"))) is not None
        and start <= day <= today
    }
    load = []
    for date_key in dates:
        row = wellness.get(date.fromisoformat(date_key), {})
        # Today's provider load can include planned workouts. A retrospective ends
        # yesterday; preserve the null point rather than presenting a forecast as actual.
        if date_key == today.isoformat():
            row = {}
        values = {}
        for key, aliases in (("ctl", ("ctl", "ctLoad")), ("atl", ("atl", "atlLoad"))):
            value = next((row[k] for k in aliases if row.get(k) is not None), None)
            values[key] = activity_validation.bounded_activity_metric(value, 0, 10000)
        values["tsb"] = (
            round(values["ctl"] - values["atl"], 2)
            if values["ctl"] is not None and values["atl"] is not None
            else None
        )
        load.append({"date": date_key, **values})

    series: dict[str, list[dict[str, Any]]] = {key: [] for key in METRIC_KEYS}
    for key in METRIC_KEYS:
        for source in (
            ("Intervals.icu",) if key == "cycling_eftp_watts" else ("Garmin Connect",)
        ):
            observations = {}
            if source == "Intervals.icu":
                observations = eftp.eftp_daily_values(
                    list(wellness.values()),
                    _rows(raw.get("activities"))
                    + _rows(snapshot.get("recent_activities")),
                    start,
                    today,
                )
            else:
                for row in _rows(garmin.get("performance_history")):
                    day = _day(row.get("date"))
                    metrics = row.get("metrics")
                    if (
                        day is None
                        or not start <= day <= today
                        or not isinstance(metrics, dict)
                    ):
                        continue
                    value = activity_validation.bounded_performance_metric(
                        key, metrics.get(key)
                    )
                    if value is not None:
                        observations[day.isoformat()] = value
            series[key].append(
                {
                    "source": source,
                    "points": [
                        {"date": day, "value": observations.get(day)} for day in dates
                    ],
                }
            )
    return {
        "start": dates[0],
        "end": dates[-1],
        "days": 90,
        "load": {"source": "Intervals.icu", "points": load},
        "metrics": series,
    }
