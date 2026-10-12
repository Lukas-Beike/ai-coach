"""Pure plans that turn stored provider payloads into canonical ingest rows.

The plans call the provider mappers and never write. A row that maps to no
record is skipped and counted, so one malformed row never blocks the rest of a
payload. Raw records keep the provider rows as fetched; the sync layer sanitizes
them before they are stored. Activities are mapped from the full raw rows, not
from the compact read model used by the legacy snapshot projection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.local_time import local_date
from backend.canonical.mapping import MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import ProviderId
from backend.providers.garmin_activity_mapping import (
    MAPPER_VERSION as GARMIN_ACTIVITY_VERSION,
)
from backend.providers.garmin_activity_mapping import map_garmin_activities
from backend.providers.garmin_health_mapping import (
    GARMIN_HEALTH_SECTION_NAMES,
    map_garmin_health,
)
from backend.providers.garmin_health_mapping import (
    MAPPER_VERSION as GARMIN_HEALTH_VERSION,
)
from backend.providers.intervals_activity_mapping import (
    MAPPER_VERSION as INTERVALS_ACTIVITY_VERSION,
)
from backend.providers.intervals_activity_mapping import map_intervals_activities
from backend.providers.intervals_wellness_mapping import (
    MAPPER_VERSION as INTERVALS_WELLNESS_VERSION,
)
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)

ACTIVITY_RECORD_KIND: Final = "activity"
WELLNESS_RECORD_KIND: Final = "wellness"
ATHLETE_RECORD_KIND: Final = "athlete"
HEALTH_RECORD_KIND: Final = "health"

ATHLETE_RECORD_ID: Final = "athlete"
MAX_RECORD_ID_LENGTH: Final = 256
INTERVALS_ACTIVITY_ID_KEY: Final = "id"
INTERVALS_WELLNESS_ID_KEY: Final = "id"
GARMIN_ACTIVITY_ID_KEY: Final = "activityId"


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One provider row or health section, unsanitized, ready for storage."""

    record_kind: str
    source_record_id: str
    payload: Mapping[str, Any]
    mapper_version: int


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """A mapped activity with its athlete-local date and mapper version."""

    record: ActivityRecord
    local_date: date
    mapper_version: int


@dataclass(frozen=True, slots=True)
class ObservationItem:
    observation: Observation
    mapper_version: int


@dataclass(frozen=True, slots=True)
class IngestPlan:
    """Everything one fetched payload contributes to the canonical tables."""

    provider: ProviderId
    raw_records: tuple[RawRecord, ...] = ()
    activities: tuple[ActivityItem, ...] = ()
    observations: tuple[ObservationItem, ...] = ()
    present_activity_ids: frozenset[str] = field(default_factory=frozenset)
    skipped_invalid: int = 0


def intervals_ingest_plan(
    raw: object, *, zone: tzinfo, retrieved_at: datetime
) -> IngestPlan:
    """Plan the canonical rows of one Intervals.icu ``raw_provider_data`` block."""
    if not isinstance(raw, Mapping):
        return IngestPlan(provider=ProviderId.INTERVALS)
    activity_rows, raw_records, skipped, present = _activity_batch(
        raw.get("activities"),
        id_key=INTERVALS_ACTIVITY_ID_KEY,
        mapper=lambda rows: map_intervals_activities(
            rows, zone=zone, retrieved_at=retrieved_at
        ),
        mapper_version=INTERVALS_ACTIVITY_VERSION,
        zone=zone,
    )
    observations: list[ObservationItem] = []
    wellness_rows = raw.get("wellness")
    if isinstance(wellness_rows, list):
        valid_rows: list[Any] = []
        for row in wellness_rows:
            row_id = _row_id(row, INTERVALS_WELLNESS_ID_KEY)
            if row_id is None:
                skipped += 1
                continue
            valid_rows.append(row)
            raw_records.append(
                RawRecord(WELLNESS_RECORD_KIND, row_id, row, INTERVALS_WELLNESS_VERSION)
            )
        wellness = map_intervals_wellness(valid_rows, retrieved_at=retrieved_at)
        observations.extend(
            ObservationItem(observation, INTERVALS_WELLNESS_VERSION)
            for observation in wellness.records
        )
    athlete = raw.get("athlete")
    if isinstance(athlete, dict):
        raw_records.append(
            RawRecord(
                ATHLETE_RECORD_KIND, ATHLETE_RECORD_ID, athlete, INTERVALS_WELLNESS_VERSION
            )
        )
        thresholds = map_intervals_athlete_thresholds(
            athlete,
            observed_on=local_date(retrieved_at, zone),
            retrieved_at=retrieved_at,
        )
        observations.extend(
            ObservationItem(observation, INTERVALS_WELLNESS_VERSION)
            for observation in thresholds.records
        )
    elif athlete is not None:
        skipped += 1
    return IngestPlan(
        provider=ProviderId.INTERVALS,
        raw_records=tuple(raw_records),
        activities=tuple(activity_rows),
        observations=tuple(observations),
        present_activity_ids=frozenset(present),
        skipped_invalid=skipped,
    )


def garmin_ingest_plan(
    payload: object, *, zone: tzinfo, retrieved_at: datetime
) -> IngestPlan:
    """Plan the canonical rows of one stored Garmin payload."""
    if not isinstance(payload, Mapping):
        return IngestPlan(provider=ProviderId.GARMIN)
    activity_rows, raw_records, skipped, present = _activity_batch(
        payload.get("activities"),
        id_key=GARMIN_ACTIVITY_ID_KEY,
        mapper=lambda rows: map_garmin_activities(
            rows, zone=zone, retrieved_at=retrieved_at
        ),
        mapper_version=GARMIN_ACTIVITY_VERSION,
        zone=zone,
    )
    for name in GARMIN_HEALTH_SECTION_NAMES:
        value = payload.get(name)
        if value is not None:
            raw_records.append(
                RawRecord(HEALTH_RECORD_KIND, name, {"data": value}, GARMIN_HEALTH_VERSION)
            )
    health = map_garmin_health(payload, zone=zone, retrieved_at=retrieved_at)
    return IngestPlan(
        provider=ProviderId.GARMIN,
        raw_records=tuple(raw_records),
        activities=tuple(activity_rows),
        observations=tuple(
            ObservationItem(observation, GARMIN_HEALTH_VERSION)
            for observation in health.records
        ),
        present_activity_ids=frozenset(present),
        skipped_invalid=skipped,
    )


def _activity_batch(
    rows: object,
    *,
    id_key: str,
    mapper: Callable[[list[Any]], MappingResult[ActivityRecord]],
    mapper_version: int,
    zone: tzinfo,
) -> tuple[list[ActivityItem], list[RawRecord], int, set[str]]:
    """Map activity rows one by one so each invalid row is counted on its own.

    Every row with a usable identifier is reported as present, even when it does
    not map, so a full-window deletion never removes a record that the provider
    still returned.
    """
    if not isinstance(rows, list):
        return [], [], 0, set()
    items: list[ActivityItem] = []
    raw_records: list[RawRecord] = []
    present: set[str] = set()
    skipped = 0
    for row in rows:
        row_id = _row_id(row, id_key)
        if row_id is not None:
            present.add(row_id)
        mapped = mapper([row]).records
        source_id = mapped[0].provenance.source_record_id if mapped else None
        if not mapped or source_id is None:
            skipped += 1
            continue
        record = mapped[0]
        present.add(source_id)
        raw_records.append(RawRecord(ACTIVITY_RECORD_KIND, source_id, row, mapper_version))
        items.append(
            ActivityItem(
                record=record,
                local_date=local_date(record.started_at, zone),
                mapper_version=mapper_version,
            )
        )
    return items, raw_records, skipped, present


def _row_id(row: object, key: str) -> str | None:
    """Return a usable provider identifier from a row, or None when it has none."""
    if not isinstance(row, Mapping):
        return None
    value = row.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        return None
    if len(value) > MAX_RECORD_ID_LENGTH:
        return None
    return value
