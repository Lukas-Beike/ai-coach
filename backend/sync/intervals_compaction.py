"""Ingest-time compaction of a fetched Intervals.icu payload into the stored snapshot.

The Intervals.icu sync and the analysis-session refresh keep only these
whitelisted fields before the snapshot is stored; consumers read canonical records.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.canonical.mapping import selected
from backend.planning.compact_activities import RECENT_ACTIVITY_LIMIT
from backend.providers.intervals_activity_fields import ACTIVITY_FIELDS
from backend.providers.intervals_performance_fields import (
    CONFIGURED_FTP,
    INTENSITY,
    TRAINING_LOAD,
    W_PRIME,
)

SPORT_SETTING_FIELDS = (
    "id",
    "types",
    "ftp",
    "indoor_ftp",
    "eftp",
    "eFTP",
    "w_prime",
    "p_max",
    "power_zones",
    "hr_zones",
    "pace_zones",
    "lthr",
    "max_hr",
    "maxHR",
    "maxHeartRate",
    "threshold_pace",
    "zone2_pace",
    "zone_2_pace",
    "z2_pace",
    "pace_zone2",
    "paceZone2",
    "zone2Pace",
    "pace_units",
    "vo2max",
    "vo2_max",
    "running_vo2max",
    "cycling_vo2max",
)


WELLNESS_SPORT_INFO_FIELDS = (
    "id",
    "type",
    "types",
    "sport",
    "sport_type",
    "ftp",
    "eftp",
    "eFTP",
    "wPrime",
    "w_prime",
    "pMax",
    "p_max",
    "lthr",
    "max_hr",
    "maxHR",
    "maxHeartRate",
    "threshold_pace",
    "zone2_pace",
    "zone_2_pace",
    "z2_pace",
    "pace_zone2",
    "paceZone2",
    "zone2Pace",
    "pace_units",
    "vo2max",
    "vo2_max",
    "running_vo2max",
    "cycling_vo2max",
)


WELLNESS_FIELDS = (
    "id",
    "ctl",
    "ctLoad",
    "atl",
    "atlLoad",
    "tsb",
    "form",
    "rampRate",
    "weight",
    "bodyFat",
    "body_fat",
    "restingHR",
    "hrv",
    "hrvSDNN",
    "sleepSecs",
    "sleepScore",
    "fatigue",
    "soreness",
    "stress",
    "mood",
    "readiness",
    "readinessScore",
    "readiness_score",
    "trainingReadiness",
    "training_readiness",
)


EVENT_FIELDS = (
    "id",
    "start_date_local",
    "category",
    "name",
    "description",
    "type",
    "moving_time",
    "elapsed_time",
    "distance",
    TRAINING_LOAD,
    INTENSITY,
    "target",
    "external_id",
)


ATHLETE_FIELDS = (
    "id",
    "name",
    "sex",
    "weight",
    "height",
    "height_cm",
    "bodyFat",
    "body_fat",
    "dob",
    CONFIGURED_FTP,
    W_PRIME,
    "max_hr",
    "maxHR",
    "maxHeartRate",
    "lthr",
    "vo2max",
    "vo2_max",
    "running_vo2max",
    "cycling_vo2max",
)


def compact_sport_settings(athlete: Any) -> list[dict[str, Any]]:
    if not isinstance(athlete, dict):
        return []
    raw_settings = athlete.get("sportSettings") or athlete.get("sport_settings") or []
    if not isinstance(raw_settings, list):
        return []
    compacted = []
    for item in raw_settings[:30]:
        if not isinstance(item, dict):
            continue
        setting = selected(item, SPORT_SETTING_FIELDS)
        mmp_model = item.get("mmp_model")
        if isinstance(mmp_model, dict):
            setting["mmp_model"] = selected(mmp_model, ("ftp", "eftp", "eFTP"))
        compacted.append(setting)
    return compacted


def compact_wellness_sport_info(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        selected(item, WELLNESS_SPORT_INFO_FIELDS)
        for item in [candidate for candidate in value if isinstance(candidate, dict)][
            :30
        ]
    ]


def compact_snapshot(
    athlete: Any,
    activities: Any,
    wellness: Any,
    events: Any,
    history_days: int = 42,
    *,
    all_sync_days: int,
    synced_at: str,
) -> dict[str, Any]:
    compact_activities = [
        selected(item, ACTIVITY_FIELDS) for item in (activities or [])
    ]
    compact_wellness = [
        {
            **selected(item, WELLNESS_FIELDS),
            "sport_info": compact_wellness_sport_info(item.get("sportInfo")),
        }
        for item in (wellness or [])
        if isinstance(item, dict)
    ]
    if history_days != all_sync_days:
        compact_activities = compact_activities[:500]
        compact_wellness = compact_wellness[-(max(42, history_days) + 1) :]
    return {
        "synced_at": synced_at,
        "athlete": {
            **selected(athlete, ATHLETE_FIELDS),
            "sport_settings": compact_sport_settings(athlete),
        },
        "recent_activities": compact_activities,
        "recent_wellness": compact_wellness,
        "upcoming_calendar": [selected(item, EVENT_FIELDS) for item in (events or [])][
            :200
        ],
    }


def compact_activity_row(row: Any) -> dict[str, Any]:
    """Return the compact activity fields of one raw row; a non-mapping is empty."""
    return selected(row, ACTIVITY_FIELDS)


def compact_activity_rows(
    rows: Iterable[Any], *, limit: int = RECENT_ACTIVITY_LIMIT
) -> list[dict[str, Any]]:
    """Select the compact activity fields of the first ``limit`` raw rows."""
    compact = [compact_activity_row(row) for row in rows if isinstance(row, dict)]
    return compact[:limit]
