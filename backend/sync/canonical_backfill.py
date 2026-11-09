"""Idempotent, resumable re-projection of stored provider records into the canonical tables.

The backfill no longer ingests stored snapshots: Intervals.icu is an output target,
its stored snapshots are not read, and a database restored from a release before
2.0 keeps its Intervals.icu rows untouched. Garmin, Wahoo and the other providers
write their canonical rows live. What remains is the re-projection of the active
raw records those writers stored.

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
are re-checked (``split_unmatched_sessions``) and linked to duplicates from other
providers (``link_activity_sessions``), so a mapper fix that lets two copies match
merges stored history, and one that makes them stop matching splits it, without a
new provider refresh. Each re-projected
observation records the raw row as its owner; on completion, the active observations
that row owns and the new projection no longer emits are retired (counted as
``retired``). An observation without an owner, such as a Garmin value stored before
schema version 21 that no stored element emits any more, is not retired; it keeps its
old ``mapper_version``. The table reader that follows this phase serves only active
observations whose ``mapper_version`` equals the current version of their mapper, so
such stale observations are never served as current. The cursor is bound to the mapper
version, so a version bump during a partial run restarts that record from its first
item. Domain rows have exact ownership: on completion, in the transaction that advances
``mapped_version``, the rows of the re-projected source record are replaced by its new
batch, and the rows it no longer emits are retired (counted as ``retired``). Other
source records and providers are untouched. A raw record of a provider without a
mapper, such as a stored Intervals.icu row, is skipped and keeps its rows. This is the
only phase that updates existing canonical rows.

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
nothing vanishes. An installation whose backfill never completed reads nothing
until it does. Nothing is deleted.

Each batch writes at most ``batch_size`` plan items in one writer transaction. The
cursor and the content-free counters are one kv value written in that same
transaction, so a failed batch leaves the last committed cursor in place and the
next run resumes from it. Counters that describe a whole record (plan-level skips
and duplicates) are added only when that record completes, so an aborted and
resumed run reports the same totals as an uninterrupted one. A record that changes
between batches restarts from its first item.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, tzinfo
from enum import StrEnum
from functools import partial
from typing import Any, Final

from backend.activities.session_linking import (
    link_activity_sessions,
    split_unmatched_sessions,
)
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_domain_store, canonical_store
from backend.db.repositories import KeyValueRepository
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    ActivityItem,
    DomainBatch,
    IngestPlan,
    ObservationItem,
    RawRecord,
    current_mapper_versions,
    observation_mapper_versions,
    reprojection_mapper_version,
    reprojection_plan,
)
from backend.sync.canonical_ingest import stored_training_loads

STATE_KEY: Final = "canonical_backfill_state"
DEFAULT_BATCH_SIZE: Final = 200
MIN_BATCH_SIZE: Final = 100
MAX_BATCH_SIZE: Final = 250
COUNTER_NAMES: Final = ("skipped_invalid", "duplicates", "reprojected", "retired")

_REPROJECT: Final = "reproject"
_GARMIN: Final = ProviderId.GARMIN.value


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
    value: ActivityItem | ObservationItem | DomainBatch | RawRecord
    fetched_at: str


@dataclass(frozen=True, slots=True)
class _Work:
    """The ordered items of one raw record and the plan-level counts due when it completes."""

    items: tuple[_Item, ...] = ()
    skipped_invalid: int = 0
    duplicates: int = 0
    # The domain rows of the raw record, written on completion.
    domain_batches: tuple[DomainBatch, ...] = ()
    # The owning raw record ids and their days (see IngestPlan).
    observation_owners: Mapping[str, str] = field(default_factory=dict)


def _empty_counters() -> dict[str, dict[str, int]]:
    return {_GARMIN: dict.fromkeys(COUNTER_NAMES, 0)}


def read_status(key_values: KeyValueRepository, db: Any) -> str:
    """Return the stored backfill status word, or ``pending`` before the first batch."""
    raw = key_values.get(db, STATE_KEY)
    if raw is None:
        return BackfillStatus.PENDING.value
    try:
        state = json.loads(raw)
    except ValueError:
        # A corrupt backfill record reads as not started, so reads stay pending.
        return BackfillStatus.PENDING.value
    status = state.get("status") if isinstance(state, dict) else None
    return status if isinstance(status, str) else BackfillStatus.PENDING.value


class ReadState(StrEnum):
    """Which source serves canonical reads, decided from the backfill state alone."""

    PENDING = "pending"
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
    """Return which source serves reads: pending until the first completion."""
    state = _stored_state(key_values, db)
    if not _completed_once(state):
        return ReadState.PENDING
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
        if state.get("phase") != _REPROJECT:
            # A state stored while the retired snapshot ingest ran continues with
            # the re-projection; the snapshots it had not reached are not read.
            state.update(phase=_REPROJECT, reproject_after=0, reproject_current=None)
        if state.get("reproject_versions") != versions:
            # A new mapper must revisit rows already passed by an interrupted run,
            # not only restart the raw record at its current cursor.
            state.update(
                reproject_after=0,
                reproject_current=None,
                reproject_versions=versions,
            )
        state["status"] = BackfillStatus.RUNNING
        now = self._clock()
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
            # reads would become pending again.
            self._mark_completed_once(state, now=self._clock())
        state["status"] = BackfillStatus.FAILED
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return content-free status and counters."""
        raw = self._key_values.get(db, STATE_KEY)
        state = json.loads(raw) if raw is not None else None
        return {
            "status": state["status"]
            if state is not None
            else BackfillStatus.PENDING.value,
            "batches": state["batches"] if state is not None else 0,
            "providers": state["counters"] if state is not None else _empty_counters(),
        }

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
            loads = stored_training_loads(db)
            work = self._work_for(
                f"row:{current['id']}",
                current,
                f"{version}:{zone}:{row['payload']}:{_training_load_text(row, loads)}",
                partial(_reprojection_work, row, zone, loads),
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

    def _cached_work(self, key: str, fingerprint: str) -> _Work | None:
        return self._cache if self._cache_key == f"{key}|{fingerprint}" else None

    def _remember(self, key: str, fingerprint: str, work: _Work) -> None:
        self._cache_key = f"{key}|{fingerprint}"
        self._cache = work

    def _load(self, db: Any, zone: tzinfo) -> dict[str, Any]:
        raw = self._key_values.get(db, STATE_KEY)
        if raw is None:
            return self._fresh_state(zone)
        return json.loads(raw)

    def _save(self, db: Any, state: dict[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )

    @staticmethod
    def _fresh_state(zone: tzinfo) -> dict[str, Any]:
        return {
            "status": BackfillStatus.PENDING.value,
            "phase": _REPROJECT,
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
    bucket["retired"] += _retire_unemitted_observations(db, row, work, now=now)
    bucket["retired"] += _replace_domain_rows(db, row, work, version=version, now=now)
    # After the retirement, so an activity the new projection drops is never bundled.
    _link_work_sessions(db, work, zone=zone, now=now)
    canonical_store.set_mapped_version(
        db, record_id=current["id"], mapper_version=version, now=now
    )
    bucket["reprojected"] += 1
    bucket["skipped_invalid"] += work.skipped_invalid
    bucket["duplicates"] += work.duplicates
    _leave_reprojection(state, current)


def _link_work_sessions(db: Any, work: _Work, *, zone: tzinfo, now: str) -> None:
    """Re-check and link the sessions near the activities of ``work``.

    Copies a new projection no longer matches are split off first, then the
    sessions are linked to other providers' copies.
    """
    touched = {
        item.value.local_date
        for item in work.items
        if isinstance(item.value, ActivityItem)
    }
    split_unmatched_sessions(db, touched_dates=touched, zone=zone, now=now)
    link_activity_sessions(db, touched_dates=touched, zone=zone, now=now)


def _retire_unemitted(db: Any, row: Mapping[str, Any], work: _Work, *, now: str) -> int:
    """Mark the activity this raw row owns invalid when the new projection drops it.

    Ownership is the same provider and source record id. Only activity raw records are
    handled here; ``_retire_unemitted_observations`` retires observations. Returns 1
    when an active activity was marked invalid, otherwise 0.
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


def _retire_unemitted_observations(
    db: Any, row: Mapping[str, Any], work: _Work, *, now: str
) -> int:
    """Retire the observations the raw row owns and its new projection drops.

    A row whose stored payload is unusable maps no observations and names no owner,
    so it retires nothing. Returns how many observations were retired.
    """
    source_id = str(row["source_record_id"])
    day = work.observation_owners.get(source_id)
    if day is None:
        return 0
    observations = [
        item.value.observation
        for item in work.items
        if isinstance(item.value, ObservationItem)
    ]
    scope = canonical_store.ObservationScope(
        days=frozenset({day, *(o.observed_on.isoformat() for o in observations)}),
        emitted=frozenset(map(canonical_store.observation_natural_key, observations)),
    )
    return canonical_store.retire_unemitted_observations(
        db, provider=str(row["provider"]), scopes={source_id: scope}, now=now
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
        power_curve=batch.power_curve,
        power_curve_fetch=batch.power_curve_fetch,
    ).retired


def _training_load_text(row: Mapping[str, Any], loads: Callable[[str], Any]) -> str:
    """The stored dedicated training-load row a Garmin activity re-projects with."""
    if row["provider"] != _GARMIN or row["record_kind"] != ACTIVITY_RECORD_KIND:
        return ""
    return json.dumps(loads(str(row["source_record_id"])), sort_keys=True)


def _reprojection_work(
    row: Mapping[str, Any], zone: tzinfo, loads: Callable[[str], Any] | None = None
) -> _Work:
    plan = reprojection_plan(row, zone=zone, training_loads=loads)
    if plan is None:
        return _Work()
    return _work_from_plan(plan)


def _work_from_plan(plan: IngestPlan) -> _Work:
    """Flatten a plan into ordered items, dropping repeats within the same record.

    Domain batches are kept aside for the completion of the re-projection.
    """
    activities, duplicates = _distinct(
        plan.activities, lambda item: item.record.provenance.source_record_id or ""
    )
    items = [
        _Item(
            activity,
            activity.retrieved_at.isoformat()
            if activity.retrieved_at is not None
            else "",
        )
        for activity in activities
    ]
    observations, repeats = _distinct(
        plan.observations,
        lambda item: canonical_store.observation_natural_key(item.observation),
    )
    duplicates += repeats
    items.extend(_Item(observation, "") for observation in observations)
    batches, repeats = _distinct(
        plan.domain_batches, lambda batch: batch.source_record_id
    )
    duplicates += repeats
    return _Work(
        items=tuple(items),
        skipped_invalid=plan.skipped_invalid,
        duplicates=duplicates,
        domain_batches=tuple(batches),
        observation_owners=plan.observation_owners,
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
            owner=value.owner,
        )
    else:
        # Re-projection plans carry activities and observations as items; domain
        # batches are written on completion.
        raise TypeError("re-projection items must be activities or observations")


def _raw_row_at(db: Any, record_id: int) -> dict[str, Any] | None:
    """Return the active raw row with this id, or None when it is missing or deleted."""
    found = canonical_store.provider_records_after(db, after_id=record_id - 1, limit=1)
    if not found or int(found[0]["id"]) != record_id:
        return None
    return found[0]
