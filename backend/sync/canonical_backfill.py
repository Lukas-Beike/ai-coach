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
snapshot counts as ``skipped_invalid``. The sleep, status, zone and gear rows of a
raw record (its domain batch) are inserted only when that source record has no domain
row at all, active or retired; otherwise the batch counts as ``already_present``. An
empty batch inserts nothing and counts nothing.

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

Stripped snapshots: once the tables serve reads, a sync stores its snapshot without
the activity sections and marks it (``canonical_sections``). Such a snapshot never
counts as the newest one that may insert activities, counts as neither
``skipped_invalid`` nor a deletion source, and maps only the wellness and athlete
sections it still carries (insert-if-absent). The activities it lacks are already in
the tables and their raw records.

Re-projection: when a mapper version is above the ``mapped_version`` of an active
raw record, that record is mapped again from its stored payload and fetch time, its
canonical rows are brought to the current projection, and its ``mapped_version`` is
advanced. Deleted raw records are skipped. Re-projection never revives a tombstone: a
deleted activity, or an activity whose session is deleted, is left as it is. An
activity that the raw record owns (same provider and source record id) and that the new
projection no longer emits becomes ``invalid`` in the same transaction that advances
``mapped_version``; its session keeps its state. A later version that emits it again
makes it ``active`` with the same ``activity_id``. An unusable stored payload emits
nothing, so the activity it owns is marked ``invalid`` as well, and a later mapper fix
restores it. In the same transaction, the sessions near the re-projected activities
are linked to duplicates from other providers (``link_activity_sessions``), so a
mapper fix that lets two copies match merges stored history without a new provider
refresh. Observations have no state column and no exact ownership for athlete and
health records, so observations that an upgraded mapper no longer emits are not retired;
they keep their old ``mapper_version``. The table reader that follows this phase serves
only observations whose ``mapper_version`` equals the current version of their mapper,
so stale observations are never served as current. The cursor is bound to the mapper
version, so a version bump during a partial run restarts that record from its first
item. Domain rows have exact ownership: on completion, in the transaction that advances
``mapped_version``, the rows of the re-projected source record are replaced by its new
batch, and the rows it no longer emits are retired (counted as ``retired``). Other
source records and providers are untouched. This is the only phase that updates
existing canonical rows.

Time zone: the canonical tables store local dates computed in the athlete's zone at
write time, so the state records the zone it projected with. A different current zone
(or an older state without one) makes the next batch re-project every active raw row
once (``reproject_all``), regardless of ``mapped_version``, and ``backfill_complete``
is False until that finishes.

Read policy: the first time the backfill completes, the state records
``completed_once`` and ``first_completed_at`` in the same transaction as the
completion. A state that is already ``complete`` without the marker (stored before
the marker existed) counts as completed once, and the marker is added when the next
re-projection starts. From then on reads come from the tables (``read_state``): a
mapper-version bump or a zone change re-projects as described above, but reads stay
on the tables meanwhile and serve each observation's newest stored version, so
nothing vanishes. Only an installation whose backfill never completed reads the
legacy snapshot projection. Nothing is deleted.

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

from backend.activities.session_linking import link_activity_sessions
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_domain_store, canonical_store
from backend.db.repositories import KeyValueRepository
from backend.observability import sanitized_provider_payload
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    ActivityItem,
    DomainBatch,
    IngestPlan,
    ObservationItem,
    RawRecord,
    current_mapper_versions,
    intervals_snapshot_ingest_plan,
    observation_mapper_versions,
    reprojection_mapper_version,
    reprojection_plan,
)
from backend.providers.snapshot_projection import (
    CANONICAL_SECTIONS_KEY,
    stored_retrieved_at,
)

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
    "retired",
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
    value: RawRecord | ActivityItem | ObservationItem | DomainBatch
    fetched_at: str


@dataclass(frozen=True, slots=True)
class _Work:
    """The ordered items of one source and the plan-level counts due when it completes."""

    items: tuple[_Item, ...] = ()
    skipped_invalid: int = 0
    duplicates: int = 0
    superseded: int = 0
    # Re-projection only: the domain rows of the raw record, written on completion.
    domain_batches: tuple[DomainBatch, ...] = ()


# Wahoo is ingested live and has no legacy snapshot to backfill, so persisted
# backfill counters stay limited to the providers that are actually backfilled.
_BACKFILL_PROVIDERS = (ProviderId.INTERVALS, ProviderId.GARMIN)


def _empty_counters() -> dict[str, dict[str, int]]:
    return {
        provider.value: dict.fromkeys(COUNTER_NAMES, 0)
        for provider in _BACKFILL_PROVIDERS
    }


def _provider_of(source: str) -> str:
    return ProviderId.GARMIN.value if source == _GARMIN else ProviderId.INTERVALS.value


def read_status(key_values: KeyValueRepository, db: Any) -> str:
    """Return the stored backfill status word, or ``pending`` before the first batch."""
    raw = key_values.get(db, STATE_KEY)
    if raw is None:
        return BackfillStatus.PENDING.value
    try:
        state = json.loads(raw)
    except ValueError:
        # A corrupt backfill record reads as not started, so the switch stays on legacy.
        return BackfillStatus.PENDING.value
    status = state.get("status") if isinstance(state, dict) else None
    return status if isinstance(status, str) else BackfillStatus.PENDING.value


class ReadState(StrEnum):
    """Which source serves canonical reads, decided from the backfill state alone."""

    LEGACY = "legacy"
    TABLES = "tables"
    TABLES_REPROJECTING = "tables_reprojecting"


def _stored_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    """Return the stored backfill state; a missing or corrupt record reads as empty."""
    raw = key_values.get(db, STATE_KEY)
    if raw is None:
        return {}
    try:
        state = json.loads(raw)
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def completed_observation_versions(
    key_values: KeyValueRepository, db: Any
) -> dict[str, int]:
    """Return each provider's observation mapper version at the last completed run.

    The stored versions change only when a run completes, so during a pending
    re-projection they name the oldest version whose rows are still emitted. A
    missing or corrupt record reads as empty.
    """
    versions = _stored_state(key_values, db).get("versions")
    return observation_mapper_versions(versions) if isinstance(versions, dict) else {}


def _is_current(state: Mapping[str, Any], zone: tzinfo) -> bool:
    return (
        state.get("status") == BackfillStatus.COMPLETE.value
        and state.get("versions") == current_mapper_versions()
        and state.get("zone") == str(zone)
    )


def _completed_once(state: Mapping[str, Any]) -> bool:
    return (
        state.get("completed_once") is True
        or state.get("status") == BackfillStatus.COMPLETE.value
    )


def backfill_complete(key_values: KeyValueRepository, db: Any, *, zone: tzinfo) -> bool:
    """Return True when the backfill is complete for the current mappers and time zone.

    A read-only query. After a mapper upgrade or a zone change the stored status
    stays ``complete`` until the worker's first batch moves it back to
    re-projection, so the stored mapper versions and zone are compared too. The
    canonical tables hold local dates computed in the zone of the write. A missing,
    corrupt or older record (including one without a stored zone) is False.

    This is not the read gate: reads follow ``read_state``, which keeps serving the
    tables while a re-projection is pending.
    """
    return _is_current(_stored_state(key_values, db), zone)


def read_state(key_values: KeyValueRepository, db: Any, *, zone: tzinfo) -> ReadState:
    """Return which source serves reads: legacy only before the first completion."""
    state = _stored_state(key_values, db)
    if not _completed_once(state):
        return ReadState.LEGACY
    if _is_current(state, zone):
        return ReadState.TABLES
    return ReadState.TABLES_REPROJECTING


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
        zone = self._zone_provider() or UTC
        state = self._load(db, zone)
        versions = current_mapper_versions()
        zone_changed = state.get("zone") != str(zone)
        if state["status"] == BackfillStatus.COMPLETE:
            if state["versions"] == versions and not zone_changed:
                return BatchReport(items=0, done=True)
            state.update(phase=_REPROJECT, reproject_after=0, reproject_current=None)
            self._mark_completed_once(state, now=self._clock())
        if zone_changed:
            # Stored local dates were computed in another zone (or an older record
            # kept none), so every active raw row is projected again, once.
            state.update(
                zone=str(zone),
                reproject_all=True,
                reproject_after=0,
                reproject_current=None,
            )
        if state["phase"] == _REPROJECT and state.get("reproject_versions") != versions:
            # A new mapper must revisit rows already passed by an interrupted run,
            # not only restart the raw record at its current cursor.
            state.update(
                reproject_after=0,
                reproject_current=None,
                reproject_versions=versions,
            )
        state["status"] = BackfillStatus.RUNNING
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
            state.update(
                status=BackfillStatus.COMPLETE, versions=versions, reproject_all=False
            )
            self._mark_completed_once(state, now=now)
        state["batches"] += 1
        self._save(db, state)
        return BatchReport(items=written, done=done)

    @staticmethod
    def _mark_completed_once(state: dict[str, Any], *, now: str) -> None:
        """Record, once, that the backfill completed; the value is content-free."""
        if state.get("completed_once") is not True:
            state.update(completed_once=True, first_completed_at=now)

    def mark_failed(self, db: Any) -> None:
        """Record that the run stopped; the cursor stays where the last batch committed."""
        state = self._load(db, self._zone_provider() or UTC)
        if state["status"] == BackfillStatus.COMPLETE:
            # A completion that predates the marker must survive the failure, or
            # reads would fall back to legacy.
            self._mark_completed_once(state, now=self._clock())
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
            f"{_source_key(current)}@{zone}",
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
            if state["reproject_current"] is None:
                if scanned >= budget:
                    return written, False
                scanned += 1
                if _start_reprojection(db, state) is None:
                    return written, True
            pending = _pending_reprojection(db, state)
            if pending is None:
                continue
            current = state["reproject_current"]
            row, version = pending
            work = self._work_for(
                f"row:{current['id']}",
                current,
                f"{version}:{zone}:{row['payload']}",
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
                db, state, current, row, work, version=version, zone=zone, now=now
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
            return None
        row = db.execute(
            "SELECT payload FROM snapshots WHERE id = ?", (current["id"],)
        ).fetchone()
        return None if row is None else str(row["payload"])

    def _cached_work(self, key: str, fingerprint: str) -> _Work | None:
        return self._cache if self._cache_key == f"{key}|{fingerprint}" else None

    def _remember(self, key: str, fingerprint: str, work: _Work) -> None:
        self._cache_key = f"{key}|{fingerprint}"
        self._cache = work

    def _load(self, db: Any, zone: tzinfo) -> dict[str, Any]:
        raw = self._key_values.get(db, STATE_KEY)
        if raw is None:
            return self._fresh_state(db, zone)
        return json.loads(raw)

    def _save(self, db: Any, state: dict[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )

    @staticmethod
    def _fresh_state(db: Any, zone: tzinfo) -> dict[str, Any]:
        # Snapshots created after the run starts are written by dual-write already.
        row = db.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM snapshots"
        ).fetchone()
        # A snapshot stored without its activity sections must not become the
        # only one that may insert activities, or every full snapshot would
        # supersede its activities.
        newest = db.execute(
            "SELECT COALESCE(MAX(id), 0) AS newest_id FROM snapshots "
            "WHERE json_extract(payload, ?) IS NULL",
            (f"$.{CANONICAL_SECTIONS_KEY}",),
        ).fetchone()
        return {
            "status": BackfillStatus.PENDING.value,
            "phase": _INGEST,
            "garmin_done": True,
            "snapshot_before": int(row["next_id"]),
            "newest_id": int(newest["newest_id"]),
            "current": None,
            "reproject_after": 0,
            "reproject_current": None,
            "batches": 0,
            "counters": _empty_counters(),
            "versions": {},
            "zone": str(zone),
            "reproject_all": False,
            "completed_once": False,
            "first_completed_at": None,
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


def _pending_reprojection(
    db: Any, state: dict[str, Any]
) -> tuple[dict[str, Any], int] | None:
    """Return the current raw row and its mapper version when it needs re-projection.

    A row that was deleted or removed since the last batch, has no mapper, or is
    already current is left, and None is returned.
    """
    current = state["reproject_current"]
    row = _raw_row_at(db, current["id"])
    version = (
        None
        if row is None
        else reprojection_mapper_version(row["provider"], row["record_kind"])
    )
    if row is None or version is None:
        _leave_reprojection(state, current)
        return None
    if int(row["mapped_version"]) >= version and not state.get("reproject_all"):
        _leave_reprojection(state, current)
        return None
    return row, version


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
    zone: tzinfo,
    now: str,
) -> None:
    # Wahoo rows are ingested live, not backfilled, so its bucket appears on demand.
    bucket = state["counters"].setdefault(
        row["provider"], dict.fromkeys(COUNTER_NAMES, 0)
    )
    bucket["retired"] += _retire_unemitted(db, row, work, now=now)
    bucket["retired"] += _replace_domain_rows(db, row, work, version=version, now=now)
    # After the retirement, so an activity the new projection drops is never bundled.
    link_activity_sessions(
        db,
        touched_dates={
            item.value.local_date
            for item in work.items
            if isinstance(item.value, ActivityItem)
        },
        zone=zone,
        now=now,
    )
    canonical_store.set_mapped_version(
        db, record_id=current["id"], mapper_version=version, now=now
    )
    bucket["reprojected"] += 1
    bucket["skipped_invalid"] += work.skipped_invalid
    bucket["duplicates"] += work.duplicates
    _leave_reprojection(state, current)


def _retire_unemitted(db: Any, row: Mapping[str, Any], work: _Work, *, now: str) -> int:
    """Mark the activity this raw row owns invalid when the new projection drops it.

    Ownership is the same provider and source record id. Only activity raw records are
    retired; observations keep their old mapper version instead (see the module
    docstring). Returns 1 when an active activity was marked invalid, otherwise 0.
    """
    if row["record_kind"] != ACTIVITY_RECORD_KIND:
        return 0
    source_id = str(row["source_record_id"])
    emitted = {
        item.value.record.provenance.source_record_id
        for item in work.items
        if isinstance(item.value, ActivityItem)
    }
    if source_id in emitted:
        return 0
    return int(
        canonical_store.retire_unemitted_activity(
            db, provider=row["provider"], provider_activity_id=source_id, now=now
        )
    )


def _replace_domain_rows(
    db: Any, row: Mapping[str, Any], work: _Work, *, version: int, now: str
) -> int:
    """Replace the domain rows of a re-projected raw row; return how many were retired.

    A projection without a batch for the row retires all of its rows, so a mapper
    that stops emitting a period or status removes it from reads.
    """
    source_id = str(row["source_record_id"])
    if any(batch.source_record_id != source_id for batch in work.domain_batches):
        raise ValueError("a re-projected domain batch must belong to its raw record")
    batch = (
        work.domain_batches[0]
        if work.domain_batches
        else DomainBatch(source_id, version)
    )
    return canonical_domain_store.replace_source_rows(
        db,
        provider=ProviderId(row["provider"]),
        source_record_id=source_id,
        mapper_version=batch.mapper_version,
        now=now,
        sleep_periods=batch.sleep_periods,
        categorical=batch.categorical,
        zones=batch.zones,
        gear_items=batch.gear_items,
        gear_links=batch.gear_links,
    ).retired


def _next_source(db: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    # Garmin rows are stored per element since schema 12; its ingest phase is gone.
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
    return _work_from_plan(
        intervals_snapshot_ingest_plan(payload, zone=zone),
        stored_retrieved_at(payload, zone=zone),
        may_insert_activities=may_insert_activities,
        domain_items=True,
    )


def _reprojection_work(row: Mapping[str, Any], zone: tzinfo) -> _Work:
    plan = reprojection_plan(row, zone=zone)
    if plan is None:
        return _Work()
    return _work_from_plan(plan, None, may_insert_activities=True, domain_items=False)


def _work_from_plan(
    plan: IngestPlan,
    fetched: datetime | None,
    *,
    may_insert_activities: bool,
    domain_items: bool,
) -> _Work:
    """Flatten a plan into ordered items, dropping repeats within the same source.

    When the source may not insert activities, its activities and their raw records are
    left out, and each distinct activity is counted once as superseded. Domain batches
    follow the observations as items when ``domain_items`` is set (ingest); otherwise
    they are kept aside for the completion of a re-projection.
    """
    stamp = fetched.isoformat() if fetched is not None else ""
    items, duplicates = _raw_items(
        plan.raw_records, stamp, may_insert_activities=may_insert_activities
    )
    activities, repeats = _distinct(
        plan.activities, lambda item: item.record.provenance.source_record_id or ""
    )
    duplicates += repeats
    superseded = 0 if may_insert_activities else len(activities)
    if may_insert_activities:
        items.extend(
            _Item(activity, _fetched_at(activity.retrieved_at, stamp))
            for activity in activities
        )
    observations, repeats = _distinct(
        plan.observations,
        lambda item: canonical_store.observation_natural_key(item.observation),
    )
    duplicates += repeats
    items.extend(_Item(observation, stamp) for observation in observations)
    batches, repeats = _distinct(
        plan.domain_batches, lambda batch: batch.source_record_id
    )
    duplicates += repeats
    if domain_items:
        items.extend(_Item(batch, stamp) for batch in batches)
        batches = []
    return _Work(
        items=tuple(items),
        skipped_invalid=plan.skipped_invalid,
        duplicates=duplicates,
        superseded=superseded,
        domain_batches=tuple(batches),
    )


def _distinct[T](values: Sequence[T], key: Callable[[T], str]) -> tuple[list[T], int]:
    """Keep the first value per key, in order, and count the repeats."""
    seen: set[str] = set()
    kept: list[T] = []
    for value in values:
        identity = key(value)
        if identity not in seen:
            seen.add(identity)
            kept.append(value)
    return kept, len(values) - len(kept)


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
    elif isinstance(value, DomainBatch):
        if value.is_empty:
            return
        inserted = not canonical_domain_store.has_source_rows(
            db, provider=ProviderId(provider), source_record_id=value.source_record_id
        )
        if inserted:
            canonical_domain_store.replace_source_rows(
                db,
                provider=ProviderId(provider),
                source_record_id=value.source_record_id,
                mapper_version=value.mapper_version,
                now=now,
                sleep_periods=value.sleep_periods,
                categorical=value.categorical,
                zones=value.zones,
                gear_items=value.gear_items,
                gear_links=value.gear_links,
            )
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
        canonical_store.reproject_activity_record(
            db,
            value.record,
            local_date=value.local_date,
            mapper_version=value.mapper_version,
            fetched_at=item.fetched_at,
            now=now,
        )
    elif isinstance(value, ObservationItem):
        canonical_store.upsert_observation(
            db,
            value.observation,
            mapper_version=value.mapper_version,
            now=now,
            fill_only=value.fill_only,
        )
    else:
        # Re-projection plans carry activities and observations as items; raw records
        # are never re-written and domain batches are written on completion.
        raise TypeError("re-projection items must be activities or observations")


def _raw_row_at(db: Any, record_id: int) -> dict[str, Any] | None:
    """Return the active raw row with this id, or None when it is missing or deleted."""
    found = canonical_store.provider_records_after(db, after_id=record_id - 1, limit=1)
    if not found or int(found[0]["id"]) != record_id:
        return None
    return found[0]
