"""Project stored provider snapshots into canonical mapping results.

This module is the only place that names the snapshot and payload keys written
by the sync layer. Each projection calls the pure provider mappers, which never
raise on malformed provider data. A top-level value that is not a mapping
projects to empty results. Mapping issues are returned unchanged so the caller
can count them; they are never logged here.

Intervals.icu is an output target only; its stored snapshots are not projected.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, tzinfo
from typing import Final

from backend.canonical.garmin_payload import dedicated_activity_rows
from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.mapping import MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.providers.garmin_activity_mapping import (
    map_garmin_activities,
    merge_training_load_rows,
)
from backend.providers.garmin_health_mapping import map_garmin_health

type ProjectedSnapshot = tuple[
    MappingResult[ActivityRecord], MappingResult[Observation]
]

_STORED_TIME_KEY: Final = "synced_at"
_GARMIN_ACTIVITIES_KEY: Final = "activities"
_GARMIN_TRAINING_LOAD_KEY: Final = "training_load_activities"


def stored_retrieved_at(record: object, *, zone: tzinfo) -> datetime | None:
    """Return the sync time stored with a snapshot or payload, or None.

    Naive stored text is read as wall-clock time in ``zone``. Non-mapping input,
    a missing key and unparseable text all give None.
    """
    if not isinstance(record, Mapping):
        return None
    return parse_provider_datetime(record.get(_STORED_TIME_KEY), zone)


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
            dedicated_activity_rows(dict(payload)),
        ),
        zone=zone,
        retrieved_at=retrieved_at,
    )
    health = map_garmin_health(payload, zone=zone, retrieved_at=retrieved_at)
    return activities, health


def _empty_projection() -> ProjectedSnapshot:
    return MappingResult(), MappingResult()
