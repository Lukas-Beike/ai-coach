"""Store the one canonical session analysis per session (#1685).

``SessionAnalysisStage`` is a follow-up stage of the canonical backfill worker,
after the local session metrics (card M8). Each batch fingerprints every live
session from its Garmin, Wahoo and local records, the content hashes of their
stream and lap sets, whether a provider detail is stale, the frozen target
snapshot and the locally resolved thresholds, before any set is decoded. Only
sessions whose stored ``activity_detail_analysis`` row is not a version-3 row
with that fingerprint are recomputed, at most ``batch_size`` per transaction and
no more than the backfill's batch time allows (#2287), so a pass without
changes decodes nothing and writes nothing. The worker's ``prefetch`` freezes
targets, decodes and analyses the batch with a reader first, so the writer
transaction only re-checks the fingerprints and writes (#2311).

A session without such a row is computed when it has a stream or lap set; a
version-3 row whose session lost its sets is rewritten without an analysis.
Existing target snapshots, including those of older rows, are carried over
unchanged; a session without one freezes its matched planned targets when it is
first computed. Intervals.icu records, detail sets and thresholds are never read.

Each row also stores the session's report zone times (``zone_times``, #1743):
heart-rate, power and run pace seconds per zone counted from the merged streams
with the zones in effect on the session day (``session_zones``). Their
thresholds and limits are part of the fingerprint.

It also stores ``hr_histogram``: the seconds per integer bpm of the merged heart-rate
stream, which the local load stage reads for the heart-rate branch of card M6 (v5).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, Final

from backend.activities.activity_summary import activity_summaries
from backend.activities.detail_merge import MergedDetail, merge_details
from backend.activities.stream_zones import LABEL as ZONE_LABEL
from backend.activities.stream_zones import zone_sources, zone_times
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_summary import (
    stored_activity_key,
    summary_is_indoor,
    summary_local_date,
)
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import Sport
from backend.db import activity_detail_store
from backend.db.activity_detail_store import FullStreamKey
from backend.db.repositories import KeyValueRepository
from backend.performance.canonical_detail import detail_candidates, stored_targets
from backend.performance.canonical_session_analysis import (
    ANALYSIS_VERSION,
    METHOD_VERSION,
    analysis_fingerprint,
    calendar_profile,
    session_analysis,
    session_heart_rate_histogram,
)
from backend.performance.local_tss import THRESHOLD_KINDS, DatedThresholds
from backend.performance.session_zones import (
    dated_thresholds,
    own_configurations,
    session_zone_settings,
    zone_settings_part,
)
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences
from backend.planning.target_snapshot import freeze_targets
from backend.sync.canonical_backfill import (
    BatchReport,
    precomputed_batch,
    timed_batch,
)
from backend.sync.canonical_table_reader import CanonicalTableReader

# The application logger: only it has handlers (see observability.configure_logging).
_LOGGER = logging.getLogger("intervals_coach")
STAGE: Final = "session_analysis"
STATE_KEY: Final = "session_analysis_state"
DEFAULT_BATCH_SIZE: Final = 100

PlannedUnits = Callable[[], list[dict[str, Any]]]
Preferences = Callable[[Any], SourcePreferences]
# Targets freeze only for sessions this recent, as the first detail load did;
# older sessions would be matched against plans edited since.
FREEZE_WINDOW_DAYS: Final = 7


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
    # The Intervals.icu summary hash a detail fetch settled; kept, not an input.
    fetched_summary: str | None = None
    # The zones the report zone times are counted with (part of ``thresholds``).
    zones: ZoneSettings | None = None

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


@dataclass(frozen=True, slots=True)
class _Analysed:
    """One session's computed row and its outcome, ready to be written."""

    fingerprint: str
    payload: dict[str, Any]
    outcome: str
    frozen: bool
    # Targets looked up or frozen for a session whose row had none; the writer
    # derives them again and drops the result when they differ.
    derived: Mapping[str, Any] | None = None


@dataclass(slots=True)
class _Tally:
    """Content-free counts of one batch."""

    written: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)


def _thresholds(
    db: Any, reader: CanonicalTableReader, preferences: SourcePreferences
) -> tuple[DatedThresholds, tuple[ZoneConfiguration, ...]]:
    """Local, Garmin and Wahoo thresholds by day, and their zone configurations.

    Intervals.icu values are skipped.
    """
    configurations = own_configurations(reader.zone_configurations(db))
    thresholds = dated_thresholds(
        [item for kind in THRESHOLD_KINDS for item in reader.observations(db, kind)],
        configurations,
        preferences,
    )
    return thresholds, configurations


def _threshold_parts(
    summary: Mapping[str, Any],
    thresholds: DatedThresholds,
    zones: ZoneSettings | None,
) -> dict[str, Any]:
    """The FTP and threshold HR of the session's sport on its local day.

    ``zones`` adds the thresholds and limits of the report zone times.
    """
    try:
        sport = Sport(str(summary.get("sport")))
        day = date.fromisoformat(summary_local_date(summary))
    except ValueError:
        return {}
    chosen = thresholds.for_session(sport, day, indoor=summary_is_indoor(summary))
    parts: dict[str, Any] = {
        name: None if value is None else value.fingerprint_part()
        for name, value in (("ftp", chosen.ftp), ("threshold_hr", chosen.threshold_hr))
    }
    parts["zones"] = zone_settings_part(zones)
    return parts


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


def _fetched_summary(row: Mapping[str, Any] | None) -> str | None:
    payload = None if row is None else row.get("payload")
    value = payload.get("summary_sha256") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


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
        preferences: Preferences = lambda _db: NO_PREFERENCES,
        reader: CanonicalTableReader | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._clock = clock
        self._planned_units = planned_units
        self._preferences = preferences
        self._reader = reader or CanonicalTableReader()
        self._batch_size = batch_size
        self._prepared: dict[str, tuple[str, _Analysed]] | None = None
        # The clock reading the prefetch froze targets with.
        self._prepared_at: str | None = None

    @property
    def stage(self) -> str:
        return STAGE

    def prefetch(self, database: Callable[[], Any]) -> None:
        """Analyse one batch of changed sessions with a reader, before the writer."""
        now = self._clock()
        prepared: dict[str, tuple[str, _Analysed]] = {}
        with database().reader() as db:
            summaries, _, changed = self._changed(db)
            context = _FreezeContext(summaries, self._planned_units, now)
            for session, fingerprint in timed_batch(changed, self._batch_size):
                prepared[session.session_id] = (
                    fingerprint,
                    self._analyse(db, session, fingerprint, context),
                )
        self._prepared, self._prepared_at = prepared, now

    def run_batch(self, db: Any) -> BatchReport:
        """Write up to one batch of changed sessions in the caller's transaction.

        Sessions the prefetch analysed are written while their fingerprint is
        unchanged; without a prefetch the batch analyses inline.
        """
        now = self._clock()
        prepared, self._prepared = self._prepared, None
        prepared_at, self._prepared_at = self._prepared_at, None
        summaries, total, changed = self._changed(db)
        tally = _Tally()
        context = _FreezeContext(summaries, self._planned_units, now)
        if prepared:
            # Freeze again at the prefetch's time, so equal targets compare equal.
            prepared = self._current_targets(
                db,
                changed,
                prepared,
                _FreezeContext(summaries, self._planned_units, prepared_at or now),
            )
        computed = 0
        for (session, _), analysed in precomputed_batch(
            [
                (session.session_id, fingerprint, (session, fingerprint))
                for session, fingerprint in changed
            ],
            self._batch_size,
            prepared,
            lambda entry: self._analyse(db, entry[0], entry[1], context),
        ):
            self._store(db, session, analysed, now, tally)
            computed += 1
        done = computed == len(changed)
        counts = {
            "sessions": total,
            "computed": computed,
            "pending": len(changed) - computed,
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
        return BatchReport(items=computed, done=done)

    def _changed(
        self, db: Any
    ) -> tuple[Sequence[Mapping[str, Any]], int, list[tuple[_Session, str]]]:
        """The summaries, the session count and the sessions whose stored row
        carries another fingerprint."""
        summaries, sessions = self._sessions(db)
        return (
            summaries,
            len(sessions),
            [
                (session, fingerprint)
                for session, row in sessions
                if (fingerprint := session.fingerprint(session.targets))
                != _current_fingerprint(row)
            ],
        )

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
        keys = activity_detail_store.analysis_set_keys(db, ids)
        rows = activity_detail_store.analysis_rows_for(db, ids)
        current = self._reader.summary_fingerprints(
            db,
            {
                (key.provider, key.provider_activity_id)
                for values in keys.values()
                for key in values
            },
        )
        thresholds, configurations = _thresholds(
            db, self._reader, self._preferences(db)
        )
        sessions: list[tuple[_Session, Mapping[str, Any] | None]] = []
        for summary in summaries:
            session_id = str(summary["id"])
            own = keys.get(session_id, ())
            row = rows.get(session_id)
            records = records_by_id[session_id]
            if not own and _version(row) != ANALYSIS_VERSION:
                continue
            zones = (
                session_zone_settings(summary, thresholds, configurations)
                if own
                else None
            )
            session = _Session(
                summary=summary,
                records=records,
                all_records=tuple(records_by_id[session_id]),
                keys=own,
                stale=_is_stale(own, current),
                targets=_stored_targets(row),
                thresholds=_threshold_parts(summary, thresholds, zones) if own else {},
                fetched_summary=_fetched_summary(row),
                zones=zones,
            )
            sessions.append((session, row))
        return summaries, sessions

    @staticmethod
    def _targets(
        db: Any, session: _Session, context: _FreezeContext
    ) -> tuple[Mapping[str, Any] | None, bool]:
        """The session's targets and whether they were frozen just now."""
        if session.targets is not None or not session.keys:
            return session.targets, False
        targets = stored_targets(db, session.session_id, session.all_records)
        if targets is not None:
            return targets, False
        targets = context.freeze(session)
        return targets, targets is not None

    def _current_targets(
        self,
        db: Any,
        changed: Sequence[tuple[_Session, str]],
        prepared: dict[str, tuple[str, _Analysed]],
        context: _FreezeContext,
    ) -> dict[str, tuple[str, _Analysed]]:
        """Drop prefetched rows whose derived targets changed since (#2311)."""
        sessions = {session.session_id: session for session, _ in changed}
        return {
            session_id: (fingerprint, analysed)
            for session_id, (fingerprint, analysed) in prepared.items()
            if analysed.derived is None
            or (
                session_id in sessions
                and self._targets(db, sessions[session_id], context)[0]
                == analysed.derived
            )
        }

    def _analyse(
        self,
        db: Any,
        session: _Session,
        fingerprint: str,
        context: _FreezeContext,
    ) -> _Analysed:
        """Freeze the session's targets if needed and compute its row; no write."""
        targets, frozen = self._targets(db, session, context)
        derived = None if targets is session.targets else targets
        if derived is not None:
            fingerprint = session.fingerprint(derived)
        payload = self._payload(db, session, targets)
        return _Analysed(
            fingerprint, payload, _outcome(session, payload), frozen, derived
        )

    @staticmethod
    def _store(
        db: Any, session: _Session, analysed: _Analysed, now: str, tally: _Tally
    ) -> None:
        tally.outcomes["targets_frozen"] += analysed.frozen
        tally.outcomes[analysed.outcome] += 1
        outcome = activity_detail_store.save_analysis(
            db,
            session.session_id,
            analysis_version=ANALYSIS_VERSION,
            input_sha256=analysed.fingerprint,
            payload=analysed.payload,
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
            "zone_times": None,
            "hr_histogram": None,
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
        if session.fetched_summary is not None:
            payload["summary_sha256"] = session.fetched_summary
        if not session.keys or session.stale:
            return payload
        stored = activity_detail_store.detail_sets_for_session(db, session.session_id)
        try:
            merged = merge_details(detail_candidates(session.records, stored))
            analysis = session_analysis(session.records, merged, targets)
            # The zones of the zone times, so the profile colors and the zones
            # of one session agree (watch zone set and its limits included).
            zones = session.zones or ZoneSettings(
                ftp=_value(session.thresholds.get("ftp")),
                lthr=_value(session.thresholds.get("threshold_hr")),
            )
            profile = calendar_profile(session.records, merged, zones)
        except ArithmeticError, TypeError, ValueError:
            # One unreadable session must not stop the pass; it stays without
            # an analysis until one of its inputs changes.
            payload["failed"] = True
            return payload
        payload["session_analysis"] = analysis
        payload["calendar_profile"] = profile
        payload["zone_times"] = _zone_times(session, merged)
        payload["hr_histogram"] = session_heart_rate_histogram(session.records, merged)
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


def _zone_times(session: _Session, merged: MergedDetail) -> dict[str, Any] | None:
    """The stored report zone times of one session, or None without any."""
    if session.zones is None:
        return None
    times = zone_times(
        merged.streams,
        session.zones,
        pace=session.summary.get("sport") == Sport.RUN.value,
    )
    if not times:
        return None
    sources = zone_sources(session.zones)
    return {
        "label": ZONE_LABEL,
        "sources": {sensor: sources[sensor] for sensor in times},
        **times,
    }


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
    if payload.get("failed"):
        return "failed"
    return "profile" if payload.get("calendar_profile") else "analysis"


class _FreezeContext:
    """Planned units and sessions by local day, read once per batch when needed."""

    def __init__(
        self,
        summaries: Sequence[Mapping[str, Any]],
        planned_units: PlannedUnits,
        now: str,
    ) -> None:
        self._summaries = summaries
        self._planned_units = planned_units
        self._planned: list[dict[str, Any]] | None = None
        self._by_day: dict[str, list[Mapping[str, Any]]] | None = None
        self._first_day = datetime.fromisoformat(now).astimezone(
            UTC
        ).date() - timedelta(days=FREEZE_WINDOW_DAYS)
        self._now = now

    def freeze(self, session: _Session) -> dict[str, Any] | None:
        """Freeze a recent session's matched planned targets, a day either side."""
        try:
            day = date.fromisoformat(summary_local_date(session.summary))
        except ValueError:
            return None
        if day < self._first_day:
            return None
        if self._planned is None:
            self._planned = self._planned_units()
        if not self._planned:
            return None
        if self._by_day is None:
            self._by_day = {}
            for item in self._summaries:
                self._by_day.setdefault(summary_local_date(item), []).append(item)
        around = [
            item
            for offset in (-1, 0, 1)
            for item in self._by_day.get((day + timedelta(days=offset)).isoformat(), [])
        ]
        return freeze_targets(
            self._planned,
            around,
            stored_activity_key(session.summary),
            {"ftp": _value(session.thresholds.get("ftp"))},
            self._now,
        )


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
