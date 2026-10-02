"""Recorded sensor zones and Garmin's activity training-effect categories."""

from datetime import date, timedelta
from typing import Any

from backend.performance.training_report import (
    activity_day,
    canonical_rows,
    number,
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
    start = (today - timedelta(days=55)).isoformat()
    end = today.isoformat()
    activities, _ = canonical_rows(snapshot or {})
    zones = zone_distribution(
        [row for row in activities if start <= activity_day(row, timezone) <= end]
    )
    categories = {
        key: {"load": 0.0, "sessions": 0}
        for key in ("low_aerobic", "high_aerobic", "anaerobic")
    }
    seen: set[str] = set()
    unknown = 0
    observed_dates = []
    rows = garmin.get("activities")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        identity = str(row.get("activityId") or row.get("id") or "")
        day = activity_day(
            {
                "start_date_local": row.get("startTimeLocal")
                or row.get("start_date_local")
            },
            timezone,
        )
        if not identity or identity in seen or not start <= day <= end:
            continue
        seen.add(identity)
        observed_dates.append(day)
        label = str(row.get("trainingEffectLabel") or "").upper()
        category = _CATEGORIES.get(label)
        load = number(row.get("activityTrainingLoad"))
        if category is None or load is None or load < 0:
            unknown += 1
            continue
        categories[category]["load"] += load
        categories[category]["sessions"] += 1
    return {
        "start": start,
        "end": end,
        "zones": [row for row in zones if row["sensor"] in {"heart_rate", "power"}],
        "categories": categories,
        "unclassified_sessions": unknown,
        "classified_sessions": len(seen) - unknown,
        "category_source": "Garmin Connect",
        "coverage": {
            "known_sessions": len(seen),
            "observed_start": min(observed_dates) if observed_dates else None,
            "observed_end": max(observed_dates) if observed_dates else None,
        },
    }
