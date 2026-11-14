"""Test-only plans and projections over Intervals.icu-shaped snapshots.

Intervals.icu is an output target and the application neither reads nor stores its
activities. Tests that need Intervals.icu-shaped records as input for
provider-neutral logic (session linking, source policy, performance inputs) build
them here from the test-only mappers next to this module.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, tzinfo
from typing import Any, Final
from unittest.mock import patch

from intervals_activity_stub import INTERVALS_LABEL, map_intervals_activities
from intervals_activity_stub import MAPPER_VERSION as INTERVALS_ACTIVITY_VERSION
from intervals_wellness_stub import MAPPER_VERSION as INTERVALS_WELLNESS_VERSION
from intervals_wellness_stub import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)
from intervals_zone_stub import map_intervals_zone_configurations

from backend.canonical.local_time import local_date, parse_provider_datetime
from backend.canonical.mapping import MappingIssue, MappingResult
from backend.canonical.vocabulary import ProviderId
from backend.providers import canonical_plans
from backend.providers.canonical_plans import (
    DomainBatch,
    IngestPlan,
    ObservationItem,
    RawRecord,
)
from backend.providers.sleep_period_mapping import map_sleep_periods
from backend.providers.snapshot_projection import ProjectedSnapshot, stored_retrieved_at

__all__ = [
    "ATHLETE_RECORD_ID",
    "INTERVALS_ACTIVITY_VERSION",
    "INTERVALS_LABEL",
    "INTERVALS_WELLNESS_VERSION",
    "WELLNESS_RECORD_KIND",
    "intervals_activity_rows",
    "intervals_ingest_plan",
    "intervals_snapshot_coverage",
    "intervals_snapshot_ingest_plan",
    "intervals_test_world",
    "project_intervals_snapshot",
]

ACTIVITY_RECORD_KIND: Final = canonical_plans.ACTIVITY_RECORD_KIND
WELLNESS_RECORD_KIND: Final = "wellness"
ATHLETE_RECORD_KIND: Final = "athlete"
ATHLETE_RECORD_ID: Final = "athlete"
_ID_KEY: Final = "id"
_ACTIVITIES_KEY: Final = "recent_activities"
_RAW_KEY: Final = "raw_provider_data"
_RAW_ACTIVITIES_KEY: Final = "activities"
_WELLNESS_KEY: Final = "recent_wellness"
_ATHLETE_KEY: Final = "athlete"


def intervals_ingest_plan(
    raw: object, *, zone: tzinfo, retrieved_at: datetime, power_curve: object = None
) -> IngestPlan:
    """Plan the canonical rows of one Intervals.icu-shaped ``raw_provider_data`` block.

    ``power_curve`` is accepted for call compatibility and ignored.
    """
    del power_curve
    if not isinstance(raw, Mapping):
        return IngestPlan(provider=ProviderId.INTERVALS)
    activity_rows, raw_records, skipped, present = canonical_plans._activity_batch(
        raw.get("activities"),
        id_key=_ID_KEY,
        mapper=lambda rows: map_intervals_activities(
            rows, zone=zone, retrieved_at=retrieved_at
        ),
        mapper_version=INTERVALS_ACTIVITY_VERSION,
        zone=zone,
    )
    observations: list[ObservationItem] = []
    batches: list[DomainBatch] = []
    owners: dict[str, str] = {}
    wellness_rows = raw.get("wellness")
    if isinstance(wellness_rows, list):
        valid_rows: list[Any] = []
        for row in wellness_rows:
            row_id = canonical_plans._row_id(row, _ID_KEY)
            if row_id is None:
                skipped += 1
                continue
            valid_rows.append(row)
            owners[row_id] = row_id
            raw_records.append(
                RawRecord(WELLNESS_RECORD_KIND, row_id, row, INTERVALS_WELLNESS_VERSION)
            )
            batches.append(
                DomainBatch(
                    row_id,
                    INTERVALS_WELLNESS_VERSION,
                    sleep_periods=map_sleep_periods(
                        row,
                        provider=ProviderId.INTERVALS,
                        source_record_id=row_id,
                        retrieved_at=retrieved_at,
                        zone=zone,
                    ),
                )
            )
        wellness = map_intervals_wellness(valid_rows, retrieved_at=retrieved_at)
        observations.extend(
            ObservationItem(
                observation,
                INTERVALS_WELLNESS_VERSION,
                owner=canonical_plans._owned_by(observation, owners),
            )
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
        owners[ATHLETE_RECORD_ID] = local_date(retrieved_at, zone).isoformat()
        observations.extend(
            ObservationItem(
                observation, INTERVALS_WELLNESS_VERSION, owner=ATHLETE_RECORD_ID
            )
            for observation in thresholds.records
        )
        batches.append(
            DomainBatch(
                ATHLETE_RECORD_ID,
                INTERVALS_WELLNESS_VERSION,
                zones=map_intervals_zone_configurations(
                    athlete,
                    source_record_id=ATHLETE_RECORD_ID,
                    retrieved_at=retrieved_at,
                ),
            )
        )
    elif athlete is not None:
        skipped += 1
    return IngestPlan(
        provider=ProviderId.INTERVALS,
        raw_records=tuple(raw_records),
        activities=tuple(activity_rows),
        observations=tuple(observations),
        present_activity_ids=frozenset(present),
        activity_ids_complete=canonical_plans._ids_complete(
            raw.get("activities"), _ID_KEY
        ),
        skipped_invalid=skipped,
        domain_batches=tuple(batches),
        observation_owners=owners,
    )


def intervals_snapshot_ingest_plan(
    snapshot: Mapping[str, Any], *, zone: tzinfo, include_power_curve: bool = True
) -> IngestPlan:
    """Plan the Intervals.icu-shaped rows of one stored snapshot."""
    del include_power_curve
    retrieved_at = stored_retrieved_at(snapshot, zone=zone)
    raw = snapshot.get(_RAW_KEY)
    if retrieved_at is None or not isinstance(raw, Mapping):
        return IngestPlan(provider=ProviderId.INTERVALS, skipped_invalid=1)
    return intervals_ingest_plan(raw, zone=zone, retrieved_at=retrieved_at)


def project_intervals_snapshot(
    snapshot: object, *, zone: tzinfo, retrieved_at: datetime
) -> ProjectedSnapshot:
    """Map a stored Intervals.icu-shaped snapshot to activities and observations."""
    if not isinstance(snapshot, Mapping):
        return MappingResult(), MappingResult()
    activities = map_intervals_activities(
        snapshot.get(_ACTIVITIES_KEY), zone=zone, retrieved_at=retrieved_at
    )
    wellness = map_intervals_wellness(
        snapshot.get(_WELLNESS_KEY), retrieved_at=retrieved_at
    )
    athlete = map_intervals_athlete_thresholds(
        snapshot.get(_ATHLETE_KEY),
        observed_on=local_date(retrieved_at, zone),
        retrieved_at=retrieved_at,
    )
    return activities, _merge((wellness, athlete))


def intervals_activity_rows(snapshot: object) -> tuple[dict[str, Any], ...]:
    """Return the raw activity rows of a stored Intervals.icu-shaped snapshot."""
    if not isinstance(snapshot, Mapping):
        return ()
    raw = snapshot.get(_RAW_KEY)
    rows = raw.get(_RAW_ACTIVITIES_KEY) if isinstance(raw, Mapping) else None
    if not isinstance(rows, list):
        rows = snapshot.get(_ACTIVITIES_KEY)
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def intervals_snapshot_coverage(snapshot: object, *, zone: tzinfo) -> Any:
    """Summarize a stored Intervals.icu-shaped snapshot, or None without a sync time."""
    from backend.canonical.coverage import summarize_provider

    stored_at = stored_retrieved_at(snapshot, zone=zone)
    if stored_at is None:
        return None
    activity_time = (
        stored_retrieved_at(
            {"synced_at": snapshot.get("activities_synced_at")}, zone=zone
        )
        if isinstance(snapshot, Mapping) and "activities_synced_at" in snapshot
        else stored_at
    )
    activities, _activity_observations = project_intervals_snapshot(
        snapshot, zone=zone, retrieved_at=activity_time or stored_at
    )
    _observation_activities, observations = project_intervals_snapshot(
        snapshot, zone=zone, retrieved_at=stored_at
    )
    return summarize_provider(
        ProviderId.INTERVALS,
        stored_at,
        activities,
        observations,
        activities_retrieved_at=activity_time,
        observations_retrieved_at=stored_at,
    )


def _merge[T](results: tuple[MappingResult[T], ...]) -> MappingResult[T]:
    records: list[T] = []
    issues: list[MappingIssue] = []
    for result in results:
        records.extend(result.records)
        issues.extend(result.issues)
    return MappingResult(records=tuple(records), issues=tuple(issues))


def intervals_reprojection_plan(
    raw_row: Mapping[str, Any], *, zone: tzinfo
) -> IngestPlan | None:
    """Plan the canonical rows a stored Intervals.icu raw record projects to."""
    kind = str(raw_row["record_kind"])
    fetched = parse_provider_datetime(raw_row["fetched_at"], zone)
    payload = canonical_plans._stored_payload(raw_row["payload"])
    provider = ProviderId.INTERVALS
    if fetched is None or payload is None:
        return IngestPlan(provider=provider, skipped_invalid=1)
    source_id = str(raw_row["source_record_id"])
    if kind == ACTIVITY_RECORD_KIND:
        items, _raw, skipped, _present = canonical_plans._activity_batch(
            [payload],
            id_key=_ID_KEY,
            mapper=lambda rows: map_intervals_activities(
                rows, zone=zone, retrieved_at=fetched
            ),
            mapper_version=INTERVALS_ACTIVITY_VERSION,
            zone=zone,
            retrieved_at=fetched,
        )
        return IngestPlan(
            provider=provider, activities=tuple(items), skipped_invalid=skipped
        )
    if kind == WELLNESS_RECORD_KIND:
        wellness = map_intervals_wellness([payload], retrieved_at=fetched)
        return IngestPlan(
            provider=provider,
            observations=tuple(
                ObservationItem(
                    observation, INTERVALS_WELLNESS_VERSION, owner=source_id
                )
                for observation in wellness.records
            ),
            observation_owners={source_id: source_id},
            domain_batches=(
                DomainBatch(
                    source_id,
                    INTERVALS_WELLNESS_VERSION,
                    sleep_periods=map_sleep_periods(
                        payload,
                        provider=provider,
                        source_record_id=source_id,
                        retrieved_at=fetched,
                        zone=zone,
                    ),
                ),
            ),
        )
    if kind == ATHLETE_RECORD_KIND:
        thresholds = map_intervals_athlete_thresholds(
            payload, observed_on=local_date(fetched, zone), retrieved_at=fetched
        )
        return IngestPlan(
            provider=provider,
            observations=tuple(
                ObservationItem(
                    observation, INTERVALS_WELLNESS_VERSION, owner=source_id
                )
                for observation in thresholds.records
            ),
            observation_owners={source_id: local_date(fetched, zone).isoformat()},
            domain_batches=(
                DomainBatch(
                    ATHLETE_RECORD_ID,
                    INTERVALS_WELLNESS_VERSION,
                    zones=map_intervals_zone_configurations(
                        payload,
                        source_record_id=ATHLETE_RECORD_ID,
                        retrieved_at=fetched,
                    ),
                ),
            ),
        )
    return None


@contextmanager
def intervals_test_world(*, bump: int = 0, coverage: bool = False) -> Iterator[None]:
    """Make the canonical layer treat Intervals.icu as a mapped provider again.

    The application does not map Intervals.icu records. Tests of the provider-neutral
    re-projection, version-window and read-selector logic use Intervals.icu-shaped
    records as one of several providers; inside this context the mapper table,
    the observation kinds, the re-projection plan and the persisted coverage
    providers include it, as before the retirement. ``bump`` raises the wellness
    and athlete mapper version, as a mapper change would. ``coverage`` also lists
    Intervals.icu among the providers with a persisted coverage summary.
    """
    wellness_version = INTERVALS_WELLNESS_VERSION + bump
    provider = ProviderId.INTERVALS.value
    versions = {
        **canonical_plans._MAPPER_VERSIONS,
        (provider, ACTIVITY_RECORD_KIND): INTERVALS_ACTIVITY_VERSION,
        (provider, WELLNESS_RECORD_KIND): wellness_version,
        (provider, ATHLETE_RECORD_KIND): wellness_version,
    }
    real_plan = canonical_plans.reprojection_plan

    def plan(
        raw_row: Mapping[str, Any],
        *,
        zone: tzinfo,
        training_loads: Any = None,
        day_items: Any = None,
    ) -> IngestPlan | None:
        if raw_row["provider"] == provider:
            return intervals_reprojection_plan(raw_row, zone=zone)
        return real_plan(
            raw_row, zone=zone, training_loads=training_loads, day_items=day_items
        )

    with (
        patch.object(
            sys.modules[__name__], "INTERVALS_WELLNESS_VERSION", wellness_version
        ),
        patch.dict(canonical_plans._MAPPER_VERSIONS, versions),
        patch.object(
            canonical_plans,
            "_OBSERVATION_RECORD_KINDS",
            canonical_plans._OBSERVATION_RECORD_KINDS
            | {WELLNESS_RECORD_KIND, ATHLETE_RECORD_KIND},
        ),
        patch("backend.sync.canonical_backfill.reprojection_plan", side_effect=plan),
        patch(
            "backend.sync.canonical_read_selector.CANONICAL_COVERAGE_PROVIDERS",
            (ProviderId.INTERVALS, ProviderId.GARMIN)
            if coverage
            else canonical_coverage_providers(),
        ),
    ):
        yield


def canonical_coverage_providers() -> tuple[ProviderId, ...]:
    from backend.sync.canonical_read_selector import CANONICAL_COVERAGE_PROVIDERS

    return CANONICAL_COVERAGE_PROVIDERS
