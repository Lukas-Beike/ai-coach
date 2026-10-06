"""Recorded sensor zones and Garmin's activity training-effect categories."""

from datetime import date, timedelta
from typing import Any

from backend.performance import freshness as performance_freshness
from backend.performance.activity_validation import bounded_activity_metric
from backend.performance.training_report import (
    activity_day,
    canonical_rows,
    zone_distribution,
)

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


def training_focus(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any],
    today: date,
    timezone: str = "UTC",
) -> dict[str, Any]:
    start = (today - timedelta(days=27)).isoformat()
    end = today.isoformat()
    activities, _ = canonical_rows(snapshot or {})
    zones = zone_distribution(
        [row for row in activities if start <= activity_day(row, timezone) <= end]
    )
    categories = {
        key: {"load": 0.0, "sessions": 0}
        for key in ("low_aerobic", "high_aerobic", "anaerobic")
    }
    dedicated_rows = garmin.get("training_load_activities")
    has_dedicated_loads = isinstance(dedicated_rows, list) and bool(dedicated_rows)
    activity_source = (
        "training_load_activities+activities" if has_dedicated_loads else "activities"
    )
    seen, unknown, observed_dates = _garmin_activity_coverage(
        garmin, start, end, timezone, categories
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
    timezone: str,
    categories: dict[str, dict[str, float | int]],
) -> tuple[set[str], int, list[str]]:
    seen: set[str] = set()
    unknown = 0
    observed_dates = []
    activities = garmin.get("activities")
    activities = activities if isinstance(activities, list) else []
    loads = garmin.get("training_load_activities")
    loads_by_id = (
        {
            str(row.get("activityId") or row.get("id")): row
            for row in loads[:1000]
            if isinstance(row, dict) and (row.get("activityId") or row.get("id"))
        }
        if isinstance(loads, list)
        else {}
    )
    for index, activity in enumerate(activities[:1000]):
        if not isinstance(activity, dict):
            continue
        identity = str(activity.get("activityId") or activity.get("id") or "")
        row = dict(activity)
        if identity and identity in loads_by_id:
            load_record = loads_by_id[identity]
            for key in ("activityTrainingLoad", "trainingEffectLabel"):
                if load_record.get(key) is not None:
                    row[key] = load_record[key]
        day = activity_day(
            {
                "start_date_local": row.get("startTimeLocal")
                or row.get("start_date_local")
            },
            timezone,
        )
        if not day or not start <= day <= end:
            continue
        if identity and identity in seen:
            continue
        seen.add(identity or f"row:{index}")
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
