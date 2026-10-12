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

from backend.canonical.local_time import local_date
from backend.db import canonical_store
from backend.db.canonical_store import WriteOutcome
from backend.observability import sanitized_provider_payload
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    IngestPlan,
    garmin_ingest_plan,
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

    def count(self, outcome: WriteOutcome) -> None:
        if outcome is WriteOutcome.WRITTEN:
            self.written += 1
        elif outcome is WriteOutcome.UPDATED:
            self.updated += 1
        else:
            self.unchanged += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "written": self.written,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_invalid": self.skipped_invalid,
            "deleted": self.deleted,
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
    """Write the Intervals.icu raw block of a snapshot.

    ``activity_days`` is None for historical fetches, which never delete. An
    incremental snapshot never deletes either. A snapshot without a sync time
    writes nothing and returns empty counters.
    """
    retrieved_at = stored_retrieved_at(snapshot, zone=zone)
    if retrieved_at is None:
        return CanonicalIngestCounters()
    raw = snapshot.get("raw_provider_data")
    plan = intervals_ingest_plan(raw, zone=zone, retrieved_at=retrieved_at)
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
        db, plan, retrieved_at=retrieved_at, deletion_window=deletion_window
    )


def ingest_garmin_payload(
    db: Any, payload: Mapping[str, Any], *, zone: tzinfo
) -> CanonicalIngestCounters:
    """Write one stored Garmin payload. Garmin never deletes, so no window is passed."""
    retrieved_at = stored_retrieved_at(payload, zone=zone)
    if retrieved_at is None:
        return CanonicalIngestCounters()
    plan = garmin_ingest_plan(payload, zone=zone, retrieved_at=retrieved_at)
    return ingest_plan(db, plan, retrieved_at=retrieved_at, deletion_window=None)


def ingest_plan(
    db: Any,
    plan: IngestPlan,
    *,
    retrieved_at: datetime,
    deletion_window: DeletionWindow | None,
) -> CanonicalIngestCounters:
    """Write raw records, then activities, then observations, then apply deletions."""
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
            fetched_at=stamp,
            now=stamp,
        )
    for activity in plan.activities:
        counters.count(
            canonical_store.upsert_activity_record(
                db,
                activity.record,
                local_date=activity.local_date,
                mapper_version=activity.mapper_version,
                fetched_at=stamp,
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
                db, item.observation, mapper_version=item.mapper_version, now=stamp
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
    return counters
