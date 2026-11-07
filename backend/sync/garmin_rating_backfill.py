"""Backfill the watch ratings that only Intervals.icu copies still hold (#1728).

RPE and feel are entered on the watch; the Intervals.icu activity records only
relay Garmin's ``directWorkoutRpe`` and ``directWorkoutFeel``. Before the
Intervals.icu ingest data is deleted, the ``rating_backfill`` chain stores these
ratings as Garmin ratings (the ``activity_ratings`` section the regular sync
writes, mapped on the Garmin scales).

Selection: every live canonical session with an active Intervals.icu record that
has an RPE or feel, and an active Garmin record in the same session, whose Garmin
record holds no rating and has no stored rating row. A session without a Garmin
copy is only counted, never guessed. Sessions before the history floor are never
read.

The chain walks the sessions newest first, at most ``BATCH_LIMIT`` activities per
job (the whole last day of a batch is included, so a day is never split). The
``rating_history`` cursor moves to the oldest day of a complete batch; a rate
limit leaves it where it is and the rows already read stay stored. A second run
finds nothing to read: a rated or already read Garmin record is not selected.

An activity whose read is skipped (a client error) or fails three runs in a row is
kept in the state (its id, never in diagnostics) and not selected again; an
activity without a stored raw Garmin row is kept out the same way and counted
separately. The chain is only finished for good once the Garmin and Intervals.icu
historical chains reached the floor; before that it parks and the startup
scheduler queues it again. The Garmin lock is held per read and per write only.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Protocol

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.garmin_payload import (
    ACTIVITIES_SECTION,
    ACTIVITY_RATINGS_SECTION,
)
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store, garmin_store
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin_personal import PERSONAL_KEY_REJECTED_REASON
from backend.providers.garmin_rating_history import (
    FAILED,
    KEY_REJECTED,
    RATE_LIMITED,
    RatingReadStopped,
)
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.jobs import BACKFILL_CURSOR_STREAMS, RATING_HISTORY_CURSOR

BATCH_LIMIT: Final = 30
FAILURE_LIMIT: Final = 3
# A read or write waits this long for a running Garmin sync before it fails.
LOCK_WAIT_SECONDS: Final = 120.0
STATE_KEY: Final = "garmin_rating_backfill_state"
ALLOWED_SOURCES: Final = frozenset({ACTIVITY_RATINGS_SECTION, ACTIVITIES_SECTION})
_SESSION_CHUNK: Final = 500
_HISTORY_STREAM: Final = BACKFILL_CURSOR_STREAMS["historical_backfill"]
_HISTORY_CHAINS: Final = ((GARMIN_ID, _HISTORY_STREAM),)
_RATED_SQL: Final = (
    "(json_extract(details, '$.rpe') IS NOT NULL "
    "OR json_extract(details, '$.feel') IS NOT NULL)"
)

type RatingSink = Callable[[dict[str, Any]], None]
type SkipSink = Callable[[str], None]
type Guard = Callable[[], AbstractContextManager[Any]]


class RatingReader(Protocol):
    def fetch_activity_ratings(
        self,
        activities: list[tuple[str, str]],
        on_row: RatingSink,
        on_skip: SkipSink,
        guard: Guard,
    ) -> None: ...


class SyncCoordination(Protocol):
    def operation(self) -> AbstractContextManager[Any]: ...

    def acquire(self, *, timeout: float | None = None) -> bool: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class RatingCandidate:
    session_id: str
    day: str
    started_at: str
    garmin_activity_id: str


@dataclass(frozen=True)
class RatingSelection:
    """Candidates newest first, plus the counts of the sessions not read."""

    candidates: tuple[RatingCandidate, ...]
    already_rated: int
    no_garmin_copy: int

    def batch(self, end: date | None) -> tuple[list[RatingCandidate], bool]:
        """Return the next batch up to day ``end`` and whether older ones remain."""
        limit = "9999-12-31" if end is None else end.isoformat()
        eligible = [item for item in self.candidates if item.day <= limit]
        if len(eligible) <= BATCH_LIMIT:
            return eligible, False
        last_day = eligible[BATCH_LIMIT - 1].day
        size = BATCH_LIMIT
        while size < len(eligible) and eligible[size].day == last_day:
            size += 1
        return eligible[:size], size < len(eligible)


def select_rating_candidates(
    db: Any,
    *,
    excluded: frozenset[str] = frozenset(),
    earliest: date | None = None,
) -> RatingSelection:
    """Classify the live sessions that carry an Intervals.icu rating.

    ``excluded`` holds Garmin activity ids that are not read again; sessions
    before ``earliest`` are not candidates.
    """
    intervals = _session_rows(db, ProviderId.INTERVALS.value, rated_only=True)
    garmin = _session_rows(db, ProviderId.GARMIN.value, rated_only=False)
    sessions = _live_sessions(db, [*intervals, *garmin])
    rated_sessions, unrated = _garmin_sessions(
        garmin, sessions, garmin_store.stored_keys(db, ACTIVITY_RATINGS_SECTION)
    )
    floor = "" if earliest is None else earliest.isoformat()
    already_rated = no_copy = 0
    found: dict[str, RatingCandidate] = {}
    seen: set[str] = set()
    for row in intervals:
        session = sessions.get(str(row["activity_id"]))
        if session is None or session in seen:
            continue
        seen.add(session)
        if session in rated_sessions:
            already_rated += 1
        elif session in unrated:
            identifier, started = unrated[session]
            day = _day(row, started)
            if identifier not in excluded and day >= floor:
                found[session] = RatingCandidate(session, day, started, identifier)
        else:
            no_copy += 1
    ordered = sorted(
        found.values(), key=lambda item: (item.day, item.session_id), reverse=True
    )
    return RatingSelection(tuple(ordered), already_rated, no_copy)


def _garmin_sessions(
    garmin: Iterable[Any],
    sessions: Mapping[str, str],
    read_ids: set[str],
) -> tuple[set[str], dict[str, tuple[str, str]]]:
    """Split the live sessions with a Garmin record into rated and unrated ones.

    An unrated session keeps its first Garmin record's id and start.
    """
    rated: set[str] = set()
    unrated: dict[str, tuple[str, str]] = {}
    for row in garmin:
        session = sessions.get(str(row["activity_id"]))
        if session is None:
            continue
        identifier = str(row["provider_activity_id"])
        if row["rated"] or identifier in read_ids:
            rated.add(session)
        else:
            unrated.setdefault(session, (identifier, str(row["started_at"])))
    return rated, unrated


def _day(row: Mapping[str, Any], started: str) -> str:
    return str(row["local_date"] or iso_date_prefix(started))


def _session_rows(db: Any, provider: str, *, rated_only: bool) -> list[Any]:
    rated = f"CASE WHEN {_RATED_SQL} THEN 1 ELSE 0 END AS rated"
    where = f"AND {_RATED_SQL}" if rated_only else ""
    return db.execute(
        "SELECT activity_id, provider_activity_id, local_date, started_at, "
        f"{rated} FROM activity_records WHERE provider = ? AND state = 'active' "
        f"AND activity_id IS NOT NULL {where} "
        "ORDER BY provider_activity_id",
        (provider,),
    ).fetchall()


def _live_sessions(db: Any, rows: Iterable[Any]) -> dict[str, str]:
    """Map each record's session id to the live session it leads to."""
    references = list(dict.fromkeys(str(row["activity_id"]) for row in rows))
    effective = canonical_store.effective_session_ids(db, references)
    targets = sorted(set(effective.values()))
    live: set[str] = set()
    for start in range(0, len(targets), _SESSION_CHUNK):
        chunk = targets[start : start + _SESSION_CHUNK]
        marks = ", ".join("?" for _ in chunk)
        live.update(
            str(row["activity_id"])
            for row in db.execute(
                "SELECT activity_id FROM activity_sessions WHERE state = 'active' "
                f"AND activity_id IN ({marks})",
                tuple(chunk),
            )
        )
    return {
        reference: target for reference, target in effective.items() if target in live
    }


class GarminRatingBackfillService:
    """Read and store the ratings of one batch of sessions."""

    def __init__(
        self,
        *,
        reader: RatingReader,
        database_manager: Any,
        snapshot_writer: GarminSnapshotWriter,
        key_values: KeyValueRepository,
        coordination: SyncCoordination,
        utc_now: Callable[[], str],
        configured: Callable[[], bool],
        earliest_date: date,
    ) -> None:
        self._reader = reader
        self._database_manager = database_manager
        self._snapshot_writer = snapshot_writer
        self._key_values = key_values
        self._coordination = coordination
        self._utc_now = utc_now
        self._configured = configured
        self._earliest_date = earliest_date

    def available(self) -> bool:
        """Return whether a real Garmin read is configured (never in fixture mode)."""
        return self._configured()

    @contextmanager
    def _guard(self) -> Iterator[None]:
        """Hold the Garmin coordination lock for one read or one write only."""
        with self._coordination.operation():
            if not self._coordination.acquire(timeout=LOCK_WAIT_SECONDS):
                raise AppError(
                    503, "Garmin wird bereits aktualisiert.", reason="provider_busy"
                )
            try:
                yield
            finally:
                self._coordination.release()

    def backfill(self, end: date | None) -> dict[str, Any]:
        """Read one batch ending on day ``end`` (None: newest); return the job result.

        A rate limit, a rejected key or another provider error fails the job, so the
        worker retries it later or stops; the cursor stays and the rows read before
        the failure are stored.
        """
        if not self._configured():
            raise AppError(
                503, "Garmin ist nicht konfiguriert.", reason="not_configured"
            )
        with self._database_manager.reader() as db:
            state = _read_state(self._key_values, db)
            selection = select_rating_candidates(
                db, excluded=_excluded(state), earliest=self._earliest_date
            )
        batch, more = selection.batch(end)
        rows: list[dict[str, Any]] = []
        skipped: list[str] = []
        failure: Exception | None = None
        if batch:
            try:
                self._reader.fetch_activity_ratings(
                    [(item.garmin_activity_id, item.started_at) for item in batch],
                    rows.append,
                    skipped.append,
                    self._guard,
                )
            except Exception as exc:  # noqa: BLE001 - stored first, then re-raised.
                failure = exc
        fetched_at = self._utc_now()
        oldest = batch[-1].day if batch else None
        failed = (
            failure.activity_id
            if isinstance(failure, RatingReadStopped) and failure.kind == FAILED
            else None
        )
        counts = self._write(
            rows,
            skipped,
            failed=failed,
            fetched_at=fetched_at,
            advance=failure is None,
            oldest=oldest,
            more=more,
        )
        if isinstance(failure, RatingReadStopped):
            raise _stop_error(failure)
        if failure is not None:
            raise failure
        return {
            "status": "ok",
            "synced_at": fetched_at,
            "candidates": len(batch),
            "window_records": len(rows),
            "historical_next_end": _next_end(oldest) if more else None,
            "skipped": len(skipped),
            **counts,
        }

    def _write(
        self,
        rows: list[dict[str, Any]],
        skipped: list[str],
        *,
        failed: str | None,
        fetched_at: str,
        advance: bool,
        oldest: str | None,
        more: bool,
    ) -> dict[str, int]:
        with self._guard(), self._database_manager.unit_of_work() as db:
            stored: list[dict[str, Any]] = []
            raws: list[dict[str, Any]] = []
            missing: list[str] = []
            for row in rows:
                raw = garmin_store.read_activity(db, str(row["activityId"]))
                if raw is None:
                    missing.append(str(row["activityId"]))
                else:
                    stored.append(row)
                    raws.append(raw)
            if stored:
                # The stored activity rows are mapped again, so the rating reaches
                # the canonical records.
                self._snapshot_writer.write_refresh(
                    db,
                    fetched_at=fetched_at,
                    sections={
                        ACTIVITY_RATINGS_SECTION: stored,
                        ACTIVITIES_SECTION: raws,
                    },
                    view={},
                    windows={},
                    allowed=ALLOWED_SOURCES,
                )
            backfilled = sum(
                1
                for row in stored
                if row.get("directWorkoutRpe") is not None
                or row.get("directWorkoutFeel") is not None
            )
            state = _read_state(self._key_values, db)
            _record_outcome(state, stored, skipped, missing, failed)
            finished = bool(state["finished"]) or (
                advance and not more and self._history_complete(db)
            )
            state.update(
                backfilled=state["backfilled"] + backfilled,
                no_rating=state["no_rating"] + len(stored) - backfilled,
                finished=finished,
                updated_at=fetched_at,
            )
            self._key_values.set(db, STATE_KEY, json.dumps(state, sort_keys=True))
            if advance:
                # The floor marks a finished chain, so a restart does not resume it;
                # a parked chain keeps the day it reached. Never below the floor.
                floor = self._earliest_date.isoformat()
                cursor = floor if finished else oldest
                if cursor is not None:
                    write_cursor(
                        db,
                        GARMIN_ID,
                        RATING_HISTORY_CURSOR,
                        max(cursor, floor),
                        fetched_at,
                        fetched_at,
                    )
        return {
            "backfilled": backfilled,
            "no_rating": len(stored) - backfilled,
            "no_raw_row": len(missing),
        }

    def _history_complete(self, db: Any) -> bool:
        """Return whether the activity chains that can still add sessions hit the floor.

        Intervals.icu is not read any more, so no Intervals.icu session arrives
        and its history cursor never moves; only Garmin counts.
        """
        floor = self._earliest_date.isoformat()
        for provider, stream in _HISTORY_CHAINS:
            cursor = read_cursor(db, provider, stream).get("cursor")
            if not cursor or str(cursor) > floor:
                return False
        return True


def _excluded(state: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(state["skipped_ids"]) | frozenset(state["no_raw_ids"])


def _record_outcome(
    state: dict[str, Any],
    stored: list[dict[str, Any]],
    skipped: list[str],
    missing: list[str],
    failed: str | None,
) -> None:
    """Fold one run into the state: ids kept out of later selections, failure counts."""
    failures: dict[str, int] = state["failures"]
    for identifier in [str(row["activityId"]) for row in stored] + skipped + missing:
        failures.pop(identifier, None)
    state["skipped_ids"] = sorted({*state["skipped_ids"], *skipped})
    state["no_raw_ids"] = sorted({*state["no_raw_ids"], *missing})
    if failed is not None:
        failures[failed] = failures.get(failed, 0) + 1
        if failures[failed] >= FAILURE_LIMIT:
            del failures[failed]
            state["skipped_ids"] = sorted({*state["skipped_ids"], failed})


def _stop_error(failure: RatingReadStopped) -> AppError:
    """The job error of a stopped read."""
    if failure.kind == RATE_LIMITED:
        return AppError(429, "Garmin begrenzt die Anfragen.", reason="rate_limited")
    if failure.kind == KEY_REJECTED:
        return AppError(
            401,
            "Der Garmin-Personal-API-Schlüssel wurde abgelehnt.",
            reason=PERSONAL_KEY_REJECTED_REASON,
        )
    # A 401 on a data read or a transient failure: the key flag stays untouched.
    return AppError(
        503, "Garmin ist vorübergehend nicht erreichbar.", reason="provider_unavailable"
    )


def _next_end(oldest: str | None) -> str | None:
    if oldest is None:
        return None
    return (date.fromisoformat(oldest) - timedelta(days=1)).isoformat()


def _read_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    failures = stored.get("failures")
    return {
        "backfilled": int(stored.get("backfilled") or 0),
        "no_rating": int(stored.get("no_rating") or 0),
        "skipped_ids": [str(item) for item in stored.get("skipped_ids") or []],
        "no_raw_ids": [str(item) for item in stored.get("no_raw_ids") or []],
        "failures": {str(key): int(count) for key, count in failures.items()}
        if isinstance(failures, dict)
        else {},
        "finished": bool(stored.get("finished")),
        "updated_at": stored.get("updated_at"),
    }


def rating_backfill_finished(key_values: KeyValueRepository, db: Any) -> bool:
    """Whether the stored backfill state says the chain finished for good."""
    return bool(_read_state(key_values, db)["finished"])


def rating_backfill_counts(
    db: Any, key_values: KeyValueRepository, earliest: date | None = None
) -> dict[str, Any]:
    """Content-free counts of the rating backfill, for diagnostics and the later
    Intervals.icu data migration's dry run.

    ``candidates`` are the sessions still to read, ``already_rated`` those whose
    Garmin record holds a rating or whose rating was read, ``no_garmin_copy``
    the sessions with an Intervals.icu rating and no Garmin record. Sessions
    before ``earliest`` (the history floor) are no candidates, as for the job.
    """
    state = _read_state(key_values, db)
    selection = select_rating_candidates(
        db, excluded=_excluded(state), earliest=earliest
    )
    cursor = read_cursor(db, GARMIN_ID, RATING_HISTORY_CURSOR).get("cursor")
    if state["finished"]:
        phase = "finished"
    else:
        phase = "in_progress" if cursor else "not_started"
    return {
        "candidates": len(selection.candidates),
        "backfilled": state["backfilled"],
        "no_rating_at_garmin": state["no_rating"],
        "already_rated": selection.already_rated,
        "skipped_by_error": len(state["skipped_ids"]),
        "no_raw_row": len(state["no_raw_ids"]),
        "no_garmin_copy": selection.no_garmin_copy,
        "cursor": phase,
        "finished": phase == "finished",
    }
