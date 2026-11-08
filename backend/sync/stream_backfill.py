"""Re-fetch the full-resolution streams of the activity history (#1763).

After the Intervals.icu purge the older sessions hold no per-second streams; the
sessions the regular detail fetch no longer reaches (older than its 90-day window,
or fetched without the original file) keep only summaries, chart points or nothing.
Card M8 and the CP/CS, running-best, decoupling and HR-distribution methods need
the full-resolution record streams, which only the original FIT files carry.

The ``stream_backfill`` chain of a provider (Garmin through the Personal API,
Wahoo through its workout list) walks the live sessions newest first and downloads
the FIT file of each active, non-manual, non-strength record that has no
full-resolution stream set of its own yet. It stores the file's stream and device lap sets
exactly like the regular detail fetch, so a second run finds nothing to read.
Strength files are never read: their sets carry the athlete's Garmin Connect
corrections.

At most ``batch_limit`` records are read per job (the whole last day of a batch is
included, so a day is never split). The ``stream_history`` cursor moves to the oldest
day of a complete batch and to the floor once nothing is left. A rate limit, a
rejected key or a transient error ends the job with the cursor unchanged; files
already stored stay. A record without a file, or without sensor records in it, is
kept in the state (its id, never in diagnostics) and not read again; a record whose
download fails three runs in a row or answers with a client error is kept out the
same way. A job without ``end_date`` starts the chain again and lets those
failed records retry. Nothing is written to a provider, and nothing before the
history floor is read.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final, Protocol

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.activity_detail import ActivityStreamSet, ActivityStrengthSetSet
from backend.canonical.mapping import MappingResult
from backend.canonical.vocabulary import (
    ActivityDetailKind,
    ActivityRecordState,
    ActivitySessionState,
    RecordingOrigin,
    Sport,
    StreamResolution,
)
from backend.db.activity_detail_store import replace_detail_set
from backend.db.canonical_store import active_provider_record_hash, activity_record_link
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.garmin_fit_history import FitTransportMissing
from backend.providers.garmin_personal import PERSONAL_KEY_REJECTED_REASON
from backend.providers.garmin_rating_history import (
    FAILED,
    KEY_REJECTED,
    RATE_LIMITED,
    RatingReadStopped,
)
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.jobs import STREAM_HISTORY_CURSOR

FAILURE_LIMIT: Final = 3
STATE_KEY_PREFIX: Final = "stream_backfill_state"
BLOCKED_PERSONAL_API: Final = "personal_api_required"

STORED: Final = "stored"
NO_STREAMS: Final = "no_streams"
GONE: Final = "gone"

type Guard = Callable[[], AbstractContextManager[Any]]
type FileHandler = Callable[[str, bytes | None], None]
type SkipHandler = Callable[[str], None]


class StreamSource(Protocol):
    """Downloads the files of one batch and hands each on as it arrives."""

    def fetch(
        self,
        batch: Sequence[StreamCandidate],
        on_file: FileHandler,
        on_skip: SkipHandler,
        guard: Guard,
    ) -> None: ...


class StreamMapping(Protocol):
    """Maps one downloaded file to detail sets under the provider's provenance."""

    mapper_version: int

    def map(
        self, candidate: StreamCandidate, data: bytes, retrieved_at: datetime
    ) -> MappingResult[Any]: ...


@dataclass(frozen=True)
class StreamCandidate:
    provider_activity_id: str
    day: str
    started_at: str
    recorded_by: str


@dataclass(frozen=True)
class StreamSelection:
    """Candidates newest first, plus the counts of the records not read."""

    candidates: tuple[StreamCandidate, ...]
    with_streams: int

    def batch(self, end: date | None, limit: int) -> tuple[list[StreamCandidate], bool]:
        """Return the next batch up to day ``end`` and whether older ones remain."""
        newest = "9999-12-31" if end is None else end.isoformat()
        eligible = [item for item in self.candidates if item.day <= newest]
        if len(eligible) <= limit:
            return eligible, False
        last_day = eligible[limit - 1].day
        size = limit
        while size < len(eligible) and eligible[size].day == last_day:
            size += 1
        return eligible[:size], size < len(eligible)


def select_stream_candidates(
    db: Any,
    provider: str,
    *,
    excluded: frozenset[str] = frozenset(),
    earliest: date | None = None,
) -> StreamSelection:
    """Classify the provider's records of live sessions that could carry streams.

    ``excluded`` holds provider activity ids that are not read again; records
    before ``earliest`` are no candidates. Manual and strength records are never
    eligible.
    """
    rows = db.execute(
        "SELECT r.provider_activity_id, r.started_at, r.local_date, r.recorded_by, "
        "EXISTS (SELECT 1 FROM activity_detail_sets AS d "
        "WHERE d.provider = r.provider "
        "AND d.provider_activity_id = r.provider_activity_id "
        "AND d.detail_kind = ? AND d.resolution = ?) AS has_streams "
        "FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id AND s.state <> ? "
        "WHERE r.provider = ? AND r.state = ? AND r.recorded_by <> ? AND r.sport <> ?",
        (
            ActivityDetailKind.STREAMS.value,
            StreamResolution.FULL.value,
            ActivitySessionState.DELETED.value,
            provider,
            ActivityRecordState.ACTIVE.value,
            RecordingOrigin.MANUAL.value,
            Sport.STRENGTH.value,
        ),
    ).fetchall()
    floor = "" if earliest is None else earliest.isoformat()
    found: dict[str, StreamCandidate] = {}
    with_streams = 0
    for row in rows:
        identifier = str(row["provider_activity_id"])
        started = str(row["started_at"])
        day = str(row["local_date"] or iso_date_prefix(started))
        if day < floor:
            continue
        if row["has_streams"]:
            with_streams += 1
        elif identifier not in excluded:
            found[identifier] = StreamCandidate(
                identifier, day, started, str(row["recorded_by"])
            )
    ordered = sorted(
        found.values(),
        key=lambda item: (item.day, item.provider_activity_id),
        reverse=True,
    )
    return StreamSelection(tuple(ordered), with_streams)


@dataclass
class _Outcome:
    """What one batch did, by provider activity id."""

    stored: list[str]
    no_file: list[str]
    no_streams: list[str]
    skipped: list[str]
    gone: int = 0


class StreamBackfillService:
    """Download and store the FIT streams of one provider's batch of sessions."""

    def __init__(
        self,
        *,
        provider: str,
        source: StreamSource,
        mapping: StreamMapping,
        database_manager: Callable[[], Any],
        key_values: KeyValueRepository,
        guard: Guard,
        utc_now: Callable[[], str],
        configured: Callable[[], bool],
        earliest_date: date,
        batch_limit: int,
    ) -> None:
        self._provider = provider
        self._source = source
        self._mapping = mapping
        self._database_manager = database_manager
        self._key_values = key_values
        self._guard = guard
        self._utc_now = utc_now
        self._configured = configured
        self._earliest_date = earliest_date
        self._batch_limit = batch_limit

    def available(self) -> bool:
        """Return whether a real provider read is configured (never in fixture mode)."""
        return self._configured()

    def backfill(self, end: date | None) -> dict[str, Any]:
        """Read one batch ending on day ``end`` (None: newest); return the job result.

        A rate limit, a rejected key or another provider error fails the job, so the
        worker retries it later or stops; the cursor stays and the files stored before
        the failure remain. Without a Personal API key Garmin cannot serve files: the
        job ends without a change and the state says so.
        """
        if not self._configured():
            raise AppError(
                503, "Der Anbieter ist nicht konfiguriert.", reason="not_configured"
            )
        with self._database_manager().reader() as db:
            state = _read_state(self._key_values, db, self._provider)
            if end is None:
                # A fresh chain lets records that failed before try again.
                state["skipped_ids"] = []
                state["failures"] = {}
            selection = select_stream_candidates(
                db,
                self._provider,
                excluded=_excluded(state),
                earliest=self._earliest_date,
            )
        batch, more = selection.batch(end, self._batch_limit)
        by_id = {item.provider_activity_id: item for item in batch}
        outcome = _Outcome([], [], [], [])
        failure: Exception | None = None
        blocked: str | None = None
        if batch:
            try:
                self._source.fetch(
                    batch,
                    lambda identifier, data: self._handle_file(
                        identifier, data, by_id[identifier], outcome
                    ),
                    outcome.skipped.append,
                    self._guard,
                )
            except FitTransportMissing:
                blocked = BLOCKED_PERSONAL_API
            except Exception as exc:  # noqa: BLE001 - stored first, then re-raised.
                failure = exc
        fetched_at = self._utc_now()
        oldest = batch[-1].day if batch else None
        failed = (
            failure.activity_id
            if isinstance(failure, RatingReadStopped) and failure.kind == FAILED
            else None
        )
        self._write(
            state,
            outcome,
            failed=failed,
            blocked=blocked,
            fetched_at=fetched_at,
            advance=failure is None and blocked is None,
            oldest=oldest,
            more=more,
        )
        if isinstance(failure, RatingReadStopped):
            raise stop_error(failure)
        if failure is not None:
            raise failure
        result: dict[str, Any] = {
            "status": "ok",
            "synced_at": fetched_at,
            "candidates": len(batch),
            "window_records": len(outcome.stored),
            "historical_next_end": _next_end(oldest) if more and not blocked else None,
            "stored": len(outcome.stored),
            "no_file": len(outcome.no_file),
            "no_streams": len(outcome.no_streams),
            "skipped": len(outcome.skipped),
        }
        if blocked is not None:
            result["reason"] = blocked
        return result

    def _handle_file(
        self,
        identifier: str,
        data: bytes | None,
        candidate: StreamCandidate,
        outcome: _Outcome,
    ) -> None:
        """Store one downloaded file at once, so a later failure loses nothing."""
        if data is None:
            outcome.no_file.append(identifier)
            return
        result = self._store(candidate, data)
        if result == STORED:
            outcome.stored.append(identifier)
        elif result == NO_STREAMS:
            outcome.no_streams.append(identifier)
        else:
            outcome.gone += 1

    def _store(self, candidate: StreamCandidate, data: bytes) -> str:
        """Map and store one file; the record must still be active at write time."""
        retrieved_at = datetime.fromisoformat(self._utc_now())
        mapped = self._mapping.map(candidate, data, retrieved_at)
        records = [
            item
            for item in mapped.records
            if not isinstance(item, ActivityStrengthSetSet)
        ]
        # A file without sensor records replaces nothing and is not read again.
        if not any(
            isinstance(item, ActivityStreamSet)
            and item.resolution is StreamResolution.FULL
            for item in records
        ):
            return NO_STREAMS
        identifier = candidate.provider_activity_id
        with self._guard(), self._database_manager().unit_of_work() as db:
            link = activity_record_link(db, self._provider, identifier)
            if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
                return GONE
            summary_sha256 = active_provider_record_hash(
                db, self._provider, ACTIVITY_RECORD_KIND, identifier
            )
            for item in records:
                replace_detail_set(
                    db,
                    item,
                    mapper_version=self._mapping.mapper_version,
                    summary_sha256=summary_sha256,
                    now=retrieved_at.isoformat(),
                )
        return STORED

    def _write(
        self,
        state: dict[str, Any],
        outcome: _Outcome,
        *,
        failed: str | None,
        blocked: str | None,
        fetched_at: str,
        advance: bool,
        oldest: str | None,
        more: bool,
    ) -> None:
        with self._guard(), self._database_manager().unit_of_work() as db:
            _record_outcome(state, outcome, failed)
            state.update(
                stored=state["stored"] + len(outcome.stored),
                blocked=blocked,
                updated_at=fetched_at,
            )
            self._key_values.set(
                db, state_key(self._provider), json.dumps(state, sort_keys=True)
            )
            if advance:
                # The floor marks a finished chain, so a restart does not resume it;
                # a parked chain keeps the day it reached. Never below the floor.
                floor = self._earliest_date.isoformat()
                cursor = oldest if more and oldest is not None else floor
                write_cursor(
                    db,
                    self._provider,
                    STREAM_HISTORY_CURSOR,
                    max(cursor, floor),
                    fetched_at,
                    fetched_at,
                )


def state_key(provider: str) -> str:
    return f"{STATE_KEY_PREFIX}:{provider}"


def stop_error(failure: RatingReadStopped) -> AppError:
    """The job error of a stopped read."""
    if failure.kind == RATE_LIMITED:
        return AppError(
            429, "Der Anbieter begrenzt die Anfragen.", reason="rate_limited"
        )
    if failure.kind == KEY_REJECTED:
        return AppError(
            401,
            "Der Garmin-Personal-API-Schlüssel wurde abgelehnt.",
            reason=PERSONAL_KEY_REJECTED_REASON,
        )
    # A 401 on a data read or a transient failure: the key flag stays untouched.
    return AppError(
        503,
        "Der Anbieter ist vorübergehend nicht erreichbar.",
        reason="provider_unavailable",
    )


def _record_outcome(
    state: dict[str, Any], outcome: _Outcome, failed: str | None
) -> None:
    """Fold one batch into the state: ids kept out of later selections, failure counts."""
    failures: dict[str, int] = state["failures"]
    for identifier in (
        *outcome.stored,
        *outcome.no_file,
        *outcome.no_streams,
        *outcome.skipped,
    ):
        failures.pop(identifier, None)
    state["no_file_ids"] = sorted({*state["no_file_ids"], *outcome.no_file})
    state["no_stream_ids"] = sorted({*state["no_stream_ids"], *outcome.no_streams})
    state["skipped_ids"] = sorted({*state["skipped_ids"], *outcome.skipped})
    if failed is not None:
        failures[failed] = failures.get(failed, 0) + 1
        if failures[failed] >= FAILURE_LIMIT:
            del failures[failed]
            state["skipped_ids"] = sorted({*state["skipped_ids"], failed})


def _excluded(state: Mapping[str, Any]) -> frozenset[str]:
    return (
        frozenset(state["no_file_ids"])
        | frozenset(state["no_stream_ids"])
        | frozenset(state["skipped_ids"])
    )


def _next_end(oldest: str | None) -> str | None:
    if oldest is None:
        return None
    return (date.fromisoformat(oldest) - timedelta(days=1)).isoformat()


def _read_state(
    key_values: KeyValueRepository, db: Any, provider: str
) -> dict[str, Any]:
    raw = key_values.get(db, state_key(provider))
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    failures = stored.get("failures")
    return {
        "stored": int(stored.get("stored") or 0),
        "no_file_ids": [str(item) for item in stored.get("no_file_ids") or []],
        "no_stream_ids": [str(item) for item in stored.get("no_stream_ids") or []],
        "skipped_ids": [str(item) for item in stored.get("skipped_ids") or []],
        "failures": {str(key): int(count) for key, count in failures.items()}
        if isinstance(failures, dict)
        else {},
        "blocked": stored.get("blocked") or None,
        "updated_at": stored.get("updated_at"),
    }


def stream_backfill_counts(
    db: Any,
    key_values: KeyValueRepository,
    provider: str,
    earliest: date | None = None,
) -> dict[str, Any]:
    """Content-free counts of one provider's stream backfill, for diagnostics.

    ``candidates`` are the records still to read, ``with_streams`` those that hold
    full-resolution streams, ``stored`` the files stored by the job so far, and
    ``no_file`` / ``no_streams`` / ``skipped_by_error`` the records kept out of later
    runs. Records before ``earliest`` (the history floor) are no candidates.
    """
    state = _read_state(key_values, db, provider)
    selection = select_stream_candidates(
        db, provider, excluded=_excluded(state), earliest=earliest
    )
    cursor = read_cursor(db, provider, STREAM_HISTORY_CURSOR).get("cursor")
    floor = None if earliest is None else earliest.isoformat()
    if state["blocked"]:
        phase = "blocked"
    elif cursor and (floor is None or str(cursor) <= floor):
        phase = "finished"
    else:
        phase = "in_progress" if cursor else "not_started"
    return {
        "candidates": len(selection.candidates),
        "with_streams": selection.with_streams,
        "stored": state["stored"],
        "no_file": len(state["no_file_ids"]),
        "no_streams": len(state["no_stream_ids"]),
        "skipped_by_error": len(state["skipped_ids"]),
        "blocked": state["blocked"],
        "cursor": phase,
        "finished": phase == "finished",
    }
