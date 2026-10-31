"""Recorded sensor zones and the activity training-effect categories.

Both read the canonical activity summaries only: the categories come from the
training-effect label and load of the sessions Garmin Connect reported (#1416).
The Garmin sync status supplies only the freshness.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.activities.activity_summary import summary_local_date
from backend.canonical.vocabulary import ProviderId
from backend.performance import freshness as performance_freshness
from backend.performance.activity_validation import bounded_activity_metric
from backend.performance.training_report import zone_distribution

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
# The provider whose training-effect categories the focus shows.
_CATEGORY_PROVIDER: Final = ProviderId.GARMIN.value
# The Garmin sections whose freshness describes the categories.
_ACTIVITIES_SECTION: Final = "activities"
_TRAINING_LOAD_SECTION: Final = "training_load_activities"
_UNKNOWN_FRESHNESS: Final = {
    "freshness": "unknown",
    "observed_at": None,
    "fetched_at": None,
    "measurement_status": "unknown",
    "measurement_age_days": None,
}


def training_focus(
    garmin: performance_freshness.GarminSyncStatus,
    today: date,
    timezone: str = "UTC",
    *,
    activities: Sequence[Any],
    days: int = 28,
) -> dict[str, Any]:
    start = (today - timedelta(days=days - 1)).isoformat()
    end = today.isoformat()
    in_window = [
        row
        for row in activities
        if isinstance(row, Mapping)
        and start <= summary_local_date(row, timezone) <= end
    ]
    zones = zone_distribution(in_window)
    categories = {
        key: {"load": 0.0, "sessions": 0}
        for key in ("low_aerobic", "high_aerobic", "anaerobic")
    }
    has_dedicated_loads = _TRAINING_LOAD_SECTION in garmin.populated_sections
    activity_source = (
        f"{_TRAINING_LOAD_SECTION}+{_ACTIVITIES_SECTION}"
        if has_dedicated_loads
        else _ACTIVITIES_SECTION
    )
    known, unknown, observed_dates = _category_coverage(
        activities, start, end, categories
    )
    freshness = performance_freshness.garmin_source_freshness(garmin, today)
    activity_freshness = {
        key: freshness.get(key) or dict(_UNKNOWN_FRESHNESS)
        for key in (
            (_ACTIVITIES_SECTION, _TRAINING_LOAD_SECTION)
            if has_dedicated_loads
            else (_ACTIVITIES_SECTION,)
        )
    }
    return {
        "start": start,
        "end": end,
        "zones": [row for row in zones if row["sensor"] in {"heart_rate", "power"}],
        "categories": categories,
        "unclassified_sessions": unknown,
        "classified_sessions": known - unknown,
        "category_source": "Garmin Connect",
        "category_source_key": activity_source,
        "category_freshness": activity_freshness,
        "coverage": {
            "known_sessions": known,
            "observed_start": min(observed_dates) if observed_dates else None,
            "observed_end": max(observed_dates) if observed_dates else None,
        },
    }


def _category_coverage(
    summaries: Sequence[Any],
    start: str,
    end: str,
    categories: dict[str, dict[str, float | int]],
) -> tuple[int, int, list[str]]:
    """Add each Garmin session's load to its category; return the coverage.

    A session is dated by its athlete-local start date, as Garmin's own local
    start time dated it.
    """
    known = 0
    unknown = 0
    observed_dates = []
    for summary in summaries:
        if not isinstance(summary, Mapping):
            continue
        record_ids = summary.get("record_ids")
        day = summary_local_date(summary)
        if (
            not isinstance(record_ids, Mapping)
            or _CATEGORY_PROVIDER not in record_ids
            or not start <= day <= end
        ):
            continue
        known += 1
        observed_dates.append(day)
        category = _CATEGORIES.get(str(summary.get("training_effect_label") or ""))
        activity_load = bounded_activity_metric(
            summary.get("training_effect_load"), 0, 100_000
        )
        if category is None or activity_load is None:
            unknown += 1
        else:
            categories[category]["load"] += activity_load
            categories[category]["sessions"] += 1
    return known, unknown, observed_dates
