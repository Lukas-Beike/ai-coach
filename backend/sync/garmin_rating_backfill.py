"""Backfill the watch ratings that only Intervals.icu copies still hold (#1728).

RPE and feel are entered on the watch; the Intervals.icu activity records only
relay Garmin's ``directWorkoutRpe`` and ``directWorkoutFeel``. Before the
Intervals.icu ingest data is deleted, the ``rating_backfill`` chain stores these
ratings as Garmin ratings (the ``activity_ratings`` section the regular sync
writes, mapped on the Garmin scales).

Selection: every live canonical session with an active Intervals.icu record that
has an RPE or feel, and an active Garmin record in the same session, whose Garmin
record holds no rating and has no stored rating row. A session without a Garmin
copy is only counted, never guessed.

The chain walks the sessions newest first, at most ``BATCH_LIMIT`` activities per
job (the whole last day of a batch is included, so a day is never split). The
``rating_history`` cursor moves to the oldest day of a complete batch; a rate
limit leaves it where it is and the rows already read stay stored. A second run
finds nothing to read: a rated or already read Garmin record is not selected.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
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
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.jobs import RATING_HISTORY_CURSOR

BATCH_LIMIT: Final = 30
# A backfill chunk waits this long for a running Garmin sync before it fails.
LOCK_WAIT_SECONDS: Final = 120.0
STATE_KEY: Final = "garmin_rating_backfill_state"
ALLOWED_SOURCES: Final = frozenset({ACTIVITY_RATINGS_SECTION, ACTIVITIES_SECTION})
_RATED_SQL: Final = (
    "(json_extract(details, '$.rpe') IS NOT NULL "
    "OR json_extract(details, '$.feel') IS NOT NULL)"
)

type RatingSink = Callable[[dict[str, Any]], None]


class RatingReader(Protocol):
    def fetch_activity_ratings(
        self, activities: list[tuple[str, str]], sink: RatingSink
    ) -> int: ...


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


def select_rating_candidates(db: Any) -> RatingSelection:
    """Classify the live sessions that carry an Intervals.icu rating."""
    intervals = _session_rows(db, ProviderId.INTERVALS.value, rated_only=True)
    garmin = _session_rows(db, ProviderId.GARMIN.value, rated_only=False)
    sessions = _live_sessions(db, [*intervals, *garmin])
    read_ids = {
        item.key for _, item in garmin_store.iter_items(db, (ACTIVITY_RATINGS_SECTION,))
    }
    rated_sessions: set[str] = set()
    unrated: dict[str, tuple[str, str]] = {}
    for row in garmin:
        session = sessions.get(str(row["activity_id"]))
        if session is None:
            continue
        identifier = str(row["provider_activity_id"])
        if row["rated"] or identifier in read_ids:
            rated_sessions.add(session)
        else:
            unrated.setdefault(session, (identifier, str(row["started_at"])))
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
            found[session] = RatingCandidate(
                session, _day(row, started), started, identifier
            )
        else:
            no_copy += 1
    ordered = sorted(
        found.values(), key=lambda item: (item.day, item.session_id), reverse=True
    )
    return RatingSelection(tuple(ordered), already_rated, no_copy)


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
    live = {
        str(row["activity_id"])
        for row in db.execute(
            "SELECT activity_id FROM activity_sessions WHERE state = 'active'"
        )
    }
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
        with self._coordination.operation():
            if not self._coordination.acquire(timeout=LOCK_WAIT_SECONDS):
                raise AppError(
                    503, "Garmin wird bereits aktualisiert.", reason="provider_busy"
                )
            try:
                return self._run(end)
            finally:
                self._coordination.release()

    def _run(self, end: date | None) -> dict[str, Any]:
        with self._database_manager.reader() as db:
            selection = select_rating_candidates(db)
        batch, more = selection.batch(end)
        rows: list[dict[str, Any]] = []
        skipped = 0
        failure: Exception | None = None
        if batch:
            try:
                skipped = self._reader.fetch_activity_ratings(
                    [(item.garmin_activity_id, item.started_at) for item in batch],
                    rows.append,
                )
            except Exception as exc:  # noqa: BLE001 - stored first, then re-raised.
                failure = exc
        fetched_at = self._utc_now()
        oldest = batch[-1].day if batch else None
        counts = self._write(
            rows,
            skipped=skipped,
            fetched_at=fetched_at,
            advance=failure is None,
            oldest=oldest,
            more=more,
        )
        if failure is not None:
            raise failure
        return {
            "status": "ok",
            "synced_at": fetched_at,
            "candidates": len(batch),
            "window_records": len(rows),
            "historical_next_end": _next_end(oldest) if more else None,
            "skipped": skipped,
            **counts,
        }

    def _write(
        self,
        rows: list[dict[str, Any]],
        *,
        skipped: int,
        fetched_at: str,
        advance: bool,
        oldest: str | None,
        more: bool,
    ) -> dict[str, int]:
        backfilled = sum(
            1
            for row in rows
            if row.get("directWorkoutRpe") is not None
            or row.get("directWorkoutFeel") is not None
        )
        with self._database_manager.unit_of_work() as db:
            if rows:
                sections: dict[str, Any] = {ACTIVITY_RATINGS_SECTION: rows}
                # The stored activity rows are mapped again, so the rating reaches
                # the canonical records.
                activities = [
                    raw
                    for row in rows
                    if (raw := garmin_store.read_activity(db, str(row["activityId"])))
                ]
                if activities:
                    sections[ACTIVITIES_SECTION] = activities
                self._snapshot_writer.write_refresh(
                    db,
                    fetched_at=fetched_at,
                    sections=sections,
                    view={},
                    windows={},
                    allowed=ALLOWED_SOURCES,
                )
            state = _read_state(self._key_values, db)
            finished = advance and not more
            state.update(
                backfilled=state["backfilled"] + backfilled,
                no_rating=state["no_rating"] + len(rows) - backfilled,
                skipped=state["skipped"] + skipped,
                finished=bool(state["finished"]) or finished,
                updated_at=fetched_at,
            )
            self._key_values.set(db, STATE_KEY, json.dumps(state, sort_keys=True))
            if advance and (finished or oldest is not None):
                # The floor marks a finished chain, so a restart does not resume it.
                cursor = self._earliest_date.isoformat() if finished else str(oldest)
                write_cursor(
                    db, GARMIN_ID, RATING_HISTORY_CURSOR, cursor, fetched_at, fetched_at
                )
        return {"backfilled": backfilled, "no_rating": len(rows) - backfilled}


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
    return {
        "backfilled": int(stored.get("backfilled") or 0),
        "no_rating": int(stored.get("no_rating") or 0),
        "skipped": int(stored.get("skipped") or 0),
        "finished": bool(stored.get("finished")),
        "updated_at": stored.get("updated_at"),
    }


def rating_backfill_counts(
    db: Any, key_values: KeyValueRepository, earliest_date: date
) -> dict[str, Any]:
    """Content-free counts of the rating backfill, for diagnostics and the later
    Intervals.icu data migration's dry run.

    ``candidates`` are the sessions still to read, ``already_rated`` those whose
    Garmin record holds a rating or whose rating was read, ``no_garmin_copy``
    the sessions with an Intervals.icu rating and no Garmin record.
    """
    selection = select_rating_candidates(db)
    state = _read_state(key_values, db)
    cursor = read_cursor(db, GARMIN_ID, RATING_HISTORY_CURSOR).get("cursor")
    if state["finished"] or (cursor and str(cursor) <= earliest_date.isoformat()):
        phase = "finished"
    else:
        phase = "in_progress" if cursor else "not_started"
    return {
        "candidates": len(selection.candidates),
        "backfilled": state["backfilled"],
        "no_rating_at_garmin": state["no_rating"],
        "already_rated": selection.already_rated,
        "skipped_by_error": state["skipped"],
        "no_garmin_copy": selection.no_garmin_copy,
        "cursor": phase,
        "finished": phase == "finished",
    }
