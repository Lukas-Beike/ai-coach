"""Store the one canonical session analysis per session (#1685).

``SessionAnalysisStage`` is a follow-up stage of the canonical backfill worker,
after the local session metrics (card M8). Each batch fingerprints every live
session from its Garmin, Wahoo and local records, the content hashes of their
stream and lap sets, whether a provider detail is stale, the frozen target
snapshot and the locally resolved thresholds, before any set is decoded. Only
sessions whose stored ``activity_detail_analysis`` row is not a version-3 row
with that fingerprint are recomputed, at most ``batch_size`` per transaction,
so a pass without changes decodes nothing and writes nothing.

A session without such a row is computed when it has a stream or lap set; a
version-3 row whose session lost its sets is rewritten without an analysis.
Existing target snapshots, including those of older rows, are carried over
unchanged; a session without one freezes its matched planned targets when it is
first computed. Intervals.icu records, detail sets and thresholds are never read.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, timedelta, tzinfo
from typing import Any, Final

from backend.activities.activity_summary import activity_summaries
from backend.activities.detail_merge import merge_details
from backend.canonical.activity_summary import (
    stored_activity_key,
    summary_is_indoor,
    summary_local_date,
)
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ProviderId, Sport
from backend.db import activity_detail_store
from backend.db.activity_detail_store import FullStreamKey
from backend.db.repositories import KeyValueRepository
from backend.performance.canonical_detail import detail_candidates
from backend.performance.canonical_session_analysis import (
    ANALYSIS_VERSION,
    METHOD_VERSION,
    analysis_fingerprint,
    analysis_records,
    calendar_profile,
    session_analysis,
)
from backend.performance.local_tss import THRESHOLD_KINDS, DatedThresholds
from backend.planning.target_snapshot import freeze_targets
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_table_reader import CanonicalTableReader

# The application logger: only it has handlers (see observability.configure_logging).
_LOGGER = logging.getLogger("intervals_coach")
STAGE: Final = "session_analysis"
STATE_KEY: Final = "session_analysis_state"
DEFAULT_BATCH_SIZE: Final = 100
_INTERVALS: Final = ProviderId.INTERVALS.value

PlannedUnits = Callable[[], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class _Session:
    """One session's analysis inputs, read without decoding any set."""

    summary: Mapping[str, Any]
    records: tuple[ActivityRecord, ...]
    # Every active record, Intervals.icu included: only for snapshot carry-over.
    all_records: tuple[ActivityRecord, ...]
    keys: tuple[FullStreamKey, ...]
    stale: bool
    targets: Mapping[str, Any] | None
    thresholds: dict[str, Any]

    @property
    def session_id(self) -> str:
        return str(self.summary["id"])

    def fingerprint(self, targets: Mapping[str, Any] | None) -> str:
        return analysis_fingerprint(
            self.records,
            [key.content_sha256 for key in self.keys],
            stale=self.stale,
            targets=targets,
            thresholds=self.thresholds,
        )


@dataclass(slots=True)
class _Tally:
    """Content-free counts of one batch."""

    written: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)


def _thresholds(db: Any, reader: CanonicalTableReader) -> DatedThresholds:
    """Local, Garmin and Wahoo thresholds by day; Intervals.icu values are skipped."""
    return DatedThresholds(
        [
            item
            for kind in THRESHOLD_KINDS
            for item in reader.observations(db, kind)
            if item.provenance.provider is not ProviderId.INTERVALS
        ],
        [
            item
            for item in reader.zone_configurations(db)
            if item.provenance.provider is not ProviderId.INTERVALS
        ],
    )


def _threshold_parts(
    summary: Mapping[str, Any], thresholds: DatedThresholds
) -> dict[str, Any]:
    """The FTP and threshold HR of the session's sport on its local day."""
    try:
        sport = Sport(str(summary.get("sport")))
        day = date.fromisoformat(summary_local_date(summary))
    except ValueError:
        return {}
    chosen = thresholds.for_session(sport, day, indoor=summary_is_indoor(summary))
    return {
        name: None if value is None else value.fingerprint_part()
        for name, value in (("ftp", chosen.ftp), ("threshold_hr", chosen.threshold_hr))
    }


def _is_stale(
    keys: Sequence[FullStreamKey], current: Mapping[tuple[str, str], str]
) -> bool:
    return any(
        key.summary_sha256
        and (latest := current.get((key.provider, key.provider_activity_id)))
        and latest != key.summary_sha256
        for key in keys
    )


def _stored_targets(row: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    payload = None if row is None else row.get("payload")
    targets = payload.get("target_snapshot") if isinstance(payload, dict) else None
    return targets if isinstance(targets, dict) else None


def _value(threshold: Mapping[str, Any] | None) -> float | None:
    value = None if threshold is None else threshold.get("value")
    return float(value) if isinstance(value, int | float) else None


class SessionAnalysisStage:
    """Backfill follow-up that keeps the stored canonical session analyses current."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
        clock: Callable[[], str],
        planned_units: PlannedUnits = list,
        reader: CanonicalTableReader | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._clock = clock
        self._planned_units = planned_units
        self._reader = reader or CanonicalTableReader()
        self._batch_size = batch_size

    @property
    def stage(self) -> str:
        return STAGE

    def run_batch(self, db: Any) -> BatchReport:
        """Recompute up to one batch of changed sessions in the caller's transaction."""
        now = self._clock()
        summaries, sessions = self._sessions(db)
        changed = [
            (session, fingerprint)
            for session, row in sessions
            if (fingerprint := session.fingerprint(session.targets))
            != _current_fingerprint(row)
        ]
        batch = changed[: self._batch_size]
        tally = _Tally()
        planned: list[dict[str, Any]] | None = None
        for session, fingerprint in batch:
            if session.targets is None and session.keys:
                planned = self._planned_units() if planned is None else planned
            self._write(db, session, fingerprint, summaries, planned or [], now, tally)
        done = len(changed) <= self._batch_size
        counts = {
            "sessions": len(sessions),
            "computed": len(batch),
            "pending": len(changed) - len(batch),
            "outcomes": dict(sorted(tally.outcomes.items())),
            "written": tally.written,
        }
        state = self._state(db)
        self._save(
            db,
            {
                "status": "complete" if done else "running",
                "method_version": METHOD_VERSION,
                "completed_at": now if done else state.get("completed_at"),
                "counts": counts,
            },
        )
        # Counts only: outcome names, never values or identifiers.
        _LOGGER.info(
            "Canonical session analyses reconciled",
            extra={"event": "session_analysis_reconciled", "context": counts},
        )
        return BatchReport(items=len(batch), done=done)

    def _sessions(
        self, db: Any
    ) -> tuple[
        Sequence[Mapping[str, Any]], list[tuple[_Session, Mapping[str, Any] | None]]
    ]:
        """Every session that has analysis inputs or a version-3 row, unread."""
        records_by_id = {
            session_id: records
            for session_id, records in self._reader.activity_sessions(db)
            if records
        }
        summaries = activity_summaries(
            records_by_id.items(), self._zone_provider() or UTC
        )
        ids = [str(summary["id"]) for summary in summaries]
        keys = {
            session_id: tuple(key for key in values if key.provider != _INTERVALS)
            for session_id, values in activity_detail_store.analysis_set_keys(
                db, ids
            ).items()
        }
        rows = activity_detail_store.analysis_rows_for(db, ids)
        current = self._reader.summary_fingerprints(
            db,
            {
                (key.provider, key.provider_activity_id)
                for values in keys.values()
                for key in values
            },
        )
        thresholds = _thresholds(db, self._reader)
        sessions = []
        for summary in summaries:
            session_id = str(summary["id"])
            own = keys.get(session_id, ())
            row = rows.get(session_id)
            records = analysis_records(records_by_id[session_id])
            if not records:
                own = ()
            if not own and _version(row) != ANALYSIS_VERSION:
                continue
            session = _Session(
                summary=summary,
                records=records,
                all_records=tuple(records_by_id[session_id]),
                keys=own,
                stale=_is_stale(own, current),
                targets=_stored_targets(row),
                thresholds=_threshold_parts(summary, thresholds) if own else {},
            )
            sessions.append((session, row))
        return summaries, sessions

    def _write(
        self,
        db: Any,
        session: _Session,
        fingerprint: str,
        summaries: Sequence[Mapping[str, Any]],
        planned: list[dict[str, Any]],
        now: str,
        tally: _Tally,
    ) -> None:
        targets = session.targets
        if targets is None and session.keys:
            targets = _merged_targets(db, session.all_records)
            if targets is None:
                targets = _freeze(session, summaries, planned, now)
                tally.outcomes["targets_frozen"] += targets is not None
            if targets is not None:
                fingerprint = session.fingerprint(targets)
        payload = self._payload(db, session, targets)
        tally.outcomes[_outcome(session, payload)] += 1
        outcome = activity_detail_store.save_analysis(
            db,
            session.session_id,
            analysis_version=ANALYSIS_VERSION,
            input_sha256=fingerprint,
            payload=payload,
            now=now,
        )
        tally.written += outcome is not activity_detail_store.WriteOutcome.UNCHANGED

    def _payload(
        self, db: Any, session: _Session, targets: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method_version": METHOD_VERSION,
            "target_snapshot": targets,
            "session_analysis": None,
            "calendar_profile": None,
            "stale": session.stale,
            "source": " / ".join(
                dict.fromkeys(
                    record.provenance.label
                    for record in session.records
                    if record.provenance.label
                )
            )
            or None,
            "observed_at": max((key.fetched_at for key in session.keys), default=None),
        }
        if not session.keys or session.stale:
            return payload
        stored = activity_detail_store.detail_sets_for_session(db, session.session_id)
        merged = merge_details(detail_candidates(session.records, stored))
        payload["session_analysis"] = session_analysis(session.records, merged, targets)
        payload["calendar_profile"] = calendar_profile(
            session.records,
            merged,
            ftp_w=_value(session.thresholds.get("ftp")),
            threshold_hr_bpm=_value(session.thresholds.get("threshold_hr")),
        )
        return payload

    def mark_failed(self, db: Any) -> None:
        state = self._state(db)
        state["status"] = "failed"
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free status and counts of the last batch."""
        return summarize_session_analysis(self._key_values, db)

    def _state(self, db: Any) -> dict[str, Any]:
        return _load_state(self._key_values, db)

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def _version(row: Mapping[str, Any] | None) -> int | None:
    return None if row is None else row.get("analysis_version")


def _current_fingerprint(row: Mapping[str, Any] | None) -> str | None:
    """The stored fingerprint of a version-3 row; older rows never match."""
    if _version(row) != ANALYSIS_VERSION or row is None:
        return None
    return row.get("input_sha256")


def _outcome(session: _Session, payload: Mapping[str, Any]) -> str:
    if not session.keys:
        return "no_details"
    if session.stale:
        return "stale"
    return "profile" if payload.get("calendar_profile") else "analysis"


def _freeze(
    session: _Session,
    summaries: Sequence[Mapping[str, Any]],
    planned: list[dict[str, Any]],
    now: str,
) -> dict[str, Any] | None:
    """Freeze the matched planned targets; matching compares a day either side."""
    if not planned:
        return None
    try:
        day = date.fromisoformat(summary_local_date(session.summary))
    except ValueError:
        return None
    window = {(day + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)}
    around = [item for item in summaries if summary_local_date(item) in window]
    return freeze_targets(
        planned,
        around,
        stored_activity_key(session.summary),
        {"ftp": _value(session.thresholds.get("ftp"))},
        now,
    )


def _merged_targets(
    db: Any, records: Sequence[ActivityRecord]
) -> Mapping[str, Any] | None:
    """A snapshot kept under a session merged into this one, by any record."""
    for record in records:
        provider = record.provenance.provider
        if provider is None:
            continue
        found = _stored_targets(
            activity_detail_store.analysis_row_for_record(
                db, provider.value, record.activity_id
            )
        )
        if found is not None:
            return found
    return None


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}


def summarize_session_analysis(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Content-free status and counts of the last batch, for diagnostics."""
    state = _load_state(key_values, db)
    return {
        "status": state.get("status", "pending"),
        "method_version": state.get("method_version"),
        "counts": state.get("counts", {}),
    }


__all__ = ["STAGE", "SessionAnalysisStage", "summarize_session_analysis"]
