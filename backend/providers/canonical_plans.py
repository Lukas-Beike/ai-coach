"""Pure plans that turn stored provider payloads into canonical ingest rows.

The plans call the provider mappers and never write. A row that maps to no
record is skipped and counted, so one malformed row never blocks the rest of a
payload. Raw records keep the provider rows as fetched; the sync layer sanitizes
them before they are stored. Activities are mapped from the full raw rows, not
from the compact read model.

A Garmin payload keeps sections from earlier reads when a refresh fails or skips
them. Each Garmin section is therefore stamped with the time it was fetched, not
with the payload's latest sync time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.domain_records import (
    CategoricalObservation,
    GearActivityLink,
    GearItem,
    SleepPeriod,
    ZoneConfiguration,
)
from backend.canonical.garmin_payload import ITEM_SECTIONS as GARMIN_ITEM_SECTIONS
from backend.canonical.garmin_payload import dedicated_activity_rows
from backend.canonical.local_time import (
    local_date,
    parse_provider_datetime,
    wall_time,
)
from backend.canonical.mapping import MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.section_items import (
    SectionItem,
    key_of,
    record_id,
    section_of,
    split_section,
    unwrapped,
    wrapped,
)
from backend.canonical.vocabulary import ProviderId
from backend.providers.garmin_activity_mapping import (
    MAPPER_VERSION as GARMIN_ACTIVITY_VERSION,
)
from backend.providers.garmin_activity_mapping import (
    map_garmin_activities,
    merge_training_load_rows,
)
from backend.providers.garmin_gear_mapping import map_garmin_gear
from backend.providers.garmin_health_mapping import (
    GARMIN_HEALTH_SECTION_NAMES,
    GARMIN_PERFORMANCE_HISTORY_SECTION,
    map_garmin_health,
)
from backend.providers.garmin_health_mapping import (
    MAPPER_VERSION as GARMIN_HEALTH_VERSION,
)
from backend.providers.garmin_status_mapping import (
    STATUS_SECTIONS as GARMIN_STATUS_SECTIONS,
)
from backend.providers.garmin_status_mapping import map_garmin_status_codes
from backend.providers.garmin_training_mapping import morning_readiness
from backend.providers.garmin_weight_walk import WEIGHT_SECTIONS
from backend.providers.garmin_zone_mapping import map_garmin_heart_rate_zones
from backend.providers.sleep_period_mapping import map_sleep_periods
from backend.providers.wahoo_activity_mapping import (
    MAPPER_VERSION as WAHOO_ACTIVITY_VERSION,
)
from backend.providers.wahoo_activity_mapping import (
    map_wahoo_activities,
    raw_workout_for_storage,
    wahoo_workout_id,
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
HEALTH_RECORD_KIND: Final = "health"
WAHOO_POWER_ZONES_RECORD_KIND: Final = "power_zones"
WAHOO_USER_RECORD_KIND: Final = "user"

MAX_RECORD_ID_LENGTH: Final = 256
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
# Dedicated training-load rows merged into the activities before they are stored.
GARMIN_TRAINING_LOAD_SECTION: Final = "training_load_activities"
GARMIN_WEIGHT_SECTION: Final = "weight"
# The rank of each Garmin health section on a natural key two sections share,
# in ``GARMIN_HEALTH_SECTION_NAMES`` order (the order the live ingest keeps inside
# one payload); the weight aliases share the weight section's rank, and the
# last-ranked section is the fill-only performance history (#2782).
GARMIN_SECTION_RANKS: Final[Mapping[str, int]] = {
    alias: rank
    for rank, name in enumerate(GARMIN_HEALTH_SECTION_NAMES)
    for alias in (WEIGHT_SECTIONS if name == GARMIN_WEIGHT_SECTION else (name,))
}
GARMIN_BODY_BATTERY_SECTION: Final = "body_battery"
GARMIN_MORNING_BATTERY_KEY: Final = "morning_body_battery"
GARMIN_MORNING_ATTEMPTED_AT_KEY: Final = "attempted_at"
GARMIN_MORNING_ERROR_KEY: Final = "error"
GARMIN_SLEEP_SECTION: Final = "sleep"
GARMIN_GEAR_SECTION: Final = "gear"
GARMIN_HEART_RATE_ZONES_SECTION: Final = "heart_rate_zones"


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
    """A mapped activity with the local date it was lived on and its mapper version."""

    record: ActivityRecord
    local_date: date
    mapper_version: int
    # When the row was fetched; None means the ingest's own retrieval time.
    retrieved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ObservationItem:
    observation: Observation
    mapper_version: int
    # A fill-only value never replaces a stored value of another source record:
    # the accumulated Garmin performance history yields to dedicated sections.
    fill_only: bool = False
    # Source record id of the raw record whose projection emits the observation,
    # or None when that is not known exactly; an unowned row is never retired.
    owner: str | None = None
    # The rank of each section of the provider on a shared natural key
    # (``GARMIN_SECTION_RANKS``); None leaves the key's precedence to the writer.
    ranks: Mapping[str, int] | None = None


@dataclass(frozen=True, slots=True)
class DomainBatch:
    """The sleep, status, zone, gear and power curve rows one raw record projects to.

    Writing a batch replaces every row of ``source_record_id``: rows it no longer
    holds are retired. The records' provenance names the same source record id.
    A producer emits a batch, empty when nothing maps, for every raw record of a
    kind that projects domain rows, so a corrected record retires its old rows.
    """

    source_record_id: str
    mapper_version: int
    sleep_periods: tuple[SleepPeriod, ...] = ()
    categorical: tuple[CategoricalObservation, ...] = ()
    zones: tuple[ZoneConfiguration, ...] = ()
    gear_items: tuple[GearItem, ...] = ()
    gear_links: tuple[GearActivityLink, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.sleep_periods
            or self.categorical
            or self.zones
            or self.gear_items
            or self.gear_links
        )


@dataclass(frozen=True, slots=True)
class IngestPlan:
    """Everything one fetched payload contributes to the canonical tables.

    ``domain_batches`` hold one batch per raw record that projects to domain rows;
    each batch's source record is among ``raw_records`` of an ingest plan.
    ``withdrawn_activity_ids`` name listed activities that are no recording yet;
    a stored copy of one is tombstoned only while it holds no measured value
    either, and a later recording revives it.
    ``observation_owners`` map each raw record whose observations the plan maps
    completely to the ISO day it describes: a wellness day, a dated element's
    day, or else the local day of its fetch, which dateless snapshot records
    (athlete, profile, a whole Garmin section) date their values with. A stored
    observation the record owns on that day, or on a day the record still
    emits, is retired when the plan no longer emits it; values of other days
    are history and stay. A raw record the plan does not carry, such as a section
    that failed to load, retires nothing.
    """

    provider: ProviderId
    raw_records: tuple[RawRecord, ...] = ()
    activities: tuple[ActivityItem, ...] = ()
    observations: tuple[ObservationItem, ...] = ()
    present_activity_ids: frozenset[str] = field(default_factory=frozenset)
    withdrawn_activity_ids: frozenset[str] = field(default_factory=frozenset)
    skipped_invalid: int = 0
    domain_batches: tuple[DomainBatch, ...] = ()
    observation_owners: Mapping[str, str] = field(default_factory=dict)
    # The plan read an activity list in which every row carried a usable id, so
    # ``present_activity_ids`` names every activity the provider returned and a
    # deletion window may be applied.
    activity_ids_complete: bool = False


def _owned_by(observation: Observation, owners: Collection[str]) -> str | None:
    """Return the observation's source record id when it is one of ``owners``."""
    source_id = observation.provenance.source_record_id
    return source_id if source_id in owners else None


def _garmin_batch(
    section: str,
    source_id: str,
    element: object,
    *,
    zone: tzinfo,
    retrieved_at: datetime,
) -> DomainBatch | None:
    """Return the domain rows of one Garmin section element, or None for a section without any."""
    if section in GARMIN_STATUS_SECTIONS:
        return DomainBatch(
            source_id,
            GARMIN_HEALTH_VERSION,
            categorical=map_garmin_status_codes(
                section, element, source_record_id=source_id, retrieved_at=retrieved_at
            ),
        )
    if section == GARMIN_GEAR_SECTION:
        items, links = map_garmin_gear(
            element, source_record_id=source_id, retrieved_at=retrieved_at
        )
        return DomainBatch(
            source_id, GARMIN_HEALTH_VERSION, gear_items=items, gear_links=links
        )
    if section == GARMIN_HEART_RATE_ZONES_SECTION:
        return DomainBatch(
            source_id,
            GARMIN_HEALTH_VERSION,
            zones=map_garmin_heart_rate_zones(
                element,
                source_record_id=source_id,
                retrieved_at=retrieved_at,
                zone=zone,
            ),
        )
    if section != GARMIN_SLEEP_SECTION:
        return None
    return DomainBatch(
        source_id,
        GARMIN_HEALTH_VERSION,
        sleep_periods=map_sleep_periods(
            element,
            provider=ProviderId.GARMIN,
            source_record_id=source_id,
            retrieved_at=retrieved_at,
            zone=zone,
        ),
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


# Returns the stored dedicated training-load row of one Garmin activity id.
type TrainingLoadLookup = Callable[[str], Any]
# The stored elements of a Garmin section on one day: (section, day) -> elements.
type DayItemsLookup = Callable[[str, str], Sequence[SectionItem]]
# Sections whose mapper keeps one reading a day, the wake-up one. Each reading is
# stored as its own element, so the day's reading is chosen across the day's
# elements and only that element emits observations (#2844).
GARMIN_MORNING_SECTIONS: Final = frozenset({"readiness", "training_readiness_history"})


def _garmin_activity_mapper(
    *,
    zone: tzinfo,
    retrieved_at: datetime,
    training_loads: TrainingLoadLookup | None,
    payload_loads: object = None,
) -> Callable[[list[Any]], MappingResult[ActivityRecord]]:
    """Map Garmin activity rows with their dedicated training-load values merged in.

    The stored, accumulated dedicated rows (``training_loads``) come first and the
    rows of the same payload win, so the result does not depend on which sections
    a sync fetched. The raw activity row itself stays as the provider sent it.
    """

    def mapper(rows: list[Any]) -> MappingResult[ActivityRecord]:
        loads: list[Any] = []
        if training_loads is not None:
            for row in rows:
                identity = _row_id(row, GARMIN_ACTIVITY_ID_KEY)
                stored = None if identity is None else training_loads(identity)
                if stored is not None:
                    loads.append(stored)
        if isinstance(payload_loads, list):
            loads.extend(payload_loads)
        return map_garmin_activities(
            merge_training_load_rows(rows, loads),
            zone=zone,
            retrieved_at=retrieved_at,
        )

    return mapper


def garmin_ingest_plan(
    payload: object,
    *,
    zone: tzinfo,
    training_loads: TrainingLoadLookup | None = None,
) -> IngestPlan:
    """Plan the canonical rows of one stored Garmin payload.

    Every section is mapped with its own fetch time. A section whose fetch time
    is unknown is left out. ``training_loads`` returns the stored dedicated
    training-load row of an activity id; the payload's own rows win over it.
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
            mapper=_garmin_activity_mapper(
                zone=zone,
                retrieved_at=activities_at,
                training_loads=training_loads,
                payload_loads=dedicated_activity_rows(payload),
            ),
            mapper_version=GARMIN_ACTIVITY_VERSION,
            zone=zone,
            retrieved_at=activities_at,
        )
    raw_records.extend(_garmin_section_records(payload, zone=zone))
    # A reading that does not keep its day's value keeps no level either: its
    # empty batch retires what it wrote before (#2844).
    unchosen = _garmin_unchosen_readings(payload)
    batches = tuple(
        batch
        for raw in raw_records
        if raw.record_kind == HEALTH_RECORD_KIND
        and (
            batch := DomainBatch(raw.source_record_id, GARMIN_HEALTH_VERSION)
            if raw.source_record_id in unchosen
            else _stored_garmin_batch(
                raw.source_record_id, raw.payload, zone=zone, fetched=raw.retrieved_at
            )
        )
        is not None
    )
    observations: list[ObservationItem] = []
    raw_ids = {raw.source_record_id for raw in raw_records}
    owners: dict[str, str] = {}
    for name in GARMIN_HEALTH_SECTION_NAMES:
        section_at = garmin_section_retrieved_at(payload, name, zone=zone)
        if section_at is None:
            continue
        for section in WEIGHT_SECTIONS if name == GARMIN_WEIGHT_SECTION else (name,):
            observations.extend(
                _garmin_section_observations(
                    section,
                    payload.get(section),
                    zone=zone,
                    retrieved_at=section_at,
                    raw_ids=raw_ids,
                    owners=owners,
                )
            )
    return IngestPlan(
        provider=ProviderId.GARMIN,
        raw_records=tuple(raw_records),
        activities=tuple(activity_rows),
        observations=tuple(observations),
        present_activity_ids=frozenset(present),
        activity_ids_complete=activities_at is not None
        and _ids_complete(
            payload.get(GARMIN_ACTIVITIES_SECTION), GARMIN_ACTIVITY_ID_KEY
        ),
        skipped_invalid=skipped,
        domain_batches=batches,
        observation_owners=owners,
    )


def _stored_garmin_batch(
    source_id: str,
    payload: Mapping[str, Any],
    *,
    zone: tzinfo,
    fetched: datetime | None,
) -> DomainBatch | None:
    """Return the domain rows of one stored Garmin health element, as its raw record holds it."""
    section = section_of(source_id)
    item = unwrapped(section, key_of(source_id), payload)
    if fetched is None or item is None:
        return None
    return _garmin_batch(
        section, source_id, item.value, zone=zone, retrieved_at=fetched
    )


def garmin_morning_keys(
    section: str, items: Sequence[SectionItem]
) -> frozenset[str] | None:
    """The keys of the elements that keep their day's reading; None keeps every element."""
    if section not in GARMIN_MORNING_SECTIONS:
        return None
    return frozenset(item.key for item in morning_readiness(items, _item_record))


def _item_record(item: SectionItem) -> Mapping[str, Any]:
    return item.value if isinstance(item.value, Mapping) else {}


def garmin_day_reading(
    source_id: str, payload: Mapping[str, Any], day_items: DayItemsLookup | None
) -> tuple[SectionItem, ...] | None:
    """The reading a stored morning-section element re-projects, chosen across its day.

    None when no choice applies (another section, no lookup, an undated element):
    the element maps itself. Otherwise the day's chosen stored reading, or an empty
    tuple when the day keeps none (only re-scores), so every reading of a day
    projects the same values whatever order the re-projection takes (#2844).
    """
    section = section_of(source_id)
    if section not in GARMIN_MORNING_SECTIONS or day_items is None:
        return None
    item = unwrapped(section, key_of(source_id), payload)
    if item is None or not item.observed_on:
        return None
    siblings = day_items(section, item.observed_on)
    keys = garmin_morning_keys(section, siblings) or frozenset()
    return tuple(sibling for sibling in siblings if sibling.key in keys)[:1]


def _garmin_unchosen_readings(payload: Mapping[str, Any]) -> frozenset[str]:
    """The record ids of the payload's readings that do not keep their day's value."""
    unchosen: set[str] = set()
    for section in GARMIN_MORNING_SECTIONS:
        items = split_section(payload[section]) if section in payload else []
        keys = garmin_morning_keys(section, items) or frozenset()
        unchosen.update(
            record_id(section, item.key) for item in items if item.key not in keys
        )
    return frozenset(unchosen)


def _garmin_section_observations(
    section: str,
    value: object,
    *,
    zone: tzinfo,
    retrieved_at: Any,
    raw_ids: Collection[str],
    owners: dict[str, str],
) -> Iterator[ObservationItem]:
    """Map each stored element as stored, so re-projection rebuilds the same rows.

    An element stored as a raw record of the plan owns its observations and is
    added to ``owners`` with its day; the observations of any other element have
    no owner.
    """
    items = split_section(value)
    morning = garmin_morning_keys(section, items)
    for item in items:
        element_id = record_id(section, item.key)
        owner = element_id if element_id in raw_ids else None
        if owner is not None:
            owners[owner] = _element_day(item.observed_on, retrieved_at, zone)
        if item.value is None or (morning is not None and item.key not in morning):
            continue
        health = map_garmin_health(
            wrapped(section, item), zone=zone, retrieved_at=retrieved_at
        )
        for observation in health.records:
            yield ObservationItem(
                observation,
                GARMIN_HEALTH_VERSION,
                fill_only=section == GARMIN_PERFORMANCE_HISTORY_SECTION,
                owner=owner,
                ranks=GARMIN_SECTION_RANKS,
            )


def _element_day(observed_on: str | None, fetched: datetime, zone: tzinfo) -> str:
    """Return an element's own day, or the local fetch day its values fall back to."""
    return observed_on or local_date(fetched, zone).isoformat()


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

    Wahoo lists a workout without a measured value before it processed the
    recording, and for a loaded plan that was never recorded. Such a workout has
    no value a duplicate rule can compare, so it is withdrawn instead of planned
    as an activity; once its summary arrives it is planned as usual. A workout
    whose summary offers a recording file, or a copy of the same id that
    carries values in the same payload, is never withdrawn.
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
    with_file = _wahoo_ids_with_file(payload.get(WAHOO_WORKOUTS_KEY))
    recorded = {
        item.record.activity_id for item in items if _wahoo_recorded(item.record)
    }
    # Each raw record was planned together with its activity, in the same order.
    # A copy with values wins over every empty copy of its id; the file only
    # keeps an id none of whose copies carries values yet.
    kept = [
        (raw, item)
        for raw, item in zip(raw_records, items, strict=True)
        if _wahoo_recorded(item.record)
        or (
            item.record.activity_id in with_file
            and item.record.activity_id not in recorded
        )
    ]
    withdrawn = {item.record.activity_id for item in items} - {
        item.record.activity_id for _raw, item in kept
    }
    threshold_raw, threshold_observations, threshold_skipped = _wahoo_threshold_items(
        payload, zone=zone, retrieved_at=retrieved_at
    )
    return IngestPlan(
        provider=ProviderId.WAHOO,
        raw_records=tuple(raw for raw, _item in kept) + threshold_raw,
        activities=tuple(item for _raw, item in kept),
        observations=threshold_observations,
        present_activity_ids=frozenset(present),
        activity_ids_complete=_ids_complete(
            payload.get(WAHOO_WORKOUTS_KEY), WAHOO_ACTIVITY_ID_KEY
        ),
        withdrawn_activity_ids=frozenset(withdrawn),
        skipped_invalid=skipped + threshold_skipped,
        observation_owners=dict.fromkeys(
            (raw.source_record_id for raw in threshold_raw),
            local_date(retrieved_at, zone).isoformat(),
        ),
    )


def _wahoo_ids_with_file(rows: object) -> set[str]:
    """Return the ids of listed workouts whose summary offers a recording file.

    A file is a recording even while the summary holds no value yet; its detail
    import needs the stored activity.
    """
    if not isinstance(rows, list):
        return set()
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        summary = row.get("workout_summary")
        file = summary.get("file") if isinstance(summary, Mapping) else None
        if not isinstance(file, Mapping) or not isinstance(file.get("url"), str):
            continue
        workout_id = wahoo_workout_id(row)
        if workout_id is not None:
            ids.add(workout_id)
    return ids


def _wahoo_recorded(record: ActivityRecord) -> bool:
    """Return True when a Wahoo workout carries a measured summary value."""
    return (
        record.duration_s is not None
        or bool(record.distance_m)
        or record.avg_hr is not None
        or record.avg_power is not None
        or record.load is not None
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
    # A threshold value names its raw record as its source record.
    raw_ids = {record.source_record_id for record in raw}
    observations = tuple(
        ObservationItem(
            observation, WAHOO_THRESHOLD_VERSION, owner=_owned_by(observation, raw_ids)
        )
        for observation in mapped.records
    )
    return tuple(raw), observations, len(mapped.issues)


_MAPPER_VERSIONS: Final[dict[tuple[str, str], int]] = {
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


def reprojection_plan(
    raw_row: Mapping[str, Any],
    *,
    zone: tzinfo,
    training_loads: TrainingLoadLookup | None = None,
    day_items: DayItemsLookup | None = None,
) -> IngestPlan | None:
    """Plan the canonical rows that one stored raw record projects to today.

    The stored payload and its fetch time are the inputs, plus, for a Garmin
    activity, its stored dedicated training-load row (``training_loads``), and for
    a reading of a ``GARMIN_MORNING_SECTIONS`` section the other stored readings of
    its day (``day_items``), so the result equals what an ingest produces under the
    same mapper version. Returns None
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
        return _reprojected_activities(
            provider,
            payload,
            zone=zone,
            fetched=fetched,
            training_loads=training_loads,
        )
    source_id = str(raw_row["source_record_id"])
    if kind == WAHOO_POWER_ZONES_RECORD_KIND:
        zones = map_wahoo_power_zones([payload], zone=zone, retrieved_at=fetched)
        return _threshold_observation_plan(
            provider, zones, source_id, local_date(fetched, zone).isoformat()
        )
    if kind == WAHOO_USER_RECORD_KIND:
        profile = map_wahoo_user(
            payload, observed_on=local_date(fetched, zone), retrieved_at=fetched
        )
        return _threshold_observation_plan(
            provider, profile, source_id, local_date(fetched, zone).isoformat()
        )
    return _reprojected_health(provider, source_id, payload, zone, fetched, day_items)


def _threshold_observation_plan(
    provider: ProviderId,
    mapped: MappingResult[Observation],
    source_id: str,
    day: str,
) -> IngestPlan:
    """Return the observations of one re-mapped Wahoo threshold row, which owns them."""
    return IngestPlan(
        provider=provider,
        observations=tuple(
            ObservationItem(observation, WAHOO_THRESHOLD_VERSION, owner=source_id)
            for observation in mapped.records
        ),
        skipped_invalid=len(mapped.issues),
        observation_owners={source_id: day},
    )


def _reprojected_activities(
    provider: ProviderId,
    payload: Mapping[str, Any],
    *,
    zone: tzinfo,
    fetched: datetime,
    training_loads: TrainingLoadLookup | None = None,
) -> IngestPlan:
    """Re-map one stored activity row with the same mapper and fetch time as its ingest."""
    if provider is ProviderId.WAHOO:
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
            mapper=_garmin_activity_mapper(
                zone=zone, retrieved_at=fetched, training_loads=training_loads
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
    day_items: DayItemsLookup | None = None,
) -> IngestPlan:
    """Re-map one stored health element, which holds the exact mapper input.

    A section neither the health mapper nor a domain mapper reads (such as
    ``activity_matches``) projects to nothing; ``gear`` projects domain rows only.
    """
    section = section_of(section_name)
    mapped = GARMIN_HEALTH_SECTION_NAMES + WEIGHT_SECTIONS
    sections = {key: value for key, value in payload.items() if key in mapped}
    batch = _stored_garmin_batch(section_name, payload, zone=zone, fetched=fetched)
    batches = () if batch is None else (batch,)
    if section not in mapped:
        return IngestPlan(provider=provider, domain_batches=batches)
    if not sections:
        return IngestPlan(provider=provider, skipped_invalid=1)
    item = unwrapped(section, key_of(section_name), payload)
    day = _element_day(item.observed_on if item else None, fetched, zone)
    owner = section_name
    choice = garmin_day_reading(section_name, payload, day_items)
    if choice is not None:
        # Every reading of a day projects the day's chosen reading, owned by it,
        # so no order of the re-projection leaves the day without its value; only
        # the chosen reading keeps its level (#2844).
        if not choice or choice[0].key != key_of(section_name):
            batches = ()
        sections = wrapped(section, choice[0]) if choice else {}
        owner = record_id(section, choice[0].key) if choice else section_name
    health = map_garmin_health(sections, zone=zone, retrieved_at=fetched)
    return IngestPlan(
        provider=provider,
        observations=tuple(
            ObservationItem(
                observation,
                GARMIN_HEALTH_VERSION,
                fill_only=section == GARMIN_PERFORMANCE_HISTORY_SECTION,
                owner=owner,
                ranks=GARMIN_SECTION_RANKS,
            )
            for observation in health.records
        ),
        domain_batches=batches,
        observation_owners={section_name: day},
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
        # The day the activity was lived: its own offset, else the athlete zone.
        day = wall_time(record.started_at, zone, record.local_offset_minutes).date()
        raw_records.append(
            RawRecord(
                ACTIVITY_RECORD_KIND,
                source_id,
                row if stored is None else stored(row),
                mapper_version,
                retrieved_at=retrieved_at,
                observed_on=day.isoformat(),
            )
        )
        items.append(
            ActivityItem(
                record=record,
                local_date=day,
                mapper_version=mapper_version,
                retrieved_at=retrieved_at,
            )
        )
    return items, raw_records, skipped, present


def _ids_complete(rows: object, key: str) -> bool:
    """Return whether ``rows`` is a list in which every row has a usable id."""
    return isinstance(rows, list) and all(_row_id(row, key) is not None for row in rows)


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
