"""Store the local session metrics (card M8, #1680) as derived observations.

``SessionMetricsStage`` is a follow-up stage of the canonical backfill worker.
Each batch fingerprints every live ride and run from its summary, the content
hashes of its full-resolution stream sets and its members, before any stream is
decoded. Only sessions whose stored rows carry another fingerprint are
recomputed, at most ``batch_size`` per transaction within the batch time
(#2287), so a pass without changes decodes nothing and writes nothing. The
worker's ``prefetch`` decodes and computes the batch with a reader first, so the
writer transaction only re-checks the fingerprints and writes (#2311). A
computed session upserts one derived observation per metric it has, owned by
the session; its other rows and the rows of sessions that are gone are
retired. Sessions computed without any value keep their fingerprint in the
stage state, so they are not decoded again until an input changes. Streams
missing from storage are not fetched here.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from typing import Any, Final

from backend.activities.activity_summary import activity_summaries
from backend.activities.detail_contract import measured_order
from backend.activities.detail_merge import merge_details
from backend.canonical.activity_summary import summary_local_date
from backend.canonical.records import (
    ActivityRecord,
    MetricValue,
    Observation,
    Provenance,
)
from backend.canonical.vocabulary import (
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import activity_detail_store, canonical_store
from backend.db.repositories import KeyValueRepository
from backend.performance.analysis_input import analysis_input
from backend.performance.canonical_detail import (
    detail_candidates,
    primary_analysis_record,
)
from backend.performance.session_metrics import (
    METHOD_ID,
    METHOD_VERSION,
    SessionMetrics,
    metrics_fingerprint,
    session_metrics,
    wants_metrics,
)
from backend.performance.session_metrics_reads import (
    DERIVED_LABEL,
    stored_session_metrics,
)
from backend.sync.canonical_backfill import (
    BatchReport,
    precomputed_batch,
    timed_batch,
)
from backend.sync.canonical_table_reader import CanonicalTableReader

# The application logger: only it has handlers (see observability.configure_logging).
_LOGGER = logging.getLogger("intervals_coach")
STAGE: Final = "session_metrics"
STATE_KEY: Final = "session_metrics_state"
DEFAULT_BATCH_SIZE: Final = 100


def _members(records: Sequence[ActivityRecord]) -> list[list[object]]:
    return [
        [
            record.provenance.provider,
            record.activity_id,
            record.provenance.recorded_by,
            record.device_type,
        ]
        for record in measured_order(records)
    ]


def _analysis_activity(
    db: Any, session_id: str, records: Sequence[ActivityRecord]
) -> dict[str, Any]:
    """The merged analysis input of the session's full-resolution streams."""
    stored = activity_detail_store.full_stream_sets_for_session(db, session_id)
    merged = merge_details(detail_candidates(records, stored))
    adapted = analysis_input(
        primary_analysis_record(records),
        merged.streams,
        None,
        members=measured_order(records),
    )
    return adapted.activity


def _recorded_by(summary: Mapping[str, Any]) -> RecordingOrigin:
    try:
        return RecordingOrigin(str(summary.get("recorded_by")))
    except ValueError:
        return RecordingOrigin.UNKNOWN


def _observations(
    summary: Mapping[str, Any], metrics: SessionMetrics
) -> list[tuple[Observation, Mapping[str, Any]]]:
    result = []
    for kind, value in metrics.values.items():
        observation = Observation(
            kind=kind,
            value=MetricValue(round(value, 4), kind.unit),
            observed_on=date.fromisoformat(summary_local_date(summary)),
            observed_at=datetime.fromisoformat(str(summary["started_at"])),
            provenance=Provenance(
                provider=None,
                source_kind=SourceKind.DERIVED,
                source_record_id=str(summary["id"]),
                recorded_by=_recorded_by(summary),
                retrieved_at=None,
                label=DERIVED_LABEL,
            ),
            sport=Sport(str(summary["sport"])),
            method=METHOD_ID,
            method_version=METHOD_VERSION,
            input_fingerprint=metrics.fingerprint,
        )
        result.append((observation, metrics.details.get(kind, {})))
    return result


@dataclass(slots=True)
class _Plan:
    """Which sessions stay as stored and which need a recompute."""

    keep: set[str] = field(default_factory=set)
    empty: dict[str, str] = field(default_factory=dict)
    changed: list[tuple[Mapping[str, Any], str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Scan:
    """One read of every session's inputs, without decoding a stream."""

    sessions: Mapping[str, Sequence[ActivityRecord]]
    summaries: Sequence[Mapping[str, Any]]
    stream_keys: Mapping[str, Sequence[Any]]
    stored: Mapping[str, Mapping[str, Mapping[str, Any]]]
    state: dict[str, Any]
    plan: _Plan

    def compute(
        self, db: Any, item: Mapping[str, Any], fingerprint: str
    ) -> SessionMetrics:
        """Decode the session's streams and compute its metrics."""
        session_id = str(item["id"])
        activity = (
            _analysis_activity(db, session_id, self.sessions[session_id])
            if session_id in self.stream_keys
            else None
        )
        return session_metrics(item, activity, fingerprint)


@dataclass(slots=True)
class _Tally:
    """Content-free counts of one batch."""

    written: int = 0
    values: Counter[str] = field(default_factory=Counter)
    bases: Counter[str] = field(default_factory=Counter)


def _plan(
    summaries: Sequence[Mapping[str, Any]],
    sessions: Mapping[str, Sequence[ActivityRecord]],
    stream_keys: Mapping[str, Sequence[Any]],
    stored: Mapping[str, Mapping[str, Mapping[str, Any]]],
    empty: Mapping[str, str],
) -> _Plan:
    """Fingerprint every session before any stream is decoded."""
    plan = _Plan()
    for summary in summaries:
        session_id = str(summary["id"])
        fingerprint = metrics_fingerprint(
            summary,
            [key.content_sha256 for key in stream_keys.get(session_id, ())],
            _members(sessions[session_id]),
        )
        rows = stored.get(session_id, {})
        if rows and all(
            row.get("input_fingerprint") == fingerprint for row in rows.values()
        ):
            plan.keep.update(row["natural_key"] for row in rows.values())
        elif not rows and empty.get(session_id) == fingerprint:
            plan.empty[session_id] = fingerprint
        else:
            plan.changed.append((summary, fingerprint))
    return plan


def _write_session(
    db: Any,
    summary: Mapping[str, Any],
    metrics: SessionMetrics,
    now: str,
    tally: _Tally,
) -> set[str]:
    """Upsert the session's values; return their natural keys (empty: no value)."""
    try:
        observations = _observations(summary, metrics)
    except TypeError, ValueError:
        # Outside the canonical bounds: this session keeps no value.
        observations = []
    if not observations:
        tally.values["none"] += 1
    keys: set[str] = set()
    for observation, derivation in observations:
        keys.add(canonical_store.observation_natural_key(observation))
        outcome = canonical_store.upsert_observation(
            db,
            observation,
            mapper_version=METHOD_VERSION,
            now=now,
            owner=str(summary["id"]),
            derivation=derivation,
        )
        tally.written += outcome is not canonical_store.WriteOutcome.UNCHANGED
        tally.values[observation.kind.value] += 1
        if basis := derivation.get("basis"):
            tally.bases[f"{observation.kind.value}:{basis}"] += 1
    return keys


class SessionMetricsStage:
    """Backfill follow-up that keeps the stored local session metrics current."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
        clock: Callable[[], str],
        reader: CanonicalTableReader | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._clock = clock
        self._reader = reader or CanonicalTableReader()
        self._batch_size = batch_size
        self._prepared: dict[str, tuple[str, SessionMetrics]] | None = None

    @property
    def stage(self) -> str:
        return STAGE

    def prefetch(self, database: Callable[[], Any]) -> None:
        """Compute one batch of changed sessions with a reader, before the writer."""
        prepared: dict[str, tuple[str, SessionMetrics]] = {}
        with database().reader() as db:
            scan = self._scan(db)
            for item, fingerprint in timed_batch(scan.plan.changed, self._batch_size):
                prepared[str(item["id"])] = (
                    fingerprint,
                    scan.compute(db, item, fingerprint),
                )
        self._prepared = prepared

    def run_batch(self, db: Any) -> BatchReport:
        """Write up to one batch of changed sessions in the caller's transaction.

        Sessions the prefetch computed are written while their fingerprint is
        unchanged; without a prefetch the batch computes inline.
        """
        now = self._clock()
        prepared, self._prepared = self._prepared, None
        scan = self._scan(db)
        stored, state, plan = scan.stored, scan.state, scan.plan
        keep, next_empty = plan.keep, plan.empty
        tally = _Tally()
        computed = 0
        for item, metrics in precomputed_batch(
            [
                (str(item["id"]), fingerprint, (item, fingerprint))
                for item, fingerprint in plan.changed
            ],
            self._batch_size,
            prepared,
            lambda entry: scan.compute(db, *entry),
        ):
            computed += 1
            summary, fingerprint = item
            session_id = str(summary["id"])
            written = _write_session(db, summary, metrics, now, tally)
            if written:
                keep.update(written)
            else:
                next_empty[session_id] = fingerprint
        pending = plan.changed[computed:]
        for waiting, _ in pending:
            # Not recomputed yet: its stored rows stay until a later batch.
            keep.update(
                row["natural_key"]
                for row in stored.get(str(waiting["id"]), {}).values()
            )
        retired = canonical_store.retire_derived_observations(
            db, METHOD_ID, keep=keep, now=now
        )
        done = not pending
        counts = {
            "sessions": len(scan.summaries),
            "with_streams": len(scan.stream_keys),
            "computed": computed,
            "pending": len(pending),
            "values": dict(sorted(tally.values.items())),
            "bases": dict(sorted(tally.bases.items())),
            "written": tally.written,
            "retired": retired,
        }
        self._save(
            db,
            {
                "status": "complete" if done else "running",
                "method_version": METHOD_VERSION,
                "completed_at": now if done else state.get("completed_at"),
                "counts": counts,
                "empty": next_empty,
            },
        )
        # Counts only: metric names and bases, never values or identifiers.
        _LOGGER.info(
            "Local session metrics reconciled",
            extra={"event": "session_metrics_reconciled", "context": counts},
        )
        return BatchReport(items=computed, done=done)

    def _scan(self, db: Any) -> _Scan:
        """Fingerprint every live ride and run before any stream is decoded."""
        sessions = {
            session_id: records
            for session_id, records in self._reader.activity_sessions(db)
            if records
        }
        summaries = [
            summary
            for summary in activity_summaries(
                sessions.items(), self._zone_provider() or UTC
            )
            if wants_metrics(summary)
        ]
        stream_keys = activity_detail_store.full_stream_keys(
            db, [str(summary["id"]) for summary in summaries]
        )
        stored = stored_session_metrics(db)
        state = self._state(db)
        plan = _plan(summaries, sessions, stream_keys, stored, state.get("empty") or {})
        return _Scan(sessions, summaries, stream_keys, stored, state, plan)

    def mark_failed(self, db: Any) -> None:
        state = self._state(db)
        state["status"] = "failed"
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free status and counts of the last batch."""
        return summarize_session_metrics(self._key_values, db)

    def _state(self, db: Any) -> dict[str, Any]:
        return _load_state(self._key_values, db)

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}


def summarize_session_metrics(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Content-free status and counts of the last batch, for diagnostics."""
    state = _load_state(key_values, db)
    return {
        "status": state.get("status", "pending"),
        "method_version": state.get("method_version"),
        "counts": state.get("counts", {}),
    }
