"""Stream backfill (#1763): FIT streams of past Garmin and Wahoo sessions.

Synthetic sessions in a temporary SQLite database, fake transport clients and
generated FIT bytes; no provider account, key, token or network is used.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlparse

from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.db.activity_detail_store import detail_sets_for, full_stream_keys
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.diagnostics.stream_backfill import summarize_stream_backfill
from backend.errors import AppError
from backend.providers import http as provider_http
from backend.providers.garmin_fit_history import (
    FitTransportMissing,
    collect_activity_fit_files,
)
from backend.providers.garmin_personal import (
    PERSONAL_KEY_REJECTED_REASON,
    TOKEN_PATH,
    GarminPersonalClient,
    GarminTransportClient,
)
from backend.providers.garmin_rating_history import RatingReadHooks
from backend.providers.wahoo_client import WahooWorkoutFetch
from backend.providers.wahoo_fit_download import WahooFitUnavailable
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.executor import WahooJobAdapter, run_stream_backfill
from backend.sync.garmin_service import GarminRemoteReader, _skippable_history_error
from backend.sync.garmin_stream_backfill import GarminStreamMapping, GarminStreamSource
from backend.sync.gates import ProviderResyncGate
from backend.sync.jobs import (
    STREAM_BACKFILL,
    STREAM_HISTORY_CURSOR,
    normalize_sync_job_request,
)
from backend.sync.refresh import sync_job_error_class
from backend.sync.stream_backfill import (
    BLOCKED_PERSONAL_API,
    FAILURE_LIMIT,
    StreamBackfillService,
    StreamCandidate,
    StreamSelection,
    select_stream_candidates,
    state_key,
    stream_backfill_counts,
)
from backend.sync.wahoo_stream_backfill import (
    HISTORY_WORKOUT_PAGES,
    WahooStreamMapping,
    WahooStreamSource,
)
from tests.test_fit_file import UINT8, UINT16, UINT32, FitBuilder

NOW = "2026-11-08T20:00:00+00:00"
FLOOR = date(2020, 1, 1)
GARMIN = ProviderId.GARMIN.value
WAHOO = ProviderId.WAHOO.value
RECORD_FIELDS = [(253, UINT32), (3, UINT8), (5, UINT32), (7, UINT16)]
LAP_FIELDS = [(2, UINT32), (7, UINT32)]
SET_FIELDS = [(5, UINT8), (3, UINT16), (4, UINT16)]


def fit_bytes(records: int = 5, *, laps: int = 1, sets: int = 0) -> bytes:
    builder = FitBuilder().define(0, 20, RECORD_FIELDS)
    for index in range(records):
        builder.data(
            0, {253: 1000 + index, 3: 120 + index, 5: 100 * index, 7: 200 + index}
        )
    if laps:
        builder.define(1, 19, LAP_FIELDS)
        for index in range(laps):
            builder.data(1, {2: 1000 + index, 7: 1000})
    if sets:
        builder.define(2, 225, SET_FIELDS)
        for _ in range(sets):
            builder.data(2, {5: 1, 3: 8, 4: 160})
    return builder.build()


def no_sensor_fit() -> bytes:
    """A valid file whose only message is a lap: no record stream."""
    return fit_bytes(records=0, laps=1)


class _Manager:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    @contextmanager
    def unit_of_work(self):
        yield self.db
        self.db.commit()

    @contextmanager
    def reader(self):
        yield self.db


@dataclass
class Env:
    db: sqlite3.Connection
    manager: _Manager
    key_values: KeyValueRepository


def make_env(case: unittest.TestCase) -> Env:
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    db = sqlite3.connect(Path(temporary.name) / "streams.db")
    case.addCleanup(db.close)
    db.row_factory = sqlite3.Row
    initialize_schema(db)
    db.commit()
    return Env(db, _Manager(db), KeyValueRepository(lambda: NOW))


def seed(
    env: Env,
    provider: str,
    number: int,
    day: date,
    *,
    sport: Sport = Sport.RIDE,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
) -> str:
    started = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
    identifier = str(number)
    canonical_store.upsert_activity_record(
        env.db,
        ActivityRecord(
            activity_id=identifier,
            provenance=Provenance(
                provider=ProviderId(provider),
                source_kind=SourceKind.DEVICE_MEASURED,
                source_record_id=identifier,
                recorded_by=recorded_by,
                retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
                label=None,
            ),
            sport=sport,
            environment=Environment.OUTDOOR,
            started_at=started,
            duration_s=3000.0,
            distance_m=30000.0,
            load=50.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
            avg_hr=140.0,
            avg_power=None,
            name="Synthetic ride",
        ),
        local_date=day,
        mapper_version=1,
        fetched_at=NOW,
        now=NOW,
    )
    env.db.commit()
    return identifier


def stored_sets(env: Env, provider: str, identifier: str) -> dict[str, Any]:
    return {
        item.detail.kind.value: item
        for item in detail_sets_for(env.db, provider, identifier)
    }


def full_streams(env: Env, identifier: str) -> bool:
    row = env.db.execute(
        "SELECT activity_id FROM activity_records WHERE provider_activity_id = ?",
        (identifier,),
    ).fetchone()
    return bool(full_stream_keys(env.db, [row["activity_id"]]))


def cursor_of(env: Env, provider: str) -> Any:
    return read_cursor(env.db, provider, STREAM_HISTORY_CURSOR).get("cursor")


def state_of(env: Env, provider: str) -> dict[str, Any]:
    return json.loads(env.key_values.get(env.db, state_key(provider)) or "{}")


def _external_call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


def _hooks(rejected: bool = False, guard: Any = None) -> RatingReadHooks:
    extra = {} if guard is None else {"guard": guard}
    return RatingReadHooks(
        error_class=sync_job_error_class,
        skippable=_skippable_history_error,
        key_rejected=lambda: rejected,
        **extra,
    )


def http_error(status: int) -> provider_http.ProviderHTTPError:
    return provider_http.classify_provider_status(status, "garmin")


class _GarminClient:
    """The ``download_activity_fit`` shape of the Personal API client."""

    def __init__(self, files: dict[str, Any]) -> None:
        self.files = files
        self.read: list[str] = []

    def download_activity_fit(self, activity_id: str) -> bytes | None:
        self.read.append(activity_id)
        value = self.files[activity_id]
        if isinstance(value, Exception):
            raise value
        return value


class _GarminReader:
    def __init__(
        self,
        client: Any,
        sleeps: list[float] | None = None,
        rejected: bool = False,
    ) -> None:
        self.client = client
        self.sleeps = sleeps if sleeps is not None else []
        self.rejected = rejected
        self.calls = 0

    def fetch_activity_files(
        self, activity_ids: Any, on_file: Any, on_skip: Any, guard: Any
    ) -> None:
        self.calls += 1
        collect_activity_fit_files(
            self.client,
            activity_ids,
            on_file,
            on_skip,
            external_call=_external_call,
            hooks=_hooks(self.rejected, guard),
            sleep=self.sleeps.append,
        )


def garmin_service(
    env: Env,
    client: Any,
    *,
    sleeps: list[float] | None = None,
    rejected: bool = False,
    batch_limit: int = 30,
    configured: bool = True,
) -> StreamBackfillService:
    return StreamBackfillService(
        provider=GARMIN,
        source=GarminStreamSource(_GarminReader(client, sleeps, rejected)),
        mapping=GarminStreamMapping(),
        database_manager=lambda: env.manager,
        key_values=env.key_values,
        guard=nullcontext,
        utc_now=lambda: NOW,
        configured=lambda: configured,
        earliest_date=FLOOR,
        batch_limit=batch_limit,
    )


class _Lister:
    """Stands in for the Wahoo read transport."""

    def __init__(self, rows: list[dict[str, Any]], *, truncated: bool = False) -> None:
        self.rows = rows
        self.truncated = truncated
        self.calls: list[tuple[datetime, datetime | None, int]] = []
        self.error: BaseException | None = None

    def list_workouts(
        self, *, since: datetime, until: datetime | None = None, max_pages: int = 20
    ) -> WahooWorkoutFetch:
        self.calls.append((since, until, max_pages))
        if self.error is not None:
            raise self.error
        return WahooWorkoutFetch(tuple(self.rows), 0, truncated=self.truncated)


def wahoo_row(number: int, *, link: bool = True) -> dict[str, Any]:
    summary: dict[str, Any] = {"duration_active_accum": "3600"}
    if link:
        summary["file"] = {"url": f"https://cdn.wahooligan.com/{number}.fit?sig=x"}
    return {"id": number, "workout_summary": summary}


class _Downloads:
    """Fake CDN: FIT bytes or a queued failure per workout number."""

    def __init__(self, files: dict[int, Any]) -> None:
        self.files = files
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        number = int(url.rsplit("/", 1)[1].split(".")[0])
        value = self.files[number]
        if isinstance(value, Exception):
            raise value
        return value


def wahoo_service(
    env: Env,
    rows: list[dict[str, Any]],
    files: dict[int, Any],
    *,
    sleeps: list[float] | None = None,
    batch_limit: int = 40,
    truncated: bool = False,
) -> tuple[StreamBackfillService, _Lister, _Downloads]:
    lister = _Lister(rows, truncated=truncated)
    downloads = _Downloads(files)
    sleeps = sleeps if sleeps is not None else []
    service = StreamBackfillService(
        provider=WAHOO,
        source=WahooStreamSource(
            client=lambda: lister,
            download=downloads,
            gate=ProviderResyncGate(WAHOO),
            sleep=sleeps.append,
        ),
        mapping=WahooStreamMapping(),
        database_manager=lambda: env.manager,
        key_values=env.key_values,
        guard=nullcontext,
        utc_now=lambda: NOW,
        configured=lambda: True,
        earliest_date=FLOOR,
        batch_limit=batch_limit,
    )
    return service, lister, downloads


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(self)

    def test_only_eligible_records_without_streams_are_candidates_newest_first(
        self,
    ) -> None:
        env = self.env
        day = date(2026, 11, 1)
        seed(env, GARMIN, 1, day, recorded_by=RecordingOrigin.GARMIN)
        seed(
            env, GARMIN, 2, day + timedelta(days=2), recorded_by=RecordingOrigin.GARMIN
        )
        seed(env, GARMIN, 3, day + timedelta(days=1), sport=Sport.STRENGTH)
        seed(
            env, GARMIN, 4, day + timedelta(days=3), recorded_by=RecordingOrigin.MANUAL
        )
        seed(env, GARMIN, 5, FLOOR - timedelta(days=1))
        seed(env, WAHOO, 6, day)

        selection = select_stream_candidates(env.db, GARMIN, earliest=FLOOR)

        self.assertEqual(
            ["2", "1"], [c.provider_activity_id for c in selection.candidates]
        )
        self.assertEqual(0, selection.with_streams)

    def test_a_record_with_full_streams_is_counted_and_not_selected(self) -> None:
        env = self.env
        seed(env, GARMIN, 1, date(2026, 11, 1), recorded_by=RecordingOrigin.GARMIN)
        service = garmin_service(env, _GarminClient({"1": fit_bytes()}))
        service.backfill(None)

        selection = select_stream_candidates(env.db, GARMIN, earliest=FLOOR)

        self.assertEqual((), selection.candidates)
        self.assertEqual(1, selection.with_streams)

    def test_excluded_ids_are_not_candidates(self) -> None:
        seed(self.env, WAHOO, 1, date(2026, 11, 1))
        seed(self.env, WAHOO, 2, date(2026, 11, 2))

        selection = select_stream_candidates(
            self.env.db, WAHOO, excluded=frozenset({"2"})
        )

        self.assertEqual(["1"], [c.provider_activity_id for c in selection.candidates])

    def test_a_batch_takes_whole_days_newest_first_up_to_the_end_day(self) -> None:
        candidates = tuple(
            StreamCandidate(str(n), f"2026-10-{30 - (n + 1) // 2:02d}", "", "")
            for n in range(34)
        )
        selection = StreamSelection(candidates, 0)

        batch, more = selection.batch(None, 30)

        self.assertTrue(more)
        # Day 15 holds the 30th and 31st candidate: the day is never split.
        self.assertEqual(31, len(batch))
        self.assertEqual("2026-10-15", batch[-1].day)
        later, _ = selection.batch(date(2026, 10, 20), 30)
        self.assertTrue(all(item.day <= "2026-10-20" for item in later))
        everything, rest = StreamSelection(candidates[:3], 0).batch(None, 30)
        self.assertEqual((3, False), (len(everything), rest))


class WahooBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(self)

    def test_streams_and_laps_are_stored_under_wahoo_and_a_rerun_reads_nothing(
        self,
    ) -> None:
        env = self.env
        seed(env, WAHOO, 11, date(2026, 11, 3))
        seed(env, WAHOO, 12, date(2026, 11, 2))
        service, lister, downloads = wahoo_service(
            env,
            [wahoo_row(11), wahoo_row(12)],
            {11: fit_bytes(), 12: fit_bytes(records=7)},
        )

        result = service.backfill(None)

        self.assertEqual(2, result["stored"])
        self.assertIsNone(result["historical_next_end"])
        sets = stored_sets(env, WAHOO, "11")
        self.assertEqual({"streams", "laps"}, set(sets))
        self.assertEqual(
            ("wahoo", RecordingOrigin.WAHOO),
            (
                sets["streams"].detail.provenance.provider.value,
                sets["streams"].detail.provenance.recorded_by,
            ),
        )
        self.assertTrue(full_streams(env, "12"))
        self.assertEqual(FLOOR.isoformat(), cursor_of(env, WAHOO))
        since, until, pages = lister.calls[0]
        self.assertEqual(HISTORY_WORKOUT_PAGES, pages)
        self.assertEqual(datetime(2026, 11, 1, 10, tzinfo=UTC), since)
        self.assertEqual(datetime(2026, 11, 4, 10, tzinfo=UTC), until)
        downloads.urls.clear()

        again = service.backfill(None)

        self.assertEqual(0, again["candidates"])
        self.assertEqual([], downloads.urls)
        self.assertEqual(1, len(lister.calls))

    def test_downloads_are_paced_but_the_first_one_is_not_delayed(self) -> None:
        env = self.env
        for number in (1, 2, 3):
            seed(env, WAHOO, number, date(2026, 11, number))
        sleeps: list[float] = []
        service, _lister, _downloads = wahoo_service(
            env,
            [wahoo_row(n) for n in (1, 2, 3)],
            {n: fit_bytes() for n in (1, 2, 3)},
            sleeps=sleeps,
        )

        service.backfill(None)

        self.assertEqual(2, len(sleeps))

    def test_a_rate_limit_keeps_stored_files_and_the_cursor(self) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        seed(env, WAHOO, 2, date(2026, 11, 2))
        service, _lister, _downloads = wahoo_service(
            env,
            [wahoo_row(1), wahoo_row(2)],
            {1: fit_bytes(), 2: WahooFitUnavailable("rate_limited")},
        )

        with self.assertRaises(AppError) as raised:
            service.backfill(None)

        self.assertEqual(
            (429, "rate_limited"), (raised.exception.status, raised.exception.reason)
        )
        self.assertTrue(full_streams(env, "1"))
        self.assertFalse(full_streams(env, "2"))
        self.assertIsNone(cursor_of(env, WAHOO))

    def test_a_transient_failure_stops_the_job_and_the_third_one_skips_the_file(
        self,
    ) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        seed(env, WAHOO, 2, date(2026, 11, 2))
        files: dict[int, Any] = {
            1: WahooFitUnavailable("unavailable"),
            2: fit_bytes(),
        }
        service, _lister, _downloads = wahoo_service(
            env, [wahoo_row(1), wahoo_row(2)], files
        )

        for _ in range(FAILURE_LIMIT):
            with self.assertRaises(AppError) as raised:
                service.backfill(None if _ == 0 else date(2026, 11, 3))
            self.assertEqual(503, raised.exception.status)
        self.assertFalse(full_streams(env, "2"))
        self.assertEqual(["1"], state_of(env, WAHOO)["skipped_ids"])

        result = service.backfill(date(2026, 11, 3))

        # The failing file no longer blocks the rest.
        self.assertEqual(1, result["stored"])
        self.assertTrue(full_streams(env, "2"))

    def test_a_rejected_expired_link_skips_only_that_file(self) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        seed(env, WAHOO, 2, date(2026, 11, 2))
        service, _lister, _downloads = wahoo_service(
            env,
            [wahoo_row(1), wahoo_row(2)],
            {1: WahooFitUnavailable("rejected"), 2: fit_bytes()},
        )

        result = service.backfill(None)

        self.assertEqual((1, 1), (result["skipped"], result["stored"]))
        self.assertEqual(["1"], state_of(env, WAHOO)["skipped_ids"])
        # A fresh chain lets a skipped file try again; a continuation does not.
        self.assertEqual(
            0,
            service.backfill(date(2026, 11, 3))["candidates"],
        )
        self.assertEqual(1, service.backfill(None)["candidates"])

    def test_workouts_without_a_file_or_gone_from_a_complete_listing_are_marked(
        self,
    ) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        seed(env, WAHOO, 2, date(2026, 11, 2))
        service, _lister, downloads = wahoo_service(env, [wahoo_row(1, link=False)], {})

        result = service.backfill(None)

        self.assertEqual(2, result["no_file"])
        self.assertEqual([], downloads.urls)
        self.assertEqual(["1", "2"], state_of(env, WAHOO)["no_file_ids"])
        self.assertEqual(0, service.backfill(None)["candidates"])

    def test_a_truncated_listing_does_not_vouch_that_a_workout_is_gone(self) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        service, _lister, _downloads = wahoo_service(env, [], {}, truncated=True)

        result = service.backfill(None)

        self.assertEqual((0, 1), (result["no_file"], result["skipped"]))

    def test_a_file_without_sensor_records_is_marked_and_replaces_nothing(
        self,
    ) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        service, _lister, _downloads = wahoo_service(
            env, [wahoo_row(1)], {1: no_sensor_fit()}
        )

        result = service.backfill(None)

        self.assertEqual((0, 1), (result["stored"], result["no_streams"]))
        self.assertEqual({}, stored_sets(env, WAHOO, "1"))
        self.assertEqual(0, service.backfill(None)["candidates"])

    def test_strength_sets_of_a_file_are_never_stored(self) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        service, _lister, _downloads = wahoo_service(
            env, [wahoo_row(1)], {1: fit_bytes(sets=2)}
        )

        service.backfill(None)

        self.assertEqual({"streams", "laps"}, set(stored_sets(env, WAHOO, "1")))

    def test_a_record_deleted_while_the_batch_ran_is_not_written(self) -> None:
        env = self.env
        seed(env, WAHOO, 1, date(2026, 11, 3))
        service, _lister, downloads = wahoo_service(
            env, [wahoo_row(1)], {1: fit_bytes()}
        )
        original = downloads.__call__

        def delete_then_download(url: str) -> bytes:
            env.db.execute(
                "UPDATE activity_records SET state = 'deleted' "
                "WHERE provider_activity_id = '1'"
            )
            return original(url)

        source: Any = service._source
        source._download = delete_then_download

        result = service.backfill(None)

        self.assertEqual(0, result["stored"])
        self.assertEqual({}, stored_sets(env, WAHOO, "1"))

    def test_the_chain_walks_back_in_batches_and_finishes_at_the_floor(self) -> None:
        env = self.env
        days = [date(2026, 11, 5) - timedelta(days=n) for n in range(5)]
        for number, day in enumerate(days, start=1):
            seed(env, WAHOO, number, day)
        rows = [wahoo_row(n) for n in range(1, 6)]
        files = {n: fit_bytes() for n in range(1, 6)}
        service, _lister, _downloads = wahoo_service(env, rows, files, batch_limit=2)

        first = service.backfill(None)
        self.assertEqual("2026-11-03", first["historical_next_end"])
        self.assertEqual("2026-11-04", cursor_of(env, WAHOO))
        second = service.backfill(date(2026, 11, 3))
        self.assertEqual("2026-11-01", second["historical_next_end"])
        last = service.backfill(date(2026, 11, 1))

        self.assertIsNone(last["historical_next_end"])
        self.assertEqual(FLOOR.isoformat(), cursor_of(env, WAHOO))
        counts = stream_backfill_counts(env.db, env.key_values, WAHOO, FLOOR)
        self.assertEqual(
            {"candidates": 0, "with_streams": 5, "stored": 5, "finished": True},
            {
                key: counts[key]
                for key in ("candidates", "with_streams", "stored", "finished")
            },
        )

    def test_the_wahoo_continuation_payload_is_accepted(self) -> None:
        envelope = normalize_sync_job_request(
            WAHOO,
            STREAM_BACKFILL,
            {"days": 45, "end_date": "2026-11-03", "reason": "fortgesetzt"},
            all_sync_days=-1,
        )

        self.assertEqual("2026-11-03", envelope["payload"]["end_date"])


class GarminBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(self)

    def seed_run(self, number: int, day: date) -> str:
        return seed(self.env, GARMIN, number, day, recorded_by=RecordingOrigin.GARMIN)

    def test_files_are_stored_with_garmin_provenance_paced_and_idempotent(
        self,
    ) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        self.seed_run(2, date(2026, 11, 2))
        sleeps: list[float] = []
        client = _GarminClient({"1": fit_bytes(), "2": fit_bytes(records=8)})
        service = garmin_service(env, client, sleeps=sleeps)

        result = service.backfill(None)

        self.assertEqual(2, result["stored"])
        self.assertEqual(["1", "2"], client.read)
        self.assertEqual(1, len(sleeps))
        sets = stored_sets(env, GARMIN, "1")
        self.assertEqual({"streams", "laps"}, set(sets))
        self.assertEqual(
            RecordingOrigin.GARMIN, sets["streams"].detail.provenance.recorded_by
        )
        self.assertEqual("garmin", sets["streams"].detail.provenance.provider.value)
        client.read.clear()

        self.assertEqual(0, service.backfill(None)["candidates"])
        self.assertEqual([], client.read)

    def test_without_a_personal_api_key_nothing_is_read_and_the_state_says_so(
        self,
    ) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        service = garmin_service(env, object())

        result = service.backfill(None)

        self.assertEqual("ok", result["status"])
        self.assertEqual(BLOCKED_PERSONAL_API, result["reason"])
        self.assertIsNone(result["historical_next_end"])
        self.assertIsNone(cursor_of(env, GARMIN))
        counts = stream_backfill_counts(env.db, env.key_values, GARMIN, FLOOR)
        self.assertEqual(("blocked", 1), (counts["cursor"], counts["candidates"]))
        # With a key later the chain resumes and clears the mark.
        garmin_service(env, _GarminClient({"1": fit_bytes()})).backfill(None)
        self.assertIsNone(state_of(env, GARMIN)["blocked"])

    def test_a_missing_file_is_marked_and_the_rest_goes_on(self) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        self.seed_run(2, date(2026, 11, 2))
        client = _GarminClient({"1": None, "2": fit_bytes()})
        service = garmin_service(env, client)

        result = service.backfill(None)

        self.assertEqual((1, 1), (result["no_file"], result["stored"]))
        client.read.clear()
        self.assertEqual(0, service.backfill(None)["candidates"])

    def test_a_client_error_skips_one_activity_only(self) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        self.seed_run(2, date(2026, 11, 2))
        service = garmin_service(
            env, _GarminClient({"1": http_error(400), "2": fit_bytes()})
        )

        result = service.backfill(None)

        self.assertEqual((1, 1), (result["skipped"], result["stored"]))

    def test_a_rate_limit_stops_the_job_with_the_cursor_unchanged(self) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        self.seed_run(2, date(2026, 11, 2))
        service = garmin_service(
            env, _GarminClient({"1": fit_bytes(), "2": http_error(429)})
        )

        with self.assertRaises(AppError) as raised:
            service.backfill(None)

        self.assertEqual(429, raised.exception.status)
        self.assertTrue(full_streams(env, "1"))
        self.assertIsNone(cursor_of(env, GARMIN))

    def test_a_rejected_key_stops_with_the_key_hint_reason(self) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        service = garmin_service(
            env, _GarminClient({"1": http_error(401)}), rejected=True
        )

        with self.assertRaises(AppError) as raised:
            service.backfill(None)

        self.assertEqual(
            (401, PERSONAL_KEY_REJECTED_REASON),
            (raised.exception.status, raised.exception.reason),
        )

    def test_fixture_mode_neither_reads_nor_moves_the_cursor(self) -> None:
        env = self.env
        self.seed_run(1, date(2026, 11, 3))
        service = garmin_service(env, _GarminClient({}), configured=False)

        result = run_stream_backfill(service, {})

        self.assertEqual(
            {"status": "ok", "reason": "not_configured", "window_records": 0}, result
        )
        self.assertIsNone(cursor_of(env, GARMIN))

    def test_the_job_passes_its_end_day_and_needs_a_service(self) -> None:
        seen: list[date | None] = []

        class Fake:
            def available(self) -> bool:
                return True

            def backfill(self, end: date | None) -> dict[str, Any]:
                seen.append(end)
                return {"status": "ok"}

        run_stream_backfill(Fake(), {})
        run_stream_backfill(Fake(), {"end_date": "2026-11-03"})
        self.assertEqual([None, date(2026, 11, 3)], seen)
        with self.assertRaises(AppError):
            run_stream_backfill(None, {})

    def test_an_unconfigured_provider_fails_the_job(self) -> None:
        service = garmin_service(self.env, _GarminClient({}), configured=False)

        with self.assertRaises(AppError) as raised:
            service.backfill(None)

        self.assertEqual("not_configured", raised.exception.reason)


class CollectorTests(unittest.TestCase):
    def test_the_guard_wraps_each_read_but_not_the_pause(self) -> None:
        held: list[bool] = []
        state = {"held": False}

        @contextmanager
        def guard():
            state["held"] = True
            try:
                yield
            finally:
                state["held"] = False

        class Client:
            def download_activity_fit(self, _activity_id: str) -> bytes:
                held.append(state["held"])
                return b"x"

        pauses: list[bool] = []
        collect_activity_fit_files(
            Client(),
            ["1", "2"],
            lambda _id, _data: None,
            lambda _id: None,
            external_call=_external_call,
            hooks=_hooks(guard=guard),
            sleep=lambda _seconds: pauses.append(state["held"]),
        )

        self.assertEqual([True, True], held)
        self.assertEqual([False], pauses)

    def test_a_non_file_answer_skips_the_activity(self) -> None:
        skipped: list[str] = []

        class Client:
            def download_activity_fit(self, _activity_id: str) -> Any:
                return {"unexpected": True}

        collect_activity_fit_files(
            Client(),
            ["1"],
            lambda _id, _data: None,
            skipped.append,
            external_call=_external_call,
            hooks=_hooks(),
            sleep=lambda _seconds: None,
        )

        self.assertEqual(["1"], skipped)


class VisibilityTests(unittest.TestCase):
    def test_diagnostics_carry_counts_for_both_providers_and_no_ids(self) -> None:
        env = make_env(self)
        seed(env, WAHOO, 987654, date(2026, 11, 3))
        service, _lister, _downloads = wahoo_service(env, [], {})
        service.backfill(None)

        report = summarize_stream_backfill(env.key_values, env.db, FLOOR)

        self.assertEqual({GARMIN, WAHOO}, set(report))
        self.assertEqual(1, report[WAHOO]["no_file"])
        self.assertEqual("finished", report[WAHOO]["cursor"])
        self.assertEqual("not_started", report[GARMIN]["cursor"])
        self.assertNotIn("987654", json.dumps(report))

    def test_diagnostics_degrade_instead_of_failing(self) -> None:
        env = make_env(self)
        env.db.execute("DROP TABLE activity_detail_sets")

        self.assertEqual(
            {"status": "unavailable"},
            summarize_stream_backfill(env.key_values, env.db, FLOOR),
        )

    def test_the_wahoo_adapter_routes_the_job_type(self) -> None:
        seen: list[Any] = []

        class Backfill:
            def available(self) -> bool:
                return True

            def backfill(self, end: Any) -> dict[str, Any]:
                seen.append(end)
                return {"status": "ok"}

        class Sync:
            def sync(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                raise AssertionError("a stream job must not run the sync")

        adapter = WahooJobAdapter(sync=Sync(), stream_backfill=Backfill())

        result = adapter.execute(
            {"id": "job"}, {"end_date": "2026-11-03"}, "r", job_type=STREAM_BACKFILL
        )

        self.assertEqual({"status": "ok"}, result)
        self.assertEqual([date(2026, 11, 3)], seen)

    def test_a_cursor_at_the_floor_is_finished_even_after_a_manual_rewrite(
        self,
    ) -> None:
        env = make_env(self)
        write_cursor(
            env.db, GARMIN, STREAM_HISTORY_CURSOR, FLOOR.isoformat(), None, NOW
        )

        counts = stream_backfill_counts(env.db, env.key_values, GARMIN, FLOOR)

        self.assertTrue(counts["finished"])


SYNTHETIC_KEY = "synthetic-personal-key"


class _Response(io.BytesIO):
    status = 200


class FakeFileApi:
    """The Personal API token and file download endpoints, with synthetic files."""

    def __init__(self, files: dict[str, Any]) -> None:
        self.files = files
        self.token_exchanges = 0
        self.paths: list[str] = []

    def __call__(self, request: Any, timeout: float) -> _Response:
        path = urlparse(request.full_url).path
        if path == TOKEN_PATH:
            self.token_exchanges += 1
            return _Response(b'"header.t.signature"')
        self.paths.append(path)
        value = self.files[path.rsplit("/", 1)[1]]
        if isinstance(value, int):
            raise HTTPError(request.full_url, value, "x", Message(), io.BytesIO())
        return _Response(value)


def zipped(data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("11_ACTIVITY.fit", data)
    return buffer.getvalue()


class TransportTests(unittest.TestCase):
    def collect(self, api: FakeFileApi, ids: list[str]) -> dict[str, bytes | None]:
        client = GarminTransportClient(
            GarminPersonalClient(SYNTHETIC_KEY, opener=api), None
        )
        files: dict[str, bytes | None] = {}
        collect_activity_fit_files(
            client,
            ids,
            files.__setitem__,
            lambda _id: None,
            external_call=_external_call,
            hooks=_hooks(),
            sleep=lambda _seconds: None,
        )
        return files

    def test_archives_and_bare_files_are_unpacked_with_one_token_exchange(
        self,
    ) -> None:
        fit = fit_bytes()
        api = FakeFileApi({"11": zipped(fit), "12": fit, "13": 404})

        files = self.collect(api, ["11", "12", "13"])

        self.assertEqual({"11": fit, "12": fit, "13": None}, files)
        self.assertEqual(1, api.token_exchanges)
        self.assertEqual(
            [f"/download-service/files/activity/{n}" for n in (11, 12, 13)],
            api.paths,
        )

    def test_an_upload_that_is_not_fit_counts_as_no_file(self) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("11_ACTIVITY.gpx", b"<gpx/>")

        files = self.collect(FakeFileApi({"11": archive.getvalue()}), ["11"])

        self.assertEqual({"11": None}, files)

    def test_the_sdk_alone_has_no_download_and_ends_before_any_request(self) -> None:
        with self.assertRaises(FitTransportMissing):
            collect_activity_fit_files(
                GarminTransportClient(None, object()),
                ["11"],
                lambda _id, _data: None,
                lambda _id: None,
                external_call=_external_call,
                hooks=_hooks(),
            )


class RemoteReaderTests(unittest.TestCase):
    def reader(self, key: str) -> GarminRemoteReader:
        config = SimpleNamespace(
            garmin_personal_api_key=key,
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
        )
        factory = Mock()
        factory.available.return_value = False
        reader = GarminRemoteReader(
            cast(Any, config),
            factory,
            Mock(),
            Mock(),
            lambda value: value,
            Mock(),
            lambda: NOW,
            lambda: date(2026, 11, 8),
            FLOOR,
            90,
            -1,
        )
        cast(Mock, reader._state_service).personal_key_rejected.return_value = False
        return reader

    def test_downloads_use_one_personal_token_for_the_batch(self) -> None:
        reader = self.reader(SYNTHETIC_KEY)
        api = FakeFileApi({"11": fit_bytes(), "12": fit_bytes()})
        personal = GarminPersonalClient(SYNTHETIC_KEY, opener=api)
        files: dict[str, bytes | None] = {}
        with (
            patch(
                "backend.sync.garmin_service._personal_client", return_value=personal
            ),
            patch("backend.providers.garmin_rating_history.time.sleep"),
        ):
            reader.fetch_activity_files(
                ["11", "12"], files.__setitem__, lambda _id: None, nullcontext
            )

        self.assertEqual({"11", "12"}, set(files))
        self.assertEqual(1, api.token_exchanges)

    def test_without_a_personal_key_no_login_is_attempted(self) -> None:
        reader = self.reader("")

        # An SDK-only account is configured but has no file download.
        with (
            patch.object(reader, "configured", return_value=True),
            patch.object(
                reader, "_authenticated_client", side_effect=AssertionError("login")
            ),
            self.assertRaises(FitTransportMissing),
        ):
            reader.fetch_activity_files(
                ["11"], lambda _id, _data: None, lambda _id: None, nullcontext
            )


if __name__ == "__main__":
    unittest.main()
