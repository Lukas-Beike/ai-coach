"""Recorded sensor zones and Garmin's activity training-effect categories."""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import summary_duration_s, summary_local_date
from backend.athlete.local_date import iso_date_prefix
from backend.performance import freshness as performance_freshness
from backend.performance.activity_validation import bounded_activity_metric
from backend.providers import garmin_performance_fields as garmin_perf_fields

_CATEGORIES = {
    "RECOVERY": "low_aerobic",
    "AEROBIC_BASE": "low_aerobic",
    "LOW_AEROBIC": "low_aerobic",
    "TEMPO": "high_aerobic",
    "THRESHOLD": "high_aerobic",
    "LACTATE_THRESHOLD": "high_aerobic",
    "VO2_MAX": "high_aerobic",
    "VO2MAX": "high_aerobic",
    "HIGH_AEROBIC": "high_aerobic",
    "ANAEROBIC_CAPACITY": "anaerobic",
    "SPEED": "anaerobic",
    "ANAEROBIC": "anaerobic",
}


_ZONE_SENSORS = (
    ("power_zone_times", "power"),
    ("heart_rate_zone_times", "heart_rate"),
)


def _zone_distribution(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum the recorded power and heart-rate zone seconds per canonical sport."""
    reports = []
    for sport in sorted({str(row.get("sport") or "other") for row in summaries}):
        if sport == "strength":
            continue
        sport_rows = [
            row for row in summaries if (row.get("sport") or "other") == sport
        ]
        duration = sum(summary_duration_s(row) or 0 for row in sport_rows)
        for key, sensor in _ZONE_SENSORS:
            seconds: dict[str, float] = {}
            measured_sessions = 0
            sources: set[str] = set()
            for row in sport_rows:
                valid = _valid_zones(row.get(key))
                if not valid:
                    continue
                measured_sessions += 1
                label = (row.get("sources") or {}).get(key)
                if label:
                    sources.add(str(label))
                for zone in valid:
                    zone_id = str(zone["id"])[:20]
                    seconds[zone_id] = seconds.get(zone_id, 0.0) + float(zone["secs"])
            if seconds:
                reports.append(
                    {
                        "sport": sport,
                        "sensor": sensor,
                        "seconds": seconds,
                        "measured_seconds": sum(seconds.values()),
                        "training_seconds": duration,
                        "measured_sessions": measured_sessions,
                        "total_sessions": len(sport_rows),
                        "source": ", ".join(sorted(sources)),
                        "method": "Provider zones recorded for each activity; no recalculation using current thresholds",
                    }
                )
    return reports


def _valid_zones(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [
        zone
        for zone in values
        if isinstance(zone, dict)
        and isinstance(zone.get("secs"), int | float)
        and not isinstance(zone.get("secs"), bool)
        and zone["secs"] >= 0
        and str(zone.get("id", "")).startswith("Z")
    ]


def training_focus(
    garmin: dict[str, Any],
    today: date,
    timezone: str = "UTC",
    *,
    activities: Sequence[Any],
    days: int = 28,
) -> dict[str, Any]:
    start = (today - timedelta(days=days - 1)).isoformat()
    end = today.isoformat()
    zones = _zone_distribution(
        [
            row
            for row in activities
            if isinstance(row, dict)
            and start <= summary_local_date(row, timezone) <= end
        ]
    )
    categories = {
        key: {"load": 0.0, "sessions": 0}
        for key in ("low_aerobic", "high_aerobic", "anaerobic")
    }
    # Remaining snapshot read: Garmin training effect and load focus have no kind.
    dedicated_rows = garmin.get("training_load_activities")
    has_dedicated_loads = isinstance(dedicated_rows, list) and bool(dedicated_rows)
    activity_source = (
        "training_load_activities+activities" if has_dedicated_loads else "activities"
    )
    seen, unknown, observed_dates = _garmin_activity_coverage(
        garmin, start, end, categories
    )
    freshness = performance_freshness.garmin_source_freshness(garmin, today)
    activity_freshness = {
        key: freshness.get(key)
        or {
            "freshness": "unknown",
            "observed_at": None,
            "fetched_at": None,
            "measurement_status": "unknown",
            "measurement_age_days": None,
        }
        for key in (
            ("activities", "training_load_activities")
            if has_dedicated_loads
            else ("activities",)
        )
    }
    return {
        "start": start,
        "end": end,
        "zones": [row for row in zones if row["sensor"] in {"heart_rate", "power"}],
        "categories": categories,
        "unclassified_sessions": unknown,
        "classified_sessions": len(seen) - unknown,
        "category_source": "Garmin Connect",
        "category_source_key": activity_source,
        "category_freshness": activity_freshness,
        "coverage": {
            "known_sessions": len(seen),
            "observed_start": min(observed_dates) if observed_dates else None,
            "observed_end": max(observed_dates) if observed_dates else None,
        },
    }


def _garmin_activity_coverage(
    garmin: dict[str, Any],
    start: str,
    end: str,
    categories: dict[str, dict[str, float | int]],
) -> tuple[set[str], int, list[str]]:
    seen: set[str] = set()
    unknown = 0
    observed_dates = []
    activities = garmin.get("activities")
    activities = activities if isinstance(activities, list) else []
    loads_by_id = _training_load_by_id(garmin.get("training_load_activities"))
    for index, activity in enumerate(activities[:1000]):
        row_data = _coverage_row(activity, index, loads_by_id, start, end)
        if row_data is None:
            continue
        identity, dedupe_key, day, row = row_data
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        observed_dates.append(day)
        if not identity:
            unknown += 1
            continue
        category = _CATEGORIES.get(
            str(row.get("trainingEffectLabel") or "").upper()[:50]
        )
        activity_load = bounded_activity_metric(
            row.get("activityTrainingLoad"), 0, 100_000
        )
        if category is None or activity_load is None:
            unknown += 1
        else:
            categories[category]["load"] += activity_load
            categories[category]["sessions"] += 1
    return seen, unknown, observed_dates


def _training_load_by_id(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        str(row.get("activityId") or row.get("id")): row
        for row in value[:1000]
        if isinstance(row, dict) and (row.get("activityId") or row.get("id"))
    }


def _coverage_row(
    activity: Any,
    index: int,
    loads_by_id: dict[str, dict[str, Any]],
    start: str,
    end: str,
) -> tuple[str, str, str, dict[str, Any]] | None:
    if not isinstance(activity, dict):
        return None
    identity = str(activity.get("activityId") or activity.get("id") or "")
    row = dict(activity)
    load_record = loads_by_id.get(identity)
    if identity and load_record is not None:
        for key in ("activityTrainingLoad", "trainingEffectLabel"):
            if load_record.get(key) is not None:
                row[key] = load_record[key]
    day = iso_date_prefix(
        str(
            row.get(garmin_perf_fields.ACTIVITY_START_LOCAL)
            or row.get("start_date_local")
            or ""
        )
    )
    if not day or not start <= day <= end:
        return None
    return identity, identity or f"row:{index}", day, row
