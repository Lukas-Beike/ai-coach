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

A provider can also replay a mapper upgrade (#1936): a record whose full stream set
was stored by an older mapper version and that lies inside the replay window is
downloaded again once. Wahoo keeps no FIT bytes, so this is the only way an
upgrade reaches sessions older than the regular detail import's window. The old
streams stay until the replacement is stored, so a failed or empty download changes
nothing. ``rearm`` moves a finished chain's cursor back when the mapper is newer
than the one the chain last ran for.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
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
from backend.providers.fit_activity_detail_mapping import fit_inventory
from backend.providers.garmin_fit_history import FitTransportMissing
from backend.providers.garmin_personal import PERSONAL_KEY_REJECTED_REASON
from backend.providers.garmin_rating_history import (
    FAILED,
    KEY_REJECTED,
    RATE_LIMITED,
    RatingReadStopped,
)
from backend.sync.cursors import clear_cursor, read_cursor, write_cursor
from backend.sync.jobs import STREAM_HISTORY_CURSOR

FAILURE_LIMIT: Final = 3
STATE_KEY_PREFIX: Final = "stream_backfill_state"
BLOCKED_PERSONAL_API: Final = "personal_api_required"

# Count-only inventory of FIT content (#2220); ``seen`` keeps file hashes so a
# file read again (regular fetch, then replay) is counted once.
FIT_INVENTORY_KEY: Final = "fit_inventory"
_MAX_SEEN_FILES: Final = 5000

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
class StreamReplay:
    """Records whose streams an older mapper version stored are read again.

    Only sessions from ``since`` on qualify; older ones keep their streams.
    """

    mapper_version: int
    since: date


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
    replay: StreamReplay | None = None,
) -> StreamSelection:
    """Classify the provider's records of live sessions that could carry streams.

    ``excluded`` holds provider activity ids that are not read again; records
    before ``earliest`` are no candidates. Manual and strength records are never
    eligible. With ``replay``, a record whose full streams all come from an older
    mapper version is a candidate too, when its day is not before ``replay.since``.
    """
    rows = db.execute(
        "SELECT r.provider_activity_id, r.started_at, r.local_date, r.recorded_by, "
        "EXISTS (SELECT 1 FROM activity_detail_sets AS d "
        "WHERE d.provider = r.provider "
        "AND d.provider_activity_id = r.provider_activity_id "
        "AND d.detail_kind = ? AND d.resolution = ?) AS has_streams, "
        "EXISTS (SELECT 1 FROM activity_detail_sets AS d "
        "WHERE d.provider = r.provider "
        "AND d.provider_activity_id = r.provider_activity_id "
        "AND d.detail_kind = ? AND d.resolution = ? "
        "AND d.mapper_version >= ?) AS has_current_streams "
        "FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id AND s.state <> ? "
        "WHERE r.provider = ? AND r.state = ? AND r.recorded_by <> ? AND r.sport <> ?",
        (
            ActivityDetailKind.STREAMS.value,
            StreamResolution.FULL.value,
            ActivityDetailKind.STREAMS.value,
            StreamResolution.FULL.value,
            0 if replay is None else replay.mapper_version,
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
            wanted = (
                replay is not None
                and not row["has_current_streams"]
                and day >= replay.since.isoformat()
            )
        else:
            wanted = True
        if wanted and identifier not in excluded:
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
        operation: Callable[[], AbstractContextManager[Any]] = nullcontext,
        replay_days: int | None = None,
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
        self._operation = operation
        self._replay_days = replay_days

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
        # A running full resync rejects the work before any state changes.
        with self._operation():
            return self._backfill(end)

    def rearm(self) -> None:
        """Start a finished chain again once per mapper version (#1936).

        A mapper upgrade only reaches stored streams through the replay, and a chain
        at its floor queues no job. The cursor is forgotten and the failed records
        may retry, once for each mapper version the replay has not covered yet;
        without a replay window nothing changes.
        """
        if self._replay_days is None or not self._configured():
            return
        version = self._mapping.mapper_version
        with self._guard(), self._database_manager().unit_of_work() as db:
            state = _read_state(self._key_values, db, self._provider)
            if state["replay_mapper_version"] >= version:
                return
            cursor = read_cursor(db, self._provider, STREAM_HISTORY_CURSOR)
            if not _at_floor(cursor.get("cursor"), self._earliest_date):
                # A walking chain may carry an older end_date in its queued job;
                # it is rearmed by the first refresh after it reaches the floor.
                return
            state.update(
                replay_mapper_version=version,
                skipped_ids=[],
                failures={},
                updated_at=self._utc_now(),
            )
            self._key_values.set(
                db, state_key(self._provider), json.dumps(state, sort_keys=True)
            )
            clear_cursor(db, self._provider, STREAM_HISTORY_CURSOR)

    def _replay(self) -> StreamReplay | None:
        if self._replay_days is None:
            return None
        today = date.fromisoformat(iso_date_prefix(self._utc_now()))
        return StreamReplay(
            self._mapping.mapper_version, today - timedelta(days=self._replay_days)
        )

    def _backfill(self, end: date | None) -> dict[str, Any]:
        with self._database_manager().reader() as db:
            state = _read_state(self._key_values, db, self._provider)
            cursor = read_cursor(db, self._provider, STREAM_HISTORY_CURSOR)
            if end is None and _at_floor(cursor.get("cursor"), self._earliest_date):
                # A rerun of a finished chain lets records that failed before try
                # again; a retry of a first batch keeps its failure counts.
                state["skipped_ids"] = []
                state["failures"] = {}
            selection = select_stream_candidates(
                db,
                self._provider,
                excluded=_excluded(state),
                earliest=self._earliest_date,
                replay=self._replay(),
            )
        batch, more = selection.batch(end, self._batch_limit)
        outcome, failure, blocked = self._fetch_batch(batch)
        fetched_at = self._utc_now()
        oldest = batch[-1].day if batch else None
        failed = (
            failure.activity_id
            if isinstance(failure, RatingReadStopped) and failure.kind == FAILED
            else None
        )
        file_skipped = self._write(
            state,
            outcome,
            failed=failed,
            blocked=blocked,
            fetched_at=fetched_at,
            advance=failure is None and blocked is None,
            oldest=oldest,
            more=more,
        )
        next_end = _next_end(oldest) if more and not blocked else None
        if file_skipped:
            # The file just moved to the skipped ids is no longer a candidate: the
            # chain reads the same window again without it instead of failing.
            failure = None
            next_end = batch[0].day
        if isinstance(failure, RatingReadStopped):
            raise stop_error(failure)
        if failure is not None:
            raise failure
        result: dict[str, Any] = {
            "status": "ok",
            "synced_at": fetched_at,
            "candidates": len(batch),
            "window_records": len(outcome.stored),
            "historical_next_end": next_end,
            "stored": len(outcome.stored),
            "no_file": len(outcome.no_file),
            "no_streams": len(outcome.no_streams),
            "skipped": len(outcome.skipped),
        }
        if blocked is not None:
            result["reason"] = blocked
        return result

    def _fetch_batch(
        self, batch: Sequence[StreamCandidate]
    ) -> tuple[_Outcome, Exception | None, str | None]:
        """Download and store one batch; a stop is returned, never raised."""
        by_id = {item.provider_activity_id: item for item in batch}
        outcome = _Outcome([], [], [], [])
        if not batch:
            return outcome, None, None
        try:
            self._source.fetch(
                batch,
                lambda identifier, data: self._handle_file(
                    identifier, data, by_id[identifier], outcome
                ),
                outcome.skipped.append,
            )
        except FitTransportMissing:
            return outcome, None, BLOCKED_PERSONAL_API
        except Exception as exc:  # noqa: BLE001 - stored first, then re-raised.
            return outcome, exc, None
        return outcome, None, None

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
        with self._guard(), self._database_manager().unit_of_work() as db:
            count_fit_file(db, self._key_values, self._provider, identifier, data)
        try:
            result = self._store(candidate, data)
        except AppError:
            raise
        except Exception:  # noqa: BLE001 - counted like a failed download.
            # A file that cannot be mapped or stored must not block the chain
            # for ever: the third failing run skips it.
            raise RatingReadStopped(FAILED, identifier) from None
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
    ) -> bool:
        """Store the state and cursor; return whether ``failed`` was skipped for good."""
        with self._guard(), self._database_manager().unit_of_work() as db:
            file_skipped = _record_outcome(state, outcome, failed)
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
        return file_skipped


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
) -> bool:
    """Fold one batch into the state: ids kept out of later selections, failure counts.

    Returns whether ``failed`` reached the failure limit and was skipped for good.
    """
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
            return True
    return False


def _excluded(state: Mapping[str, Any]) -> frozenset[str]:
    return (
        frozenset(state["no_file_ids"])
        | frozenset(state["no_stream_ids"])
        | frozenset(state["skipped_ids"])
    )


def _at_floor(cursor: object, floor: date) -> bool:
    """Whether a stored cursor marks a finished chain."""
    return bool(cursor) and str(cursor) <= floor.isoformat()


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
        "replay_mapper_version": int(stored.get("replay_mapper_version") or 0),
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


def count_fit_file(
    db: Any,
    key_values: KeyValueRepository,
    provider: str,
    provider_activity_id: str,
    data: object,
) -> None:
    """Add one read FIT file to the inventory by recording origin and sport."""
    keys = fit_inventory(data)
    if keys is None or not isinstance(data, bytes):
        return
    digest = hashlib.sha256(data).hexdigest()[:32]
    state = _inventory_state(key_values, db)
    if digest in state["seen"]:
        return
    row = db.execute(
        "SELECT sport, recorded_by FROM activity_records "
        "WHERE provider = ? AND provider_activity_id = ? LIMIT 1",
        (provider, provider_activity_id),
    ).fetchone()
    origin = _vocabulary(row and row["recorded_by"], RecordingOrigin) or provider
    sport = _vocabulary(row and row["sport"], Sport) or "unknown"
    bucket = state["counts"].setdefault(origin, {}).setdefault(sport, {})
    for key in ("files", *sorted(keys)):
        bucket[key] = int(bucket.get(key) or 0) + 1
    state["seen"] = [*state["seen"], digest][-_MAX_SEEN_FILES:]
    key_values.set(db, FIT_INVENTORY_KEY, json.dumps(state, sort_keys=True))


def fit_inventory_counts(db: Any, key_values: KeyValueRepository) -> dict[str, Any]:
    """The inventory counts for diagnostics, without the file hashes.

    Per recording origin and sport: ``files`` read, and the files holding each
    message number, unread field of a mapped message and developer field.
    """
    groups = {"m": "messages", "f": "unmapped_fields", "d": "developer_fields"}
    result: dict[str, Any] = {}
    for origin, sports in _inventory_state(key_values, db)["counts"].items():
        for sport, bucket in sports.items():
            view: dict[str, Any] = {"files": bucket.get("files", 0)}
            view.update({name: {} for name in groups.values()})
            for key, count in bucket.items():
                if key != "files" and key[:1] in groups:
                    view[groups[key[:1]]][key[1:]] = count
            result.setdefault(origin, {})[sport] = view
    return result


def _inventory_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    try:
        stored = json.loads(key_values.get(db, FIT_INVENTORY_KEY) or "{}")
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    seen = stored.get("seen")
    counts = stored.get("counts")
    return {
        "seen": [str(item) for item in seen] if isinstance(seen, list) else [],
        "counts": counts if isinstance(counts, dict) else {},
    }


def _vocabulary(value: object, vocabulary: type[RecordingOrigin | Sport]) -> str:
    try:
        return vocabulary(str(value)).value if value else ""
    except ValueError:
        return ""
