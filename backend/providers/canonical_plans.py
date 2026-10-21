"""Pure plans that turn stored provider payloads into canonical ingest rows.

The plans call the provider mappers and never write. A row that maps to no
record is skipped and counted, so one malformed row never blocks the rest of a
payload. Raw records keep the provider rows as fetched; the sync layer sanitizes
them before they are stored. Activities are mapped from the full raw rows, not
from the compact read model used by the legacy snapshot projection.

A Garmin payload keeps sections from earlier reads when a refresh fails or skips
them. Each Garmin section is therefore stamped with the time it was fetched, not
with the payload's latest sync time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.garmin_payload import ITEM_SECTIONS as GARMIN_ITEM_SECTIONS
from backend.canonical.local_time import local_date, parse_provider_datetime
from backend.canonical.mapping import MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.section_items import (
    record_id,
    section_of,
    split_section,
    wrapped,
)
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
from backend.providers.garmin_weight_walk import WEIGHT_SECTIONS
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
from backend.providers.snapshot_projection import (
    intervals_snapshot_is_stripped,
    stored_retrieved_at,
)
from backend.providers.wahoo_activity_mapping import (
    MAPPER_VERSION as WAHOO_ACTIVITY_VERSION,
)
from backend.providers.wahoo_activity_mapping import (
    map_wahoo_activities,
    raw_workout_for_storage,
)
from backend.providers.wahoo_threshold_mapping import (
    MAPPER_VERSION as WAHOO_THRESHOLD_VERSION,
)
from backend.providers.wahoo_threshold_mapping import (
    USER_RECORD_ID as WAHOO_USER_RECORD_ID,
)
from backend.providers.wahoo_threshold_mapping import (
    map_wahoo_power_zones,
    map_wahoo_threshold_payload,
    map_wahoo_user,
    select_power_zone_sets,
)

ACTIVITY_RECORD_KIND: Final = "activity"
WELLNESS_RECORD_KIND: Final = "wellness"
ATHLETE_RECORD_KIND: Final = "athlete"
HEALTH_RECORD_KIND: Final = "health"
WAHOO_POWER_ZONES_RECORD_KIND: Final = "power_zones"
WAHOO_USER_RECORD_KIND: Final = "user"

ATHLETE_RECORD_ID: Final = "athlete"
MAX_RECORD_ID_LENGTH: Final = 256
INTERVALS_ACTIVITY_ID_KEY: Final = "id"
INTERVALS_WELLNESS_ID_KEY: Final = "id"
GARMIN_ACTIVITY_ID_KEY: Final = "activityId"
WAHOO_ACTIVITY_ID_KEY: Final = "id"
WAHOO_SYNCED_AT_KEY: Final = "synced_at"
WAHOO_WORKOUTS_KEY: Final = "workouts"
WAHOO_POWER_ZONES_KEY: Final = "power_zones"
WAHOO_USER_KEY: Final = "user"

GARMIN_SYNCED_AT_KEY: Final = "synced_at"
GARMIN_FRESHNESS_KEY: Final = "source_freshness"
GARMIN_FETCHED_AT_KEY: Final = "fetched_at"
GARMIN_ACTIVITIES_SECTION: Final = "activities"
GARMIN_WEIGHT_SECTION: Final = "weight"
GARMIN_BODY_BATTERY_SECTION: Final = "body_battery"
GARMIN_MORNING_BATTERY_KEY: Final = "morning_body_battery"
GARMIN_MORNING_ATTEMPTED_AT_KEY: Final = "attempted_at"
GARMIN_MORNING_ERROR_KEY: Final = "error"


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One provider row or health section, unsanitized, ready for storage."""

    record_kind: str
    source_record_id: str
    payload: Mapping[str, Any]
    mapper_version: int
    # When the row was fetched; None means the ingest's own retrieval time.
    retrieved_at: datetime | None = None
    # ISO day the row belongs to, for windowed reads; None when it has no day.
    observed_on: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """A mapped activity with its athlete-local date and mapper version."""

    record: ActivityRecord
    local_date: date
    mapper_version: int
    # When the row was fetched; None means the ingest's own retrieval time.
    retrieved_at: datetime | None = None


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
                ATHLETE_RECORD_KIND,
                ATHLETE_RECORD_ID,
                athlete,
                INTERVALS_WELLNESS_VERSION,
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


def garmin_section_retrieved_at(
    payload: Mapping[str, Any], section: str, *, zone: tzinfo
) -> datetime | None:
    """Return when one Garmin section was fetched, or None when that is unknown.

    The section's own source-freshness time wins over the payload's sync time,
    so a section retained from an earlier read keeps that read's time. Body
    Battery also takes the morning refresh, which merges new records without
    advancing the payload's sync time; a failed morning attempt does not count.
    """
    freshness = _mapping(_mapping(payload.get(GARMIN_FRESHNESS_KEY)).get(section))
    section_time = parse_provider_datetime(
        freshness.get(GARMIN_FETCHED_AT_KEY), zone
    ) or parse_provider_datetime(payload.get(GARMIN_SYNCED_AT_KEY), zone)
    if section != GARMIN_BODY_BATTERY_SECTION:
        return section_time
    morning = _mapping(payload.get(GARMIN_MORNING_BATTERY_KEY))
    if GARMIN_MORNING_ERROR_KEY in morning:
        return section_time
    attempted = parse_provider_datetime(
        morning.get(GARMIN_MORNING_ATTEMPTED_AT_KEY), zone
    )
    if attempted is None or (section_time is not None and section_time >= attempted):
        return section_time
    return attempted


def garmin_payload_retrieved_at(payload: object, *, zone: tzinfo) -> datetime | None:
    """Return the latest time any part of a stored Garmin payload was fetched."""
    if not isinstance(payload, Mapping):
        return None
    sections = (GARMIN_ACTIVITIES_SECTION, *GARMIN_HEALTH_SECTION_NAMES)
    times = [
        time
        for time in (
            parse_provider_datetime(payload.get(GARMIN_SYNCED_AT_KEY), zone),
            *(
                garmin_section_retrieved_at(payload, section, zone=zone)
                for section in sections
            ),
        )
        if time is not None
    ]
    return max(times, default=None)


def garmin_ingest_plan(payload: object, *, zone: tzinfo) -> IngestPlan:
    """Plan the canonical rows of one stored Garmin payload.

    Every section is mapped with its own fetch time. A section whose fetch time
    is unknown is left out.
    """
    if not isinstance(payload, Mapping):
        return IngestPlan(provider=ProviderId.GARMIN)
    activity_rows: list[ActivityItem] = []
    raw_records: list[RawRecord] = []
    skipped = 0
    present: set[str] = set()
    activities_at = garmin_section_retrieved_at(
        payload, GARMIN_ACTIVITIES_SECTION, zone=zone
    )
    if activities_at is not None:
        activity_rows, raw_records, skipped, present = _activity_batch(
            payload.get(GARMIN_ACTIVITIES_SECTION),
            id_key=GARMIN_ACTIVITY_ID_KEY,
            mapper=lambda rows: map_garmin_activities(
                rows, zone=zone, retrieved_at=activities_at
            ),
            mapper_version=GARMIN_ACTIVITY_VERSION,
            zone=zone,
            retrieved_at=activities_at,
        )
    raw_records.extend(_garmin_section_records(payload, zone=zone))
    observations: list[ObservationItem] = []
    for name in GARMIN_HEALTH_SECTION_NAMES:
        section_at = garmin_section_retrieved_at(payload, name, zone=zone)
        if section_at is None:
            continue
        # Each element is mapped as stored, so re-projection rebuilds the same rows.
        for section in WEIGHT_SECTIONS if name == GARMIN_WEIGHT_SECTION else (name,):
            for item in split_section(payload.get(section)):
                if item.value is None:
                    continue
                health = map_garmin_health(
                    wrapped(section, item), zone=zone, retrieved_at=section_at
                )
                observations.extend(
                    ObservationItem(observation, GARMIN_HEALTH_VERSION)
                    for observation in health.records
                )
    return IngestPlan(
        provider=ProviderId.GARMIN,
        raw_records=tuple(raw_records),
        activities=tuple(activity_rows),
        observations=tuple(observations),
        present_activity_ids=frozenset(present),
        skipped_invalid=skipped,
    )


def _garmin_section_records(
    payload: Mapping[str, Any], *, zone: tzinfo
) -> Iterator[RawRecord]:
    """Yield one raw record per element of each Garmin section the payload carries.

    The stored object is the exact mapper input of that element, so re-projection
    rebuilds its rows. A section without a fetch time is left out.
    """
    for section in sorted(GARMIN_ITEM_SECTIONS):
        value = payload.get(section)
        if value is None:
            continue
        # The weight aliases are one fetch and share the weight section's time.
        stamp_section = GARMIN_WEIGHT_SECTION if section in WEIGHT_SECTIONS else section
        section_at = garmin_section_retrieved_at(payload, stamp_section, zone=zone)
        if section_at is None:
            continue
        for item in split_section(value):
            yield RawRecord(
                HEALTH_RECORD_KIND,
                record_id(section, item.key),
                wrapped(section, item),
                GARMIN_HEALTH_VERSION,
                retrieved_at=section_at,
                observed_on=item.observed_on,
            )


def wahoo_payload_retrieved_at(payload: object, *, zone: tzinfo) -> datetime | None:
    """Return when a Wahoo payload was fetched, or None when it carries no usable time."""
    if not isinstance(payload, Mapping):
        return None
    return parse_provider_datetime(payload.get(WAHOO_SYNCED_AT_KEY), zone)


def wahoo_ingest_plan(payload: object, *, zone: tzinfo) -> IngestPlan:
    """Plan the canonical rows of one fetched Wahoo payload.

    The payload is ``{"synced_at": <ISO time>, "workouts": [<workout rows>]}``. It
    may also carry ``"power_zones"`` and ``"user"`` when those scopes were granted
    and fetched. An absent key means "not fetched", so earlier threshold rows stay.
    Without a usable fetch time nothing is planned, so no row is ever stamped with
    an invented time. A payload whose workout list is not a list plans nothing.
    """
    retrieved_at = wahoo_payload_retrieved_at(payload, zone=zone)
    if retrieved_at is None or not isinstance(payload, Mapping):
        return IngestPlan(provider=ProviderId.WAHOO)
    items, raw_records, skipped, present = _activity_batch(
        payload.get(WAHOO_WORKOUTS_KEY),
        id_key=WAHOO_ACTIVITY_ID_KEY,
        mapper=lambda rows: map_wahoo_activities(
            rows, zone=zone, retrieved_at=retrieved_at
        ),
        mapper_version=WAHOO_ACTIVITY_VERSION,
        zone=zone,
        retrieved_at=retrieved_at,
        stored=raw_workout_for_storage,
    )
    threshold_raw, threshold_observations, threshold_skipped = _wahoo_threshold_items(
        payload, zone=zone, retrieved_at=retrieved_at
    )
    return IngestPlan(
        provider=ProviderId.WAHOO,
        raw_records=tuple(raw_records) + threshold_raw,
        activities=tuple(items),
        observations=threshold_observations,
        present_activity_ids=frozenset(present),
        skipped_invalid=skipped + threshold_skipped,
    )


def _wahoo_threshold_items(
    payload: Mapping[str, Any], *, zone: tzinfo, retrieved_at: datetime
) -> tuple[tuple[RawRecord, ...], tuple[ObservationItem, ...], int]:
    """Return the raw rows, observations and skipped count of the fetched threshold data.

    Only the newest zone set of each family is stored, the rows the mapper reads, so
    re-mapping one stored row reproduces its observation.
    """
    rows = payload.get(WAHOO_POWER_ZONES_KEY)
    user = payload.get(WAHOO_USER_KEY)
    if rows is None and user is None:
        return (), (), 0
    mapped = map_wahoo_threshold_payload(
        rows, user, zone=zone, retrieved_at=retrieved_at
    )
    raw: list[RawRecord] = []
    if rows is not None:
        chosen, _selection_issues = select_power_zone_sets(rows, zone=zone)
        raw.extend(
            RawRecord(
                WAHOO_POWER_ZONES_RECORD_KIND,
                zone_set.record_id,
                zone_set.row,
                WAHOO_THRESHOLD_VERSION,
                retrieved_at=retrieved_at,
            )
            for zone_set in chosen
        )
    if isinstance(user, Mapping):
        raw.append(
            RawRecord(
                WAHOO_USER_RECORD_KIND,
                WAHOO_USER_RECORD_ID,
                user,
                WAHOO_THRESHOLD_VERSION,
                retrieved_at=retrieved_at,
            )
        )
    observations = tuple(
        ObservationItem(observation, WAHOO_THRESHOLD_VERSION)
        for observation in mapped.records
    )
    return tuple(raw), observations, len(mapped.issues)


def intervals_snapshot_ingest_plan(
    snapshot: Mapping[str, Any], *, zone: tzinfo
) -> IngestPlan:
    """Plan the Intervals.icu rows of one stored snapshot for the backfill.

    A snapshot without a sync time or without a ``raw_provider_data`` block has no
    mapper input. Its ``recent_activities`` fallback is a compact read model, so it
    is not mapped and counts as one invalid row. A snapshot stored without its
    activity sections (``intervals_snapshot_is_stripped``) plans only what it still
    carries; with nothing left to map it plans nothing and counts no invalid row.
    """
    retrieved_at = stored_retrieved_at(snapshot, zone=zone)
    raw = snapshot.get("raw_provider_data")
    if intervals_snapshot_is_stripped(snapshot) and not isinstance(raw, Mapping):
        return IngestPlan(provider=ProviderId.INTERVALS)
    if retrieved_at is None or not isinstance(raw, Mapping):
        return IngestPlan(provider=ProviderId.INTERVALS, skipped_invalid=1)
    return intervals_ingest_plan(raw, zone=zone, retrieved_at=retrieved_at)


_MAPPER_VERSIONS: Final[dict[tuple[str, str], int]] = {
    (ProviderId.INTERVALS.value, ACTIVITY_RECORD_KIND): INTERVALS_ACTIVITY_VERSION,
    (ProviderId.INTERVALS.value, WELLNESS_RECORD_KIND): INTERVALS_WELLNESS_VERSION,
    (ProviderId.INTERVALS.value, ATHLETE_RECORD_KIND): INTERVALS_WELLNESS_VERSION,
    (ProviderId.GARMIN.value, ACTIVITY_RECORD_KIND): GARMIN_ACTIVITY_VERSION,
    (ProviderId.GARMIN.value, HEALTH_RECORD_KIND): GARMIN_HEALTH_VERSION,
    (ProviderId.WAHOO.value, ACTIVITY_RECORD_KIND): WAHOO_ACTIVITY_VERSION,
    (ProviderId.WAHOO.value, WAHOO_POWER_ZONES_RECORD_KIND): WAHOO_THRESHOLD_VERSION,
    (ProviderId.WAHOO.value, WAHOO_USER_RECORD_KIND): WAHOO_THRESHOLD_VERSION,
}


def reprojection_mapper_version(provider: str, record_kind: str) -> int | None:
    """Return the current mapper version of one raw record kind, or None when it has no mapper."""
    return _MAPPER_VERSIONS.get((provider, record_kind))


def current_mapper_versions() -> dict[str, int]:
    """Return every current mapper version, keyed by ``provider.record_kind``."""
    return {
        f"{provider}.{kind}": version
        for (provider, kind), version in sorted(_MAPPER_VERSIONS.items())
    }


_OBSERVATION_RECORD_KINDS: Final = frozenset(
    {
        WELLNESS_RECORD_KIND,
        ATHLETE_RECORD_KIND,
        HEALTH_RECORD_KIND,
        WAHOO_POWER_ZONES_RECORD_KIND,
        WAHOO_USER_RECORD_KIND,
    }
)


def current_observation_mapper_versions() -> dict[str, int]:
    """Return the current mapper version of each provider's observations, by provider.

    Observations carry no state column, so a table row is current only when its
    ``mapper_version`` equals the version returned here for its provider.
    """
    return observation_mapper_versions(current_mapper_versions())


def observation_mapper_versions(versions: Mapping[str, Any]) -> dict[str, int]:
    """Return the observation mapper version of each provider in ``versions``.

    ``versions`` is keyed by ``provider.record_kind`` as ``current_mapper_versions``
    returns it; keys of other record kinds and non-integer values are ignored.
    """
    result: dict[str, int] = {}
    for key, version in sorted(versions.items()):
        provider, _, kind = key.partition(".")
        if (
            kind in _OBSERVATION_RECORD_KINDS
            and isinstance(version, int)
            and not isinstance(version, bool)
        ):
            result[provider] = version
    return result


def reprojection_plan(raw_row: Mapping[str, Any], *, zone: tzinfo) -> IngestPlan | None:
    """Plan the canonical rows that one stored raw record projects to today.

    The stored payload and its fetch time are the only inputs, so the result equals
    what the original ingest produced under the same mapper version. Returns None
    when the record kind has no mapper. A row whose payload or fetch time is unusable
    counts as one invalid row.
    """
    provider = ProviderId(raw_row["provider"])
    kind = str(raw_row["record_kind"])
    if reprojection_mapper_version(provider.value, kind) is None:
        return None
    fetched = parse_provider_datetime(raw_row["fetched_at"], zone)
    payload = _stored_payload(raw_row["payload"])
    if fetched is None or payload is None:
        return IngestPlan(provider=provider, skipped_invalid=1)
    if kind == ACTIVITY_RECORD_KIND:
        return _reprojected_activities(provider, payload, zone=zone, fetched=fetched)
    if kind == WELLNESS_RECORD_KIND:
        wellness = map_intervals_wellness([payload], retrieved_at=fetched)
        return IngestPlan(
            provider=provider,
            observations=tuple(
                ObservationItem(observation, INTERVALS_WELLNESS_VERSION)
                for observation in wellness.records
            ),
        )
    if kind == ATHLETE_RECORD_KIND:
        thresholds = map_intervals_athlete_thresholds(
            payload, observed_on=local_date(fetched, zone), retrieved_at=fetched
        )
        return IngestPlan(
            provider=provider,
            observations=tuple(
                ObservationItem(observation, INTERVALS_WELLNESS_VERSION)
                for observation in thresholds.records
            ),
        )
    if kind == WAHOO_POWER_ZONES_RECORD_KIND:
        zones = map_wahoo_power_zones([payload], zone=zone, retrieved_at=fetched)
        return _threshold_observation_plan(provider, zones)
    if kind == WAHOO_USER_RECORD_KIND:
        profile = map_wahoo_user(
            payload, observed_on=local_date(fetched, zone), retrieved_at=fetched
        )
        return _threshold_observation_plan(provider, profile)
    return _reprojected_health(
        provider, str(raw_row["source_record_id"]), payload, zone, fetched
    )


def _threshold_observation_plan(
    provider: ProviderId, mapped: MappingResult[Observation]
) -> IngestPlan:
    """Return the observations of one re-mapped Wahoo threshold row."""
    return IngestPlan(
        provider=provider,
        observations=tuple(
            ObservationItem(observation, WAHOO_THRESHOLD_VERSION)
            for observation in mapped.records
        ),
        skipped_invalid=len(mapped.issues),
    )


def _reprojected_activities(
    provider: ProviderId, payload: Mapping[str, Any], *, zone: tzinfo, fetched: datetime
) -> IngestPlan:
    """Re-map one stored activity row with the same mapper and fetch time as its ingest."""
    if provider is ProviderId.INTERVALS:
        items, _raw, skipped, _present = _activity_batch(
            [payload],
            id_key=INTERVALS_ACTIVITY_ID_KEY,
            mapper=lambda rows: map_intervals_activities(
                rows, zone=zone, retrieved_at=fetched
            ),
            mapper_version=INTERVALS_ACTIVITY_VERSION,
            zone=zone,
            retrieved_at=fetched,
        )
    elif provider is ProviderId.WAHOO:
        items, _raw, skipped, _present = _activity_batch(
            [payload],
            id_key=WAHOO_ACTIVITY_ID_KEY,
            mapper=lambda rows: map_wahoo_activities(
                rows, zone=zone, retrieved_at=fetched
            ),
            mapper_version=WAHOO_ACTIVITY_VERSION,
            zone=zone,
            retrieved_at=fetched,
        )
    else:
        items, _raw, skipped, _present = _activity_batch(
            [payload],
            id_key=GARMIN_ACTIVITY_ID_KEY,
            mapper=lambda rows: map_garmin_activities(
                rows, zone=zone, retrieved_at=fetched
            ),
            mapper_version=GARMIN_ACTIVITY_VERSION,
            zone=zone,
            retrieved_at=fetched,
        )
    return IngestPlan(
        provider=provider, activities=tuple(items), skipped_invalid=skipped
    )


def _reprojected_health(
    provider: ProviderId,
    section_name: str,
    payload: Mapping[str, Any],
    zone: tzinfo,
    fetched: datetime,
) -> IngestPlan:
    """Re-map one stored health element, which holds the exact mapper input.

    A section no health mapper reads (such as ``activity_matches``) projects to nothing.
    """
    section = section_of(section_name)
    mapped = GARMIN_HEALTH_SECTION_NAMES + WEIGHT_SECTIONS
    sections = {key: value for key, value in payload.items() if key in mapped}
    if section not in mapped:
        return IngestPlan(provider=provider)
    if not sections:
        return IngestPlan(provider=provider, skipped_invalid=1)
    health = map_garmin_health(sections, zone=zone, retrieved_at=fetched)
    return IngestPlan(
        provider=provider,
        observations=tuple(
            ObservationItem(observation, GARMIN_HEALTH_VERSION)
            for observation in health.records
        ),
    )


def _stored_payload(text: object) -> dict[str, Any] | None:
    """Decode a stored canonical JSON payload; only an object is a usable record."""
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _activity_batch(
    rows: object,
    *,
    id_key: str,
    mapper: Callable[[list[Any]], MappingResult[ActivityRecord]],
    mapper_version: int,
    zone: tzinfo,
    retrieved_at: datetime | None = None,
    stored: Callable[[Any], Any] | None = None,
) -> tuple[list[ActivityItem], list[RawRecord], int, set[str]]:
    """Map activity rows one by one so each invalid row is counted on its own.

    Every row with a usable identifier is reported as present, even when it does
    not map, so a full-window deletion never removes a record that the provider
    still returned. ``stored`` turns a row into the payload kept in the raw record;
    the mapping itself always reads the unchanged row.
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
        raw_records.append(
            RawRecord(
                ACTIVITY_RECORD_KIND,
                source_id,
                row if stored is None else stored(row),
                mapper_version,
                retrieved_at=retrieved_at,
                observed_on=local_date(record.started_at, zone).isoformat(),
            )
        )
        items.append(
            ActivityItem(
                record=record,
                local_date=local_date(record.started_at, zone),
                mapper_version=mapper_version,
                retrieved_at=retrieved_at,
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
