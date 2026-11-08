"""Test fixture: compact an Intervals.icu payload into the stored-snapshot shape.

The Intervals.icu sync and the analysis-session refresh keep only these
whitelisted fields before the snapshot is stored; consumers read canonical records.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta, tzinfo
from typing import Any

from intervals_plan_stub import intervals_ingest_plan

from backend.canonical.local_time import local_date
from backend.canonical.mapping import selected
from backend.planning.compact_activities import RECENT_ACTIVITY_LIMIT
from backend.providers.intervals_performance_fields import INTENSITY, TRAINING_LOAD
from backend.providers.snapshot_projection import stored_retrieved_at
from backend.sync.canonical_ingest import (
    DELETION_EDGE_MARGIN,
    CanonicalIngestCounters,
    DeletionWindow,
    ingest_plan,
)

INTERVALS_POWER_CURVE_KEY = "cycling_power_profile"
CONFIGURED_FTP = "icu_ftp"
W_PRIME = "icu_w_prime"

ACTIVITY_FIELDS = (
    "id",
    "start_date_local",
    "name",
    "type",
    "moving_time",
    "distance",
    "total_elevation_gain",
    "elapsed_time",
    "icu_training_load",
    "icu_intensity",
    "icu_ctl",
    "icu_atl",
    "icu_ftp",
    "icu_eftp",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "weighted_average_watts",
    "icu_weighted_avg_watts",
    "normalized_power",
    "average_speed",
    "max_speed",
    "icu_weighted_avg_speed",
    "icu_pace",
    "vo2max",
    "vo2_max",
    "vO2MaxValue",
    "vo2MaxValue",
    "icu_vo2max",
    "feel",
    "icu_rpe",
    "paired_event_id",
    "source",
    "device_name",
    "external_id",
    "file_type",
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


def intervals_deletion_window(
    *, today: date, activity_days: int, all_sync_days: int, earliest_date: date
) -> DeletionWindow:
    """Return the days a full Intervals.icu fetch covers with certainty.

    The fetch window follows split_date_windows on the provider's local start
    date, while stored rows carry the athlete-local date. Both can differ by a
    day (travel, offset fallback around midnight), so the first and last day are
    excluded: a deletion there might hit an activity the fetch never asked for,
    and an edge day can fall out of every later window. A deletion on those days
    is picked up by a later, wider full fetch instead.
    """
    if activity_days == all_sync_days:
        start = earliest_date
    else:
        start = today - timedelta(days=max(1, activity_days) - 1)
    return DeletionWindow(
        start=start + DELETION_EDGE_MARGIN, end=today - DELETION_EDGE_MARGIN
    )


def _has_activity_list(raw: object) -> bool:
    """A missing or non-list activity block must never be read as "nothing fetched"."""
    return isinstance(raw, Mapping) and isinstance(raw.get("activities"), list)


def ingest_intervals_snapshot(
    db: Any,
    snapshot: Mapping[str, Any],
    *,
    zone: tzinfo,
    activity_days: int | None,
    all_sync_days: int,
    earliest_date: date,
) -> CanonicalIngestCounters:
    """Write the Intervals.icu raw block and the stored power curve of a snapshot.

    ``activity_days`` is None for historical fetches, which never delete. An
    incremental snapshot never deletes either. A snapshot without a sync time
    writes nothing and returns empty counters.
    """
    retrieved_at = stored_retrieved_at(snapshot, zone=zone)
    if retrieved_at is None:
        return CanonicalIngestCounters()
    raw = snapshot.get("raw_provider_data")
    plan = intervals_ingest_plan(
        raw,
        zone=zone,
        retrieved_at=retrieved_at,
        power_curve=snapshot.get(INTERVALS_POWER_CURVE_KEY),
    )
    deletion_window = None
    if (
        activity_days is not None
        and snapshot.get("incremental") is not True
        and _has_activity_list(raw)
    ):
        deletion_window = intervals_deletion_window(
            today=local_date(retrieved_at, zone),
            activity_days=activity_days,
            all_sync_days=all_sync_days,
            earliest_date=earliest_date,
        )
    return ingest_plan(
        db,
        plan,
        retrieved_at=retrieved_at,
        deletion_window=deletion_window,
        zone=zone,
    )


def ingest_intervals_partial_snapshot(
    db: Any, snapshot: Mapping[str, Any], *, zone: tzinfo
) -> CanonicalIngestCounters:
    """Write the raw block of a partial Intervals.icu fetch, such as a performance refresh.

    A partial window never marks missing records deleted: only a full window
    knows which records the provider no longer returns.
    """
    retrieved_at = stored_retrieved_at(snapshot, zone=zone)
    if retrieved_at is None:
        return CanonicalIngestCounters()
    plan = intervals_ingest_plan(
        snapshot.get("raw_provider_data"),
        zone=zone,
        retrieved_at=retrieved_at,
        power_curve=snapshot.get(INTERVALS_POWER_CURVE_KEY),
    )
    return ingest_plan(
        db, plan, retrieved_at=retrieved_at, deletion_window=None, zone=zone
    )
