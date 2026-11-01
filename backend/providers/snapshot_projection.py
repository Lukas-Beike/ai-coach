"""Project stored provider snapshots into canonical mapping results.

This module is the only place that names the snapshot and payload keys written
by the sync layer. Each projection calls the pure provider mappers, which never
raise on malformed provider data. A top-level value that is not a mapping
projects to empty results. Mapping issues are returned unchanged so the caller
can count them; they are never logged here.

Once the canonical tables serve reads, new Intervals.icu snapshots are stored
without ``recent_activities`` and ``raw_provider_data.activities`` and carry the
``canonical_sections`` marker. ``strip_intervals_activity_sections`` and
``restore_intervals_activity_sections`` convert between both forms; a stripped
snapshot projects no activities, because the tables already hold them.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.local_time import local_date, parse_provider_datetime
from backend.canonical.mapping import MappingIssue, MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.providers.garmin_activity_mapping import (
    map_garmin_activities,
    merge_training_load_rows,
)
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
_GARMIN_TRAINING_LOAD_KEY: Final = "training_load_activities"
# Content-free marker of a snapshot written without its activity sections.
CANONICAL_SECTIONS_KEY: Final = "canonical_sections"
CANONICAL_SECTIONS_TABLES: Final = "tables"


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
        merge_training_load_rows(
            payload.get(_GARMIN_ACTIVITIES_KEY),
            payload.get(_GARMIN_TRAINING_LOAD_KEY),
        ),
        zone=zone,
        retrieved_at=retrieved_at,
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


def without_intervals_activities(
    snapshot: Mapping[str, Any], activity_ids: Collection[str]
) -> dict[str, Any]:
    """Return a copy of ``snapshot`` whose activity sections omit the given ids.

    Rows are matched on their ``id``. The input is not changed, and a snapshot
    without activity sections, or without a match, comes back equal.
    """
    if not activity_ids:
        return dict(snapshot)

    def kept(rows: Any) -> Any:
        if not isinstance(rows, list):
            return rows
        return [
            row
            for row in rows
            if not (isinstance(row, Mapping) and str(row.get("id")) in activity_ids)
        ]

    result = dict(snapshot)
    if _INTERVALS_ACTIVITIES_KEY in result:
        result[_INTERVALS_ACTIVITIES_KEY] = kept(result[_INTERVALS_ACTIVITIES_KEY])
    raw = result.get(_INTERVALS_RAW_KEY)
    if isinstance(raw, Mapping) and _INTERVALS_RAW_ACTIVITIES_KEY in raw:
        result[_INTERVALS_RAW_KEY] = {
            **raw,
            _INTERVALS_RAW_ACTIVITIES_KEY: kept(raw[_INTERVALS_RAW_ACTIVITIES_KEY]),
        }
    return result


def intervals_snapshot_is_stripped(snapshot: object) -> bool:
    """Return True when a stored snapshot no longer carries its activity sections.

    The sync layer writes the marker once the canonical tables serve reads: the
    activities then live only in the tables and their raw records. Wellness, athlete
    and calendar sections stay in the snapshot.
    """
    return (
        isinstance(snapshot, Mapping)
        and snapshot.get(CANONICAL_SECTIONS_KEY) == CANONICAL_SECTIONS_TABLES
    )


def strip_intervals_activity_sections(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy without the activity sections, marked as served by the tables.

    The sections are removed, not emptied, so a stripped snapshot never reads as a
    full activity window that is missing every activity.
    """
    stripped = {
        key: value
        for key, value in snapshot.items()
        if key != _INTERVALS_ACTIVITIES_KEY
    }
    raw = snapshot.get(_INTERVALS_RAW_KEY)
    if isinstance(raw, Mapping):
        stripped[_INTERVALS_RAW_KEY] = {
            key: value
            for key, value in raw.items()
            if key != _INTERVALS_RAW_ACTIVITIES_KEY
        }
    stripped[CANONICAL_SECTIONS_KEY] = CANONICAL_SECTIONS_TABLES
    return stripped


def intervals_activity_sections_are_mapped(snapshot: object, *, zone: tzinfo) -> bool:
    """Return True when the canonical tables durably hold every activity row.

    Stripping is safe only then: a row the mapper rejects, a compact row without a
    raw counterpart and a snapshot without a sync time never reach the tables, so
    their sections must stay in the snapshot. A snapshot without activity sections
    is trivially mapped.
    """
    if not isinstance(snapshot, Mapping):
        return False
    if intervals_snapshot_has_unmatched_compact_rows(snapshot):
        return False
    raw = snapshot.get(_INTERVALS_RAW_KEY)
    rows = raw.get(_INTERVALS_RAW_ACTIVITIES_KEY) if isinstance(raw, Mapping) else None
    if rows is None:
        return not isinstance(snapshot.get(_INTERVALS_ACTIVITIES_KEY), list)
    if not isinstance(rows, list):
        return False
    if not rows:
        return True
    retrieved_at = stored_retrieved_at(snapshot, zone=zone)
    if retrieved_at is None:
        return False
    return all(_maps_with_source_id(row, zone, retrieved_at) for row in rows)


def _maps_with_source_id(row: object, zone: tzinfo, retrieved_at: datetime) -> bool:
    mapped = map_intervals_activities([row], zone=zone, retrieved_at=retrieved_at)
    return (
        bool(mapped.records)
        and mapped.records[0].provenance.source_record_id is not None
    )


def restore_intervals_activity_sections(
    snapshot: Mapping[str, Any],
    *,
    raw_rows: Iterable[Mapping[str, Any]],
    compact_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a copy of a stripped snapshot with its activity sections rebuilt.

    The rows come from the canonical tables. The result is an in-memory merge
    base, so the marker is removed: the next write decides again whether to strip.
    """
    restored = {
        key: value for key, value in snapshot.items() if key != CANONICAL_SECTIONS_KEY
    }
    raw = snapshot.get(_INTERVALS_RAW_KEY)
    restored[_INTERVALS_RAW_KEY] = {
        **(raw if isinstance(raw, Mapping) else {}),
        _INTERVALS_RAW_ACTIVITIES_KEY: [dict(row) for row in raw_rows],
    }
    restored[_INTERVALS_ACTIVITIES_KEY] = [dict(row) for row in compact_rows]
    return restored


def intervals_snapshot_has_unmatched_compact_rows(snapshot: object) -> bool:
    """Return True when a stored compact activity row has no raw counterpart.

    Snapshots from releases before ``raw_provider_data`` keep their activities only
    in ``recent_activities``. The mapper cannot map that compact read model, so
    those rows never reach the tables. An incremental sync merges its window's raw
    rows with the older compact rows, so the gap stays until a full reload returns
    a raw row with the same id. A compact row without an id is never matched and
    is ignored.
    """
    if not isinstance(snapshot, Mapping):
        return False
    compact = snapshot.get(_INTERVALS_ACTIVITIES_KEY)
    if not isinstance(compact, list):
        return False
    raw = snapshot.get(_INTERVALS_RAW_KEY)
    rows = raw.get(_INTERVALS_RAW_ACTIVITIES_KEY) if isinstance(raw, Mapping) else None
    raw_ids = {
        str(row["id"])
        for row in (rows if isinstance(rows, list) else ())
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    return any(
        isinstance(row, Mapping)
        and row.get("id") is not None
        and str(row["id"]) not in raw_ids
        for row in compact
    )


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
