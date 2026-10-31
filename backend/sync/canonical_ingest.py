"""Provider-neutral use case that writes one fetched payload into the canonical tables.

The functions run inside the caller's unit of work, so the rows written here and
the legacy snapshot write commit or roll back together. They return counters
only and never commit or log provider content.

Deletion rule: only a full, non-incremental Intervals.icu window marks missing
activities deleted, and only inside that window. Partial or incremental fetches
and historical fetches never delete. Garmin payloads are merged rather than
replaced, so Garmin never deletes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from backend.activities.session_linking import link_activity_sessions
from backend.canonical.local_time import local_date
from backend.db import canonical_domain_store, canonical_store
from backend.db.canonical_domain_store import ReplaceResult
from backend.db.canonical_store import WriteOutcome
from backend.observability import sanitized_provider_payload
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    INTERVALS_POWER_CURVE_KEY,
    IngestPlan,
    garmin_ingest_plan,
    garmin_payload_retrieved_at,
    intervals_ingest_plan,
)
from backend.providers.snapshot_projection import stored_retrieved_at


@dataclass(slots=True)
class CanonicalIngestCounters:
    """How many canonical rows one ingest wrote, kept, or skipped."""

    written: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_invalid: int = 0
    deleted: int = 0
    linked: int = 0
    retired: int = 0

    def count(self, outcome: WriteOutcome) -> None:
        if outcome is WriteOutcome.WRITTEN:
            self.written += 1
        elif outcome is WriteOutcome.UPDATED:
            self.updated += 1
        else:
            self.unchanged += 1

    def add(self, result: ReplaceResult) -> None:
        self.written += result.written
        self.updated += result.updated
        self.unchanged += result.unchanged
        self.retired += result.retired

    def as_dict(self) -> dict[str, int]:
        return {
            "written": self.written,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_invalid": self.skipped_invalid,
            "deleted": self.deleted,
            "linked": self.linked,
            "retired": self.retired,
        }


DELETION_EDGE_MARGIN = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class DeletionWindow:
    """Inclusive athlete-local date range in which a full fetch may delete."""

    start: date
    end: date


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


def ingest_garmin_payload(
    db: Any, payload: Mapping[str, Any], *, zone: tzinfo
) -> CanonicalIngestCounters:
    """Write one stored Garmin payload. Garmin never deletes, so no window is passed.

    Rows keep the fetch time of their own section; the latest fetch time of the
    payload is the write time. A payload without any fetch time writes nothing.
    """
    retrieved_at = garmin_payload_retrieved_at(payload, zone=zone)
    if retrieved_at is None:
        return CanonicalIngestCounters()
    plan = garmin_ingest_plan(payload, zone=zone)
    return ingest_plan(
        db, plan, retrieved_at=retrieved_at, deletion_window=None, zone=zone
    )


def ingest_plan(
    db: Any,
    plan: IngestPlan,
    *,
    retrieved_at: datetime,
    deletion_window: DeletionWindow | None,
    zone: tzinfo,
) -> CanonicalIngestCounters:
    """Write raw records, activities, observations and domain rows, then apply deletions.

    The domain rows of each raw record replace the rows that record projected
    before. A raw record the plan does not carry keeps its rows, so a payload
    without a section never retires that section's rows.

    The written activities are then linked to duplicates from other providers on
    the athlete's wall clock ``zone`` (see ``link_activity_sessions``).
    """
    stamp = retrieved_at.isoformat()
    provider = plan.provider.value
    counters = CanonicalIngestCounters(skipped_invalid=plan.skipped_invalid)
    for raw in plan.raw_records:
        canonical_store.upsert_provider_record(
            db,
            provider=provider,
            record_kind=raw.record_kind,
            source_record_id=raw.source_record_id,
            payload=sanitized_provider_payload(raw.payload),
            mapper_version=raw.mapper_version,
            fetched_at=_fetched_at(raw.retrieved_at, stamp),
            now=stamp,
            observed_on=raw.observed_on,
        )
    for activity in plan.activities:
        counters.count(
            canonical_store.upsert_activity_record(
                db,
                activity.record,
                local_date=activity.local_date,
                mapper_version=activity.mapper_version,
                fetched_at=_fetched_at(activity.retrieved_at, stamp),
                now=stamp,
            )
        )
    seen_keys: set[str] = set()
    for item in plan.observations:
        # Natural-key collisions inside one payload: the first wins, later ones are skipped.
        natural_key = canonical_store.observation_natural_key(item.observation)
        if natural_key in seen_keys:
            counters.skipped_invalid += 1
            continue
        seen_keys.add(natural_key)
        counters.count(
            canonical_store.upsert_observation(
                db,
                item.observation,
                mapper_version=item.mapper_version,
                now=stamp,
                fill_only=item.fill_only,
            )
        )
    raw_ids = {raw.source_record_id for raw in plan.raw_records}
    for batch in plan.domain_batches:
        if batch.source_record_id not in raw_ids:
            raise ValueError("a domain batch needs its raw record in the same plan")
        counters.add(
            canonical_domain_store.replace_source_rows(
                db,
                provider=plan.provider,
                source_record_id=batch.source_record_id,
                mapper_version=batch.mapper_version,
                now=stamp,
                sleep_periods=batch.sleep_periods,
                categorical=batch.categorical,
                zones=batch.zones,
                gear_items=batch.gear_items,
                gear_links=batch.gear_links,
                power_curve=batch.power_curve,
                power_curve_fetch=batch.power_curve_fetch,
            )
        )
    if deletion_window is not None:
        counters.deleted = canonical_store.mark_missing_deleted(
            db,
            provider,
            record_kind=ACTIVITY_RECORD_KIND,
            window_start=deletion_window.start,
            window_end=deletion_window.end,
            present_ids=plan.present_activity_ids,
            now=stamp,
        )
    if plan.activities:
        # After the deletions, so a tombstoned activity is never bundled.
        counters.linked = link_activity_sessions(
            db,
            touched_dates={activity.local_date for activity in plan.activities},
            zone=zone,
            now=stamp,
        )
    return counters


def _fetched_at(row_time: datetime | None, stamp: str) -> str:
    """Return a row's own fetch time, or the ingest stamp when it has none."""
    return stamp if row_time is None else row_time.isoformat()
