"""Idempotent, resumable backfill of stored legacy data into the canonical tables.

Order of work: the newest stored Garmin payload first, then the snapshots by
descending id. This deviates from the migration plan's oldest-first order on
purpose: the coach reads the newest data, so it becomes canonical first, and a run
that stops early still leaves the rows that matter most.

Insert-only ingest: the ingest phase never updates or revives an existing canonical
row, live or deleted. A row that already exists counts as ``already_present``. A
new activity gets a single-link session, as in ``upsert_activity_record``. Backfill
never deletes. A snapshot without ``raw_provider_data`` is not mapped, because its
``recent_activities`` fallback is a compact read model with no mapper; such a
snapshot counts as ``skipped_invalid``.

Supersession: the newest snapshot present when the run starts is the only one that
may insert activities. Its activities and their raw ``activity`` records are inserted
when absent, as usual. Every older snapshot inserts no activity and no raw ``activity``
record: each of its activities is skipped and counted as ``superseded``, not as
``already_present``. The newest snapshot already carries every activity that still
exists upstream within the synced range (an incremental sync merges with the previous
snapshot, and a full sync replaces it), so an activity that only an older snapshot
shows was deleted upstream or lies outside the configured range, and must not become
canonical. If the newest snapshot is removed during the run, every remaining snapshot
is older and supersedes its activities the same way. Older ``snapshots`` rows are
never modified or deleted, so no stored data is lost. Observations, wellness and
athlete records from older snapshots keep insert-if-absent. Whether an activity is
inserted depends only on its snapshot's id, not on canonical state, so a batch
boundary or a resume cannot change the outcome.

Re-projection: when a mapper version is above the ``mapped_version`` of an active
raw record, that record is mapped again from its stored payload and fetch time, its
canonical rows are updated to the current projection, and its ``mapped_version`` is
advanced. Deleted raw records are skipped. This is the only phase that updates
existing canonical rows.

Each batch writes at most ``batch_size`` plan items in one writer transaction. The
cursor and the content-free counters are one kv value written in that same
transaction, so a failed batch leaves the last committed cursor in place and the
next run resumes from it. Counters that describe a whole source (plan-level skips
and duplicates) are added only when that source completes, so an aborted and
resumed run reports the same totals as an uninterrupted one. A source that changes
between batches (for example a new Garmin sync) restarts from its first item; rows
already written then count as ``already_present``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import StrEnum
from functools import partial
from typing import Any, Final

from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.db.repositories import KeyValueRepository
from backend.observability import sanitized_provider_payload
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    ActivityItem,
    IngestPlan,
    ObservationItem,
    RawRecord,
    current_mapper_versions,
    garmin_ingest_plan,
    garmin_payload_retrieved_at,
    intervals_snapshot_ingest_plan,
    reprojection_mapper_version,
    reprojection_plan,
)
from backend.providers.snapshot_projection import stored_retrieved_at
from backend.sync.garmin_snapshot_writer import GARMIN_SNAPSHOT_KEY

STATE_KEY: Final = "canonical_backfill_state"
DEFAULT_BATCH_SIZE: Final = 200
MIN_BATCH_SIZE: Final = 100
MAX_BATCH_SIZE: Final = 250
COUNTER_NAMES: Final = (
    "inserted",
    "already_present",
    "superseded",
    "skipped_invalid",
    "sessions_created",
    "duplicates",
    "reprojected",
)

_INGEST: Final = "ingest"
_REPROJECT: Final = "reproject"
_GARMIN: Final = ProviderId.GARMIN.value
_SNAPSHOT: Final = "snapshot"


class BackfillStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BatchReport:
    """Plan items written by one batch, and whether the whole backfill is finished."""

    items: int
    done: bool


@dataclass(frozen=True, slots=True)
class _Item:
    value: RawRecord | ActivityItem | ObservationItem
    fetched_at: str


@dataclass(frozen=True, slots=True)
class _Work:
    """The ordered items of one source and the plan-level counts due when it completes."""

    items: tuple[_Item, ...] = ()
    skipped_invalid: int = 0
    duplicates: int = 0
    superseded: int = 0


def _empty_counters() -> dict[str, dict[str, int]]:
    return {provider.value: dict.fromkeys(COUNTER_NAMES, 0) for provider in ProviderId}


def _provider_of(source: str) -> str:
    return ProviderId.GARMIN.value if source == _GARMIN else ProviderId.INTERVALS.value


class CanonicalBackfill:
    """Runs the backfill one batch at a time. The caller owns the transaction."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
        clock: Callable[[], str],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}"
            )
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._clock = clock
        self._batch_size = batch_size
        self._cache_key: str | None = None
        self._cache: _Work | None = None

    def run_batch(self, db: Any) -> BatchReport:
        """Write one batch and its cursor in the caller's transaction."""
        state = self._load(db)
        versions = current_mapper_versions()
        if state["status"] == BackfillStatus.COMPLETE:
            if state["versions"] == versions:
                return BatchReport(items=0, done=True)
            state.update(phase=_REPROJECT, reproject_after=0, reproject_current=None)
        state["status"] = BackfillStatus.RUNNING
        zone = self._zone_provider() or UTC
        now = self._clock()
        if state["phase"] == _INGEST:
            written, ingest_done = self._ingest_step(
                db, state, zone=zone, now=now, budget=self._batch_size
            )
            if ingest_done:
                state.update(
                    phase=_REPROJECT, reproject_after=0, reproject_current=None
                )
            done = False
        else:
            written, done = self._reproject_step(
                db, state, zone=zone, now=now, budget=self._batch_size
            )
        if done:
            state.update(status=BackfillStatus.COMPLETE, versions=versions)
        state["batches"] += 1
        self._save(db, state)
        return BatchReport(items=written, done=done)

    def mark_failed(self, db: Any) -> None:
        """Record that the run stopped; the cursor stays where the last batch committed."""
        state = self._load(db)
        state["status"] = BackfillStatus.FAILED
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return content-free status, counters and the count of unresolved feedback."""
        raw = self._key_values.get(db, STATE_KEY)
        state = json.loads(raw) if raw is not None else None
        return {
            "status": state["status"]
            if state is not None
            else BackfillStatus.PENDING.value,
            "batches": state["batches"] if state is not None else 0,
            "providers": state["counters"] if state is not None else _empty_counters(),
            "unresolved_feedback": canonical_store.count_unresolved_feedback(
                db, ProviderId.INTERVALS.value
            ),
        }

    def _ingest_step(
        self, db: Any, state: dict[str, Any], *, zone: tzinfo, now: str, budget: int
    ) -> tuple[int, bool]:
        """Write up to ``budget`` ingest items; return (items written, ingest finished)."""
        counters = state["counters"]
        written = 0
        while True:
            current = _ingest_cursor(db, state)
            if current is None:
                return written, True
            work = self._ingest_source_work(db, state, current, zone)
            if work is None:
                _finish_source(state, current, _Work(), counters)
                continue
            count, finished = _drain(
                work,
                current,
                budget - written,
                partial(
                    _write_ingest,
                    db,
                    provider=_provider_of(current["source"]),
                    now=now,
                    counters=counters,
                ),
            )
            written += count
            if not finished:
                return written, False
            _finish_source(state, current, work, counters)

    def _ingest_source_work(
        self,
        db: Any,
        state: Mapping[str, Any],
        current: dict[str, Any],
        zone: tzinfo,
    ) -> _Work | None:
        """Return the items of the current source, or None when it no longer exists."""
        text = self._source_text(db, current)
        if text is None:
            return None
        return self._work_for(
            _source_key(current),
            current,
            text,
            partial(
                _ingest_work,
                current["source"],
                text,
                zone,
                _may_insert_activities(state, current),
            ),
        )

    def _reproject_step(
        self, db: Any, state: dict[str, Any], *, zone: tzinfo, now: str, budget: int
    ) -> tuple[int, bool]:
        """Re-project up to ``budget`` items; return (items written, backfill finished)."""
        written = 0
        scanned = 0
        while True:
            current = state["reproject_current"]
            if current is None:
                if scanned >= budget:
                    return written, False
                scanned += 1
                row = _start_reprojection(db, state)
                if row is None:
                    return written, True
                current = state["reproject_current"]
            else:
                row = _raw_row_at(db, current["id"])
                if row is None:
                    # Deleted or gone since the last batch: nothing left to project.
                    _leave_reprojection(state, current)
                    continue
            version = reprojection_mapper_version(row["provider"], row["record_kind"])
            if version is None or int(row["mapped_version"]) >= version:
                _leave_reprojection(state, current)
                continue
            work = self._work_for(
                f"row:{current['id']}",
                current,
                str(row["payload"]),
                partial(_reprojection_work, row, zone),
            )
            count, finished = _drain(
                work,
                current,
                budget - written,
                partial(_write_reprojection, db, now=now),
            )
            written += count
            if not finished:
                return written, False
            _complete_reprojection(
                db, state, current, row, work, version=version, now=now
            )

    def _work_for(
        self,
        key: str,
        current: dict[str, Any],
        text: str,
        build: Callable[[], _Work],
    ) -> _Work:
        """Return the cached items of a source; a changed source restarts at offset 0."""
        fingerprint = canonical_store.payload_hash(text)
        if current["fingerprint"] != fingerprint:
            current.update(fingerprint=fingerprint, offset=0)
        work = self._cached_work(key, fingerprint)
        if work is None:
            work = build()
            self._remember(key, fingerprint, work)
        return work

    def _source_text(self, db: Any, current: Mapping[str, Any]) -> str | None:
        if current["source"] == _GARMIN:
            return self._key_values.get(db, GARMIN_SNAPSHOT_KEY)
        row = db.execute(
            "SELECT payload FROM snapshots WHERE id = ?", (current["id"],)
        ).fetchone()
        return None if row is None else str(row["payload"])

    def _cached_work(self, key: str, fingerprint: str) -> _Work | None:
        return self._cache if self._cache_key == f"{key}|{fingerprint}" else None

    def _remember(self, key: str, fingerprint: str, work: _Work) -> None:
        self._cache_key = f"{key}|{fingerprint}"
        self._cache = work

    def _load(self, db: Any) -> dict[str, Any]:
        raw = self._key_values.get(db, STATE_KEY)
        if raw is None:
            return self._fresh_state(db)
        return json.loads(raw)

    def _save(self, db: Any, state: dict[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )

    @staticmethod
    def _fresh_state(db: Any) -> dict[str, Any]:
        # Snapshots created after the run starts are written by dual-write already.
        row = db.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM snapshots"
        ).fetchone()
        return {
            "status": BackfillStatus.PENDING.value,
            "phase": _INGEST,
            "garmin_done": False,
            "snapshot_before": int(row["next_id"]),
            "newest_id": int(row["next_id"]) - 1,
            "current": None,
            "reproject_after": 0,
            "reproject_current": None,
            "batches": 0,
            "counters": _empty_counters(),
            "versions": {},
        }


def _ingest_cursor(db: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the source in progress, starting the next one when none is."""
    if state["current"] is None:
        state["current"] = _next_source(db, state)
    return state["current"]


def _drain(
    work: _Work,
    current: dict[str, Any],
    budget: int,
    write: Callable[[_Item], None],
) -> tuple[int, bool]:
    """Write items from the cursor offset; return (items written, source finished)."""
    written = 0
    while current["offset"] < len(work.items):
        if written >= budget:
            return written, False
        write(work.items[current["offset"]])
        current["offset"] += 1
        written += 1
    return written, True


def _start_reprojection(db: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    """Move the re-projection cursor to the next active raw row, or return None."""
    found = canonical_store.provider_records_after(
        db, after_id=state["reproject_after"], limit=1
    )
    if not found:
        return None
    row = found[0]
    state["reproject_current"] = {"id": int(row["id"]), "fingerprint": "", "offset": 0}
    return row


def _leave_reprojection(state: dict[str, Any], current: Mapping[str, Any]) -> None:
    state.update(reproject_after=current["id"], reproject_current=None)


def _complete_reprojection(
    db: Any,
    state: dict[str, Any],
    current: Mapping[str, Any],
    row: Mapping[str, Any],
    work: _Work,
    *,
    version: int,
    now: str,
) -> None:
    canonical_store.set_mapped_version(
        db, record_id=current["id"], mapper_version=version, now=now
    )
    bucket = state["counters"][row["provider"]]
    bucket["reprojected"] += 1
    bucket["skipped_invalid"] += work.skipped_invalid
    bucket["duplicates"] += work.duplicates
    _leave_reprojection(state, current)


def _next_source(db: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    if not state["garmin_done"]:
        return {"source": _GARMIN, "id": None, "fingerprint": "", "offset": 0}
    row = db.execute(
        "SELECT id FROM snapshots WHERE id < ? ORDER BY id DESC LIMIT 1",
        (state["snapshot_before"],),
    ).fetchone()
    if row is None:
        return None
    return {"source": _SNAPSHOT, "id": int(row["id"]), "fingerprint": "", "offset": 0}


def _source_key(current: Mapping[str, Any]) -> str:
    return _GARMIN if current["source"] == _GARMIN else f"snapshot:{current['id']}"


def _finish_source(
    state: dict[str, Any],
    current: Mapping[str, Any],
    work: _Work,
    counters: dict[str, Any],
) -> None:
    bucket = counters[_provider_of(current["source"])]
    bucket["skipped_invalid"] += work.skipped_invalid
    bucket["duplicates"] += work.duplicates
    bucket["superseded"] += work.superseded
    if current["source"] == _GARMIN:
        state["garmin_done"] = True
    else:
        state["snapshot_before"] = current["id"]
    state["current"] = None


def _may_insert_activities(
    state: Mapping[str, Any], current: Mapping[str, Any]
) -> bool:
    """Garmin and the newest Intervals snapshot may insert activities; older snapshots may not."""
    return current["source"] == _GARMIN or current["id"] == state["newest_id"]


def _ingest_work(
    source: str, text: str, zone: tzinfo, may_insert_activities: bool
) -> _Work:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return _Work(skipped_invalid=1)
    if source == _GARMIN:
        return _garmin_work(payload, zone)
    return _work_from_plan(
        intervals_snapshot_ingest_plan(payload, zone=zone),
        stored_retrieved_at(payload, zone=zone),
        may_insert_activities=may_insert_activities,
    )


def _garmin_work(payload: dict[str, Any], zone: tzinfo) -> _Work:
    """Plan a stored Garmin payload; one without any fetch time is skipped as invalid."""
    fetched = garmin_payload_retrieved_at(payload, zone=zone)
    return (
        _Work(skipped_invalid=1)
        if fetched is None
        else _work_from_plan(
            garmin_ingest_plan(payload, zone=zone),
            fetched,
            may_insert_activities=True,
        )
    )


def _reprojection_work(row: Mapping[str, Any], zone: tzinfo) -> _Work:
    plan = reprojection_plan(row, zone=zone)
    if plan is None:
        return _Work()
    return _work_from_plan(plan, None, may_insert_activities=True)


def _work_from_plan(
    plan: IngestPlan, fetched: datetime | None, *, may_insert_activities: bool
) -> _Work:
    """Flatten a plan into ordered items, dropping repeats within the same source.

    When the source may not insert activities, its activities and their raw records are
    left out, and each distinct activity is counted once as superseded.
    """
    stamp = fetched.isoformat() if fetched is not None else ""
    items, duplicates = _raw_items(
        plan.raw_records, stamp, may_insert_activities=may_insert_activities
    )
    seen_activities: set[str] = set()
    seen_observations: set[str] = set()
    superseded = 0
    for activity in plan.activities:
        source_id = activity.record.provenance.source_record_id or ""
        if source_id in seen_activities:
            duplicates += 1
            continue
        seen_activities.add(source_id)
        if not may_insert_activities:
            superseded += 1
            continue
        items.append(_Item(activity, _fetched_at(activity.retrieved_at, stamp)))
    for observation in plan.observations:
        natural_key = canonical_store.observation_natural_key(observation.observation)
        if natural_key in seen_observations:
            duplicates += 1
            continue
        seen_observations.add(natural_key)
        items.append(_Item(observation, stamp))
    return _Work(
        items=tuple(items),
        skipped_invalid=plan.skipped_invalid,
        duplicates=duplicates,
        superseded=superseded,
    )


def _raw_items(
    raw_records: Sequence[RawRecord], stamp: str, *, may_insert_activities: bool
) -> tuple[list[_Item], int]:
    """Return the distinct raw records to write and the number of repeats."""
    items: list[_Item] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for raw in raw_records:
        key = (raw.record_kind, raw.source_record_id)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if raw.record_kind == ACTIVITY_RECORD_KIND and not may_insert_activities:
            continue
        items.append(_Item(raw, _fetched_at(raw.retrieved_at, stamp)))
    return items, duplicates


def _fetched_at(row_time: datetime | None, stamp: str) -> str:
    return row_time.isoformat() if row_time is not None else stamp


def _write_ingest(
    db: Any, item: _Item, provider: str, now: str, counters: dict[str, Any]
) -> None:
    """Insert one item when absent. Existing rows are never changed."""
    value = item.value
    bucket = counters[provider]
    if isinstance(value, RawRecord):
        inserted = canonical_store.insert_provider_record_if_absent(
            db,
            provider=provider,
            record_kind=value.record_kind,
            source_record_id=value.source_record_id,
            payload=sanitized_provider_payload(value.payload),
            mapper_version=value.mapper_version,
            fetched_at=item.fetched_at,
            now=now,
        )
    elif isinstance(value, ActivityItem):
        inserted = canonical_store.insert_activity_record_if_absent(
            db,
            value.record,
            local_date=value.local_date,
            mapper_version=value.mapper_version,
            fetched_at=item.fetched_at,
            now=now,
        )
        if inserted:
            bucket["sessions_created"] += 1
    else:
        inserted = canonical_store.insert_observation_if_absent(
            db,
            value.observation,
            mapper_version=value.mapper_version,
            now=now,
        )
    bucket["inserted" if inserted else "already_present"] += 1


def _write_reprojection(db: Any, item: _Item, now: str) -> None:
    """Bring one existing canonical row up to the current projection."""
    value = item.value
    if isinstance(value, ActivityItem):
        canonical_store.upsert_activity_record(
            db,
            value.record,
            local_date=value.local_date,
            mapper_version=value.mapper_version,
            fetched_at=item.fetched_at,
            now=now,
        )
    elif isinstance(value, ObservationItem):
        canonical_store.upsert_observation(
            db, value.observation, mapper_version=value.mapper_version, now=now
        )
    else:
        # Re-projection plans carry activities and observations, never raw records.
        raise TypeError("re-projection items must be activities or observations")


def _raw_row_at(db: Any, record_id: int) -> dict[str, Any] | None:
    """Return the active raw row with this id, or None when it is missing or deleted."""
    found = canonical_store.provider_records_after(db, after_id=record_id - 1, limit=1)
    if not found or int(found[0]["id"]) != record_id:
        return None
    return found[0]
