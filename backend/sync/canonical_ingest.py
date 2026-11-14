"""Provider-neutral use case that writes one fetched payload into the canonical tables.

The functions run inside the caller's unit of work, so the rows written here and
the legacy snapshot write commit or roll back together. They return counters
only and never commit or log provider content.

Deletion rule: only a completely read activity list marks missing activities
deleted, and only inside its window shrunk by one edge day: a Garmin activity
range read without failure or pause, or a fully paged Wahoo listing. Partial,
failed, paused or truncated fetches never delete.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from backend.activities.session_linking import (
    link_activity_sessions,
    split_unmatched_sessions,
)
from backend.canonical.garmin_payload import DEDICATED_ACTIVITY_SECTIONS
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_domain_store, canonical_store, garmin_store
from backend.db.canonical_domain_store import ReplaceResult
from backend.db.canonical_store import ObservationScope, WriteOutcome
from backend.observability import sanitized_provider_payload
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    IngestPlan,
    garmin_ingest_plan,
    garmin_payload_retrieved_at,
)


@dataclass(slots=True)
class CanonicalIngestCounters:
    """How many canonical rows one ingest wrote, kept, or skipped."""

    written: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_invalid: int = 0
    deleted: int = 0
    linked: int = 0
    split: int = 0
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
            "split": self.split,
            "retired": self.retired,
        }


DELETION_EDGE_MARGIN = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class DeletionWindow:
    """Inclusive athlete-local date range in which a full fetch may delete."""

    start: date
    end: date


def fetch_deletion_window(start: date, end: date) -> DeletionWindow | None:
    """Return the inner days of a completely read provider date range.

    The provider filters on its own local dates while stored rows carry the
    athlete-local date, so a deletion at the first or last day might hit an
    activity the fetch never asked for; both days are excluded. A range of two days or less returns None.
    """
    window = DeletionWindow(
        start=start + DELETION_EDGE_MARGIN, end=end - DELETION_EDGE_MARGIN
    )
    return window if window.start <= window.end else None


def _has_activity_list(raw: object) -> bool:
    """A missing or non-list activity block must never be read as "nothing fetched"."""
    return isinstance(raw, Mapping) and isinstance(raw.get("activities"), list)


def ingest_garmin_payload(
    db: Any,
    payload: Mapping[str, Any],
    *,
    zone: tzinfo,
    deletion_window: DeletionWindow | None = None,
) -> CanonicalIngestCounters:
    """Write one stored Garmin payload.

    Rows keep the fetch time of their own section; the latest fetch time of the
    payload is the write time. A payload without any fetch time writes nothing.
    ``deletion_window`` comes from a completely read activity list.
    """
    retrieved_at = garmin_payload_retrieved_at(payload, zone=zone)
    if retrieved_at is None:
        return CanonicalIngestCounters()
    plan = garmin_ingest_plan(
        payload, zone=zone, training_loads=stored_training_loads(db)
    )
    return ingest_plan(
        db, plan, retrieved_at=retrieved_at, deletion_window=deletion_window, zone=zone
    )


def stored_training_loads(db: Any) -> Callable[[str], Any]:
    """Look up the stored dedicated Garmin rows of an activity id, combined.

    The rating row and the training-load row merge into one; None without either.
    """

    def lookup(activity_id: str) -> Any:
        combined: dict[str, Any] = {}
        for section in DEDICATED_ACTIVITY_SECTIONS:
            row = garmin_store.read_item(db, section, activity_id)
            if isinstance(row, dict):
                combined.update(row)
        return combined or None

    return lookup


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
    before. Likewise, an observation owned by one of the plan's
    ``observation_owners`` that the plan no longer emits is retired. A raw record
    the plan does not carry keeps its rows, so a payload without a section (a
    failed or skipped fetch) never retires that section's rows.

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
            # Garmin re-projects with the latest delivery time (#2782).
            refresh_fetched_at=plan.provider is ProviderId.GARMIN,
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
    # First retire what an owner no longer emits, then write: a value that
    # another record still emits (a fill-only history, a key collision) is then
    # written again instead of staying behind as the cleared value.
    counters.retired += canonical_store.retire_unemitted_observations(
        db,
        provider=provider,
        scopes=observation_scopes(plan),
        now=stamp,
    )
    # Natural-key collisions inside one payload: the first wins, later ones are
    # skipped. Two ranked Garmin sections are left to the store, which decides
    # them by the one rule the re-projection follows (#2782).
    seen_keys: set[tuple[str, str | None]] = set()
    for item in plan.observations:
        slot = (
            canonical_store.observation_natural_key(item.observation),
            canonical_store.rank_section(
                item.owner, item.observation.provenance.source_record_id, item.ranks
            ),
        )
        if slot in seen_keys:
            counters.skipped_invalid += 1
            continue
        seen_keys.add(slot)
        counters.count(
            canonical_store.upsert_observation(
                db,
                item.observation,
                mapper_version=item.mapper_version,
                now=stamp,
                fill_only=item.fill_only,
                owner=item.owner,
                ranks=item.ranks,
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
            )
        )
    for provider_activity_id in sorted(plan.withdrawn_activity_ids):
        counters.deleted += canonical_store.mark_placeholder_deleted(
            db,
            provider,
            record_kind=ACTIVITY_RECORD_KIND,
            provider_activity_id=provider_activity_id,
            now=stamp,
        )
    # A plan whose activity list is missing or holds a row without an id cannot
    # tell which stored activities the provider dropped, so it never deletes.
    if deletion_window is not None and plan.activity_ids_complete:
        counters.deleted += canonical_store.mark_missing_deleted(
            db,
            provider,
            record_kind=ACTIVITY_RECORD_KIND,
            window_start=deletion_window.start,
            window_end=deletion_window.end,
            present_ids=plan.present_activity_ids,
            now=stamp,
        )
    if plan.activities:
        touched = {activity.local_date for activity in plan.activities}
        # After the deletions, so a tombstoned activity is never bundled. Copies
        # that no longer match their session are split off before linking.
        counters.split = split_unmatched_sessions(
            db, touched_dates=touched, zone=zone, now=stamp
        )
        counters.linked = link_activity_sessions(
            db, touched_dates=touched, zone=zone, now=stamp
        )
    return counters


def observation_scopes(plan: IngestPlan) -> dict[str, ObservationScope]:
    """Return what each owning raw record of the plan covers, for retirement.

    Only raw records the plan carries count. An owner covers its own day and every
    day it still emits, and keeps the natural keys it emits.
    """
    raw_ids = {raw.source_record_id for raw in plan.raw_records}
    days: dict[str, set[str]] = {}
    emitted: dict[str, set[str]] = {}
    for owner, day in plan.observation_owners.items():
        if owner in raw_ids:
            days[owner] = {day}
            emitted[owner] = set()
    for item in plan.observations:
        if item.owner in days:
            days[item.owner].add(item.observation.observed_on.isoformat())
            emitted[item.owner].add(
                canonical_store.observation_natural_key(item.observation)
            )
    return {
        owner: ObservationScope(frozenset(days[owner]), frozenset(emitted[owner]))
        for owner in days
    }


def _fetched_at(row_time: datetime | None, stamp: str) -> str:
    """Return a row's own fetch time, or the ingest stamp when it has none."""
    return stamp if row_time is None else row_time.isoformat()
