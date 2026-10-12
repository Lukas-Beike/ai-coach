"""Project stored provider snapshots into canonical mapping results.

This module is the only place that names the snapshot and payload keys written
by the sync layer. Each projection calls the pure provider mappers, which never
raise on malformed provider data. A top-level value that is not a mapping
projects to empty results. Mapping issues are returned unchanged so the caller
can count them; they are never logged here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.local_time import local_date, parse_provider_datetime
from backend.canonical.mapping import MappingIssue, MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.providers.garmin_activity_mapping import map_garmin_activities
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.intervals_activity_mapping import map_intervals_activities
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)

type ProjectedSnapshot = tuple[
    MappingResult[ActivityRecord], MappingResult[Observation]
]

_STORED_TIME_KEY: Final = "synced_at"
_INTERVALS_ACTIVITIES_KEY: Final = "recent_activities"
_INTERVALS_RAW_KEY: Final = "raw_provider_data"
_INTERVALS_RAW_ACTIVITIES_KEY: Final = "activities"
_INTERVALS_WELLNESS_KEY: Final = "recent_wellness"
_INTERVALS_ATHLETE_KEY: Final = "athlete"
_GARMIN_ACTIVITIES_KEY: Final = "activities"


def stored_retrieved_at(record: object, *, zone: tzinfo) -> datetime | None:
    """Return the sync time stored with a snapshot or payload, or None.

    Naive stored text is read as wall-clock time in ``zone``. Non-mapping input,
    a missing key and unparseable text all give None.
    """
    if not isinstance(record, Mapping):
        return None
    return parse_provider_datetime(record.get(_STORED_TIME_KEY), zone)


def project_intervals_snapshot(
    snapshot: object, *, zone: tzinfo, retrieved_at: datetime
) -> ProjectedSnapshot:
    """Map a stored Intervals.icu snapshot to activities and observations.

    The athlete's thresholds are dated on the athlete-local date of
    ``retrieved_at``. A non-mapping snapshot projects to empty results.
    """
    if not isinstance(snapshot, Mapping):
        return _empty_projection()
    activities = map_intervals_activities(
        snapshot.get(_INTERVALS_ACTIVITIES_KEY), zone=zone, retrieved_at=retrieved_at
    )
    wellness = map_intervals_wellness(
        snapshot.get(_INTERVALS_WELLNESS_KEY), retrieved_at=retrieved_at
    )
    athlete = map_intervals_athlete_thresholds(
        snapshot.get(_INTERVALS_ATHLETE_KEY),
        observed_on=local_date(retrieved_at, zone),
        retrieved_at=retrieved_at,
    )
    return activities, _merge((wellness, athlete))


def project_garmin_snapshot(
    payload: object, *, zone: tzinfo, retrieved_at: datetime
) -> ProjectedSnapshot:
    """Map a stored Garmin payload to activities and health observations.

    The health mapper reads only its own section names from the payload, so the
    whole payload is passed as the section mapping. A non-mapping payload
    projects to empty results.
    """
    if not isinstance(payload, Mapping):
        return _empty_projection()
    activities = map_garmin_activities(
        payload.get(_GARMIN_ACTIVITIES_KEY), zone=zone, retrieved_at=retrieved_at
    )
    health = map_garmin_health(payload, zone=zone, retrieved_at=retrieved_at)
    return activities, health


def intervals_activity_rows(snapshot: object) -> tuple[dict[str, Any], ...]:
    """Return the raw activity rows of a stored Intervals.icu snapshot.

    The raw ``activities`` list is preferred, else the compact ``recent_activities``
    list; entries that are not mappings are dropped. Order is the stored order.
    """
    if not isinstance(snapshot, Mapping):
        return ()
    raw = snapshot.get(_INTERVALS_RAW_KEY)
    rows = raw.get(_INTERVALS_RAW_ACTIVITIES_KEY) if isinstance(raw, Mapping) else None
    if not isinstance(rows, list):
        rows = snapshot.get(_INTERVALS_ACTIVITIES_KEY)
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def intervals_snapshot_has_only_compact_rows(snapshot: object) -> bool:
    """Return True when a stored snapshot lists activities only in compact form.

    Snapshots from releases before ``raw_provider_data`` keep their activities only
    in ``recent_activities``. The backfill cannot map that compact read model, so
    its rows never reach the tables.
    """
    if not isinstance(snapshot, Mapping):
        return False
    raw = snapshot.get(_INTERVALS_RAW_KEY)
    rows = raw.get(_INTERVALS_RAW_ACTIVITIES_KEY) if isinstance(raw, Mapping) else None
    if isinstance(rows, list):
        return False
    return isinstance(snapshot.get(_INTERVALS_ACTIVITIES_KEY), list)


def intervals_row_local_date(
    row: Mapping[str, Any], *, zone: tzinfo, retrieved_at: datetime
) -> date | None:
    """Return the athlete-local date the mapper gives one raw row, or None.

    A row the mapper rejects has no date; the table source never stores such a
    row either.
    """
    mapped = map_intervals_activities([row], zone=zone, retrieved_at=retrieved_at)
    if not mapped.records:
        return None
    return local_date(mapped.records[0].started_at, zone)


def _empty_projection() -> ProjectedSnapshot:
    return MappingResult(), MappingResult()


def _merge[T](results: Iterable[MappingResult[T]]) -> MappingResult[T]:
    records: list[T] = []
    issues: list[MappingIssue] = []
    for result in results:
        records.extend(result.records)
        issues.extend(result.issues)
    return MappingResult(records=tuple(records), issues=tuple(issues))
