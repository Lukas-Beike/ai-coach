"""One-off Garmin rating backfill (#1728).

Synthetic sessions in a temporary SQLite database, a mocked Personal API opener
and fake clients; no Garmin account, key or token is used.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store, garmin_store
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.diagnostics.rating_backfill import summarize_rating_backfill
from backend.errors import AppError
from backend.providers import http as provider_http
from backend.providers.garmin_personal import (
    PERSONAL_KEY_REJECTED_REASON,
    TOKEN_PATH,
    GarminPersonalClient,
    GarminTransportClient,
)
from backend.providers.garmin_rating_history import (
    AUTH_FAILED,
    FAILED,
    KEY_REJECTED,
    RATE_LIMITED,
    RatingReadHooks,
    RatingReadStopped,
    collect_activity_ratings,
)
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.executor import GarminSyncJobOwner
from backend.sync.garmin_rating_backfill import (
    BATCH_LIMIT,
    FAILURE_LIMIT,
    STATE_KEY,
    GarminRatingBackfillService,
    RatingCandidate,
    RatingSelection,
    select_rating_candidates,
)
from backend.sync.garmin_service import GarminRemoteReader, _skippable_history_error
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.jobs import (
    BACKFILL_CURSOR_STREAMS,
    RATING_BACKFILL,
    RATING_HISTORY_CURSOR,
)
from backend.sync.local_load import refresh_after_job
from backend.sync.refresh import sync_job_error_class

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-11-07T20:00:00+00:00"
FLOOR = date(2020, 1, 1)
SYNTHETIC_KEY = "synthetic-personal-key"


def _external_call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


def _no_sleep(_seconds: float) -> None:
    return None


def _hooks(rejected: bool = False, guard: Any = None) -> RatingReadHooks:
    extra = {} if guard is None else {"guard": guard}
    return RatingReadHooks(
        error_class=sync_job_error_class,
        skippable=_skippable_history_error,
        key_rejected=lambda: rejected,
        **extra,
    )


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


class _Coordination:
    def __init__(self) -> None:
        self.held = False
        self.log: list[str] = []

    @contextmanager
    def operation(self):
        yield

    def acquire(self, *, timeout: float | None = None) -> bool:
        self.held = True
        self.log.append("acquire")
        return True

    def release(self) -> None:
        self.held = False
        self.log.append("release")


class _Client:
    """The ``get_activity`` shape of both transports; ratings by activity id."""

    def __init__(self, ratings: dict[str, Any], coordination: Any = None) -> None:
        self.ratings = ratings
        self.coordination = coordination
        self.read: list[str] = []
        self.read_while_held: list[bool] = []

    def get_activity(self, activity_id: str) -> Any:
        self.read.append(activity_id)
        if self.coordination is not None:
            self.read_while_held.append(self.coordination.held)
        value = self.ratings[activity_id]
        if isinstance(value, Exception):
            raise value
        rpe, feel = value
        return {
            "summaryDTO": {
                "directWorkoutRpe": rpe,
                "directWorkoutFeel": feel,
                "minHR": 91,
            }
        }


class _Reader:
    def __init__(self, client: Any, sleeps: list[bool] | None = None) -> None:
        self.client = client
        self.calls = 0
        self.sleeps = sleeps
        self.coordination: Any = None

    def fetch_activity_ratings(
        self, activities: Any, on_row: Any, on_skip: Any, guard: Any
    ) -> None:
        self.calls += 1

        def sleep(_seconds: float) -> None:
            if self.sleeps is not None and self.coordination is not None:
                self.sleeps.append(self.coordination.held)

        collect_activity_ratings(
            self.client,
            activities,
            on_row,
            on_skip,
            external_call=_external_call,
            hooks=_hooks(guard=guard),
            sleep=sleep,
        )


def _intervals_record(
    source_id: str,
    started: datetime,
    rpe: float | None = None,
    feel: float | None = None,
) -> Any:
    return ActivityRecord(
        activity_id=source_id,
        provenance=Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=source_id,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
            label=None,
        ),
        sport=Sport.RUN,
        environment=Environment.OUTDOOR,
        started_at=started,
        duration_s=3000.0,
        distance_m=9000.0,
        load=50.0,
        load_model=LoadModel.INTERVALS_TRAINING_LOAD,
        avg_hr=140.0,
        avg_power=None,
        name="Synthetic run",
        rpe=rpe,
        feel=feel,
    )


def _garmin_row(activity_id: int, started: datetime) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": "running"},
        "startTimeGMT": started.strftime("%Y-%m-%d %H:%M:%S"),
        "startTimeLocal": started.astimezone(ZONE).strftime("%Y-%m-%d %H:%M:%S"),
        "duration": 3000.0,
        "distance": 9000.0,
    }


@dataclass
class Env:
    """A temporary database with the writer, key values and lock of one test."""

    db: sqlite3.Connection
    key_values: KeyValueRepository
    writer: GarminSnapshotWriter
    coordination: _Coordination = field(default_factory=_Coordination)


def make_env(case: unittest.TestCase) -> Env:
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    db = sqlite3.connect(Path(temporary.name) / "ratings.db")
    case.addCleanup(db.close)
    db.row_factory = sqlite3.Row
    initialize_schema(db)
    db.commit()
    key_values = KeyValueRepository(lambda: NOW)
    return Env(db, key_values, GarminSnapshotWriter(key_values, lambda: ZONE))


def seed(
    env: Env,
    number: int,
    day: date,
    *,
    intervals: dict[str, float] | None = None,
    garmin: bool = True,
    garmin_rating: dict[str, Any] | None = None,
) -> None:
    """One session: an Intervals.icu record, optionally a Garmin copy."""
    started = datetime(day.year, day.month, day.day, 10, 0, tzinfo=UTC)
    if intervals is not None:
        canonical_store.upsert_activity_record(
            env.db,
            _intervals_record(f"i{number}", started, **intervals),
            local_date=day,
            mapper_version=1,
            fetched_at=NOW,
            now=NOW,
        )
    if garmin:
        sections: dict[str, Any] = {"activities": [_garmin_row(number, started)]}
        if garmin_rating is not None:
            sections["activity_ratings"] = [
                {"activityId": str(number), **garmin_rating}
            ]
        env.writer.write_refresh(
            env.db,
            fetched_at=NOW,
            sections=sections,
            view={},
            windows={},
            allowed=frozenset(sections),
        )
    env.db.commit()


def make_service(
    env: Env, client: Any, *, configured: bool = True, sleeps: list[bool] | None = None
) -> tuple[GarminRatingBackfillService, _Reader]:
    reader = _Reader(client, sleeps)
    reader.coordination = env.coordination
    service = GarminRatingBackfillService(
        reader=reader,
        database_manager=_Manager(env.db),
        snapshot_writer=env.writer,
        key_values=env.key_values,
        coordination=env.coordination,
        utc_now=lambda: NOW,
        configured=lambda: configured,
        earliest_date=FLOOR,
    )
    return service, reader


def garmin_record(env: Env, number: int) -> dict[str, Any]:
    row = env.db.execute(
        "SELECT json_extract(details, '$.rpe') AS rpe, "
        "json_extract(details, '$.feel') AS feel, activity_id FROM activity_records "
        "WHERE provider = 'garmin' AND provider_activity_id = ?",
        (str(number),),
    ).fetchone()
    return dict(row)


def cursor_of(env: Env) -> Any:
    return read_cursor(env.db, "garmin", RATING_HISTORY_CURSOR).get("cursor")


def state_of(env: Env) -> dict[str, Any]:
    return json.loads(env.key_values.get(env.db, STATE_KEY) or "{}")


def reach_floor(env: Env) -> None:
    """Both activity history chains have walked back to the floor."""
    for provider in ("garmin", "intervals"):
        write_cursor(env.db, provider, "historical", FLOOR.isoformat(), None, NOW)
    env.db.commit()


def http_error(status: int) -> provider_http.ProviderHTTPError:
    return provider_http.classify_provider_status(status, "garmin")


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(self)

    def test_sessions_are_classified_by_their_garmin_copy(self) -> None:
        day = date(2026, 11, 3)
        seed(self.env, 1, day, intervals={"rpe": 6.0, "feel": 1.0})
        seed(
            self.env,
            2,
            day + timedelta(days=1),
            intervals={"rpe": 5.0},
            garmin_rating={"directWorkoutRpe": 50, "directWorkoutFeel": None},
        )
        seed(self.env, 3, day + timedelta(days=2), intervals={"rpe": 7.0}, garmin=False)
        seed(self.env, 4, day + timedelta(days=3), intervals={})
        seed(self.env, 5, day + timedelta(days=4), intervals=None)

        selection = select_rating_candidates(self.env.db)

        self.assertEqual(["1"], [c.garmin_activity_id for c in selection.candidates])
        self.assertEqual(1, selection.already_rated)
        self.assertEqual(1, selection.no_garmin_copy)

    def test_a_read_rating_row_without_values_is_not_selected_again(self) -> None:
        seed(
            self.env,
            1,
            date(2026, 11, 3),
            intervals={"rpe": 6.0},
            garmin_rating={"directWorkoutRpe": None, "directWorkoutFeel": None},
        )

        selection = select_rating_candidates(self.env.db)

        self.assertEqual((), selection.candidates)
        self.assertEqual(1, selection.already_rated)

    def test_excluded_ids_and_sessions_before_the_floor_are_not_candidates(
        self,
    ) -> None:
        seed(self.env, 1, date(2026, 11, 3), intervals={"rpe": 6.0})
        seed(self.env, 2, date(2026, 11, 4), intervals={"rpe": 6.0})
        seed(self.env, 3, FLOOR - timedelta(days=1), intervals={"rpe": 6.0})

        everything = select_rating_candidates(self.env.db)
        selection = select_rating_candidates(
            self.env.db, excluded=frozenset({"2"}), earliest=FLOOR
        )

        self.assertEqual(3, len(everything.candidates))
        self.assertEqual(["1"], [c.garmin_activity_id for c in selection.candidates])

    def test_a_batch_takes_whole_days_newest_first_up_to_the_end_day(self) -> None:
        candidates = tuple(
            RatingCandidate(f"act_{n}", f"2026-10-{30 - (n + 1) // 2:02d}", "", str(n))
            for n in range(BATCH_LIMIT + 4)
        )
        selection = RatingSelection(candidates, 0, 0)

        batch, more = selection.batch(None)

        self.assertTrue(more)
        # Day 15 holds the 30th and 31st candidate: the day is never split.
        self.assertEqual(BATCH_LIMIT + 1, len(batch))
        self.assertEqual(batch[-1].day, "2026-10-15")
        later, _ = selection.batch(date(2026, 10, 20))
        self.assertTrue(all(item.day <= "2026-10-20" for item in later))
        everything, rest = RatingSelection(candidates[:3], 0, 0).batch(None)
        self.assertEqual((3, False), (len(everything), rest))


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(self)

    def test_a_rating_is_stored_on_the_garmin_scales_and_rerun_changes_nothing(
        self,
    ) -> None:
        env = self.env
        seed(env, 1, date(2026, 11, 3), intervals={"rpe": 6.0, "feel": 1.0})
        reach_floor(env)
        service, _reader = make_service(env, _Client({"1": (60, 100)}))

        result = service.backfill(None)

        self.assertEqual(1, result["backfilled"])
        self.assertIsNone(result["historical_next_end"])
        record = garmin_record(env, 1)
        # Garmin 60 -> RPE 6; feel 100 (very strong) -> 5 - 100 / 25 = 1.
        self.assertEqual((6.0, 1.0), (record["rpe"], record["feel"]))
        self.assertEqual(FLOOR.isoformat(), cursor_of(env))
        self.assertTrue(state_of(env)["finished"])
        stored = garmin_store.read_item(env.db, "activity_ratings", "1")
        self.assertEqual(60, cast(dict[str, Any], stored)["directWorkoutRpe"])
        before = env.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0]
        rerun_client = _Client({})
        rerun, _ = make_service(env, rerun_client)

        again = rerun.backfill(None)

        self.assertEqual(0, again["candidates"])
        self.assertEqual([], rerun_client.read)
        self.assertEqual(
            before,
            env.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0],
        )
        self.assertEqual((6.0, 1.0), (record["rpe"], record["feel"]))

    def test_a_rate_limit_parks_the_cursor_and_keeps_the_rows_read(self) -> None:
        env = self.env
        for number in (1, 2, 3):
            seed(env, number, date(2026, 11, number), intervals={"rpe": 5.0})
        client = _Client({"3": (50, None), "2": http_error(429), "1": (50, None)})
        service, _reader = make_service(env, client)

        with self.assertRaises(AppError) as raised:
            service.backfill(None)

        self.assertEqual(
            (429, "rate_limited"), (raised.exception.status, raised.exception.reason)
        )
        self.assertEqual(["3", "2"], client.read)
        self.assertIsNone(cursor_of(env))
        self.assertEqual(5.0, garmin_record(env, 3)["rpe"])
        self.assertIsNone(garmin_record(env, 2)["rpe"])
        self.assertFalse(state_of(env)["finished"])
        self.assertEqual(
            env.coordination.log.count("acquire"), env.coordination.log.count("release")
        )

    def test_one_bad_activity_is_skipped_counted_and_kept_out_of_later_runs(
        self,
    ) -> None:
        env = self.env
        seed(env, 4711, date(2026, 11, 1), intervals={"rpe": 5.0})
        seed(env, 4712, date(2026, 11, 2), intervals={"rpe": 5.0})
        client = _Client({"4712": http_error(404), "4711": (50, None)})
        service, _reader = make_service(env, client)

        result = service.backfill(None)

        self.assertEqual((1, 1), (result["skipped"], result["backfilled"]))
        self.assertEqual(["4712"], state_of(env)["skipped_ids"])
        self.assertEqual(5.0, garmin_record(env, 4711)["rpe"])
        self.assertIsNone(garmin_record(env, 4712)["rpe"])
        counts = summarize_rating_backfill(env.key_values, env.db)
        self.assertEqual((0, 1), (counts["candidates"], counts["skipped_by_error"]))
        self.assertNotIn("4712", json.dumps(counts))
        again, reader = make_service(env, _Client({}))
        self.assertEqual(0, again.backfill(None)["candidates"])
        self.assertEqual(0, len(cast(_Client, reader.client).read))

    def test_a_forbidden_activity_is_skipped_not_stopped(self) -> None:
        env = self.env
        seed(env, 1, date(2026, 11, 1), intervals={"rpe": 5.0})
        seed(env, 2, date(2026, 11, 2), intervals={"rpe": 5.0})
        service, _reader = make_service(
            env, _Client({"2": http_error(403), "1": (50, None)})
        )

        result = service.backfill(None)

        self.assertEqual((1, 1), (result["skipped"], result["backfilled"]))

    def test_a_persistently_failing_activity_is_skipped_after_three_runs(
        self,
    ) -> None:
        env = self.env
        seed(env, 1, date(2026, 11, 1), intervals={"rpe": 5.0})
        seed(env, 2, date(2026, 11, 2), intervals={"rpe": 5.0})
        client = _Client({"2": http_error(500), "1": (50, None)})
        service, _reader = make_service(env, client)

        for run in range(1, FAILURE_LIMIT + 1):
            with self.assertRaises(AppError) as raised:
                service.backfill(None)
            self.assertEqual("provider_unavailable", raised.exception.reason)
            self.assertIsNone(cursor_of(env))
            if run < FAILURE_LIMIT:
                self.assertEqual({"2": run}, state_of(env)["failures"])

        self.assertEqual(["2"], state_of(env)["skipped_ids"])
        self.assertEqual({}, state_of(env)["failures"])
        result = service.backfill(None)
        self.assertEqual(1, result["backfilled"])
        self.assertEqual(5.0, garmin_record(env, 1)["rpe"])
        self.assertIsNotNone(cursor_of(env))

    def test_a_missing_raw_row_is_counted_and_not_stored_as_rated(self) -> None:
        env = self.env
        seed(env, 4711, date(2026, 11, 3), intervals={"rpe": 6.0})
        env.db.execute(
            "DELETE FROM provider_records WHERE provider = 'garmin' "
            "AND record_kind = 'activity'"
        )
        env.db.commit()
        service, _reader = make_service(env, _Client({"4711": (60, None)}))

        result = service.backfill(None)

        self.assertEqual((0, 1), (result["backfilled"], result["no_raw_row"]))
        self.assertIsNone(garmin_store.read_item(env.db, "activity_ratings", "4711"))
        self.assertEqual(["4711"], state_of(env)["no_raw_ids"])
        counts = summarize_rating_backfill(env.key_values, env.db)
        self.assertEqual(
            (0, 0, 1, 0),
            (
                counts["already_rated"],
                counts["candidates"],
                counts["no_raw_row"],
                counts["backfilled"],
            ),
        )
        self.assertNotIn("4711", json.dumps(counts))

    def test_the_chain_parks_until_the_history_chains_reached_the_floor(self) -> None:
        env = self.env
        seed(env, 1, date(2026, 11, 3), intervals={"rpe": 6.0})
        service, _reader = make_service(
            env, _Client({"1": (60, None), "2": (60, None)})
        )

        result = service.backfill(None)

        self.assertIsNone(result["historical_next_end"])
        self.assertFalse(state_of(env)["finished"])
        self.assertEqual("2026-11-03", cursor_of(env))
        seed(env, 2, date(2026, 10, 1), intervals={"rpe": 6.0})
        write_cursor(env.db, "garmin", "historical", FLOOR.isoformat(), None, NOW)
        env.db.commit()
        self.assertFalse(service.backfill(date(2026, 11, 2))["historical_next_end"])
        self.assertFalse(state_of(env)["finished"])
        reach_floor(env)

        service.backfill(date(2026, 9, 30))

        self.assertTrue(state_of(env)["finished"])
        self.assertEqual(FLOOR.isoformat(), cursor_of(env))

    def test_the_lock_is_held_per_read_never_across_the_pause(self) -> None:
        env = self.env
        for number in (1, 2, 3):
            seed(env, number, date(2026, 11, number), intervals={"rpe": 5.0})
        client = _Client(
            {str(n): (50, None) for n in (1, 2, 3)}, coordination=env.coordination
        )
        sleeps: list[bool] = []
        service, _reader = make_service(env, client, sleeps=sleeps)

        service.backfill(None)

        self.assertEqual([True, True, True], client.read_while_held)
        self.assertEqual([False, False], sleeps)
        self.assertFalse(env.coordination.held)

    def test_sessions_before_the_floor_are_never_read_or_written_below_it(
        self,
    ) -> None:
        env = self.env
        seed(env, 1, FLOOR, intervals={"rpe": 5.0})
        seed(env, 2, FLOOR - timedelta(days=1), intervals={"rpe": 5.0})
        client = _Client({"1": (50, None), "2": (50, None)})
        service, _reader = make_service(env, client)

        service.backfill(None)

        self.assertEqual(["1"], client.read)
        self.assertEqual(FLOOR.isoformat(), cursor_of(env))

    def test_an_end_day_below_the_floor_finishes_without_reads(self) -> None:
        env = self.env
        seed(env, 1, date(2026, 11, 3), intervals={"rpe": 5.0})
        reach_floor(env)
        client = _Client({})
        service, _reader = make_service(env, client)

        result = service.backfill(FLOOR - timedelta(days=1))

        self.assertEqual(0, result["candidates"])
        self.assertEqual(FLOOR.isoformat(), cursor_of(env))

    def test_the_chain_resumes_below_the_cursor_after_a_restart(self) -> None:
        env = self.env
        total = BATCH_LIMIT + 5
        ratings = {}
        for number in range(1, total + 1):
            seed(
                env,
                number,
                date(2026, 9, 1) + timedelta(days=number),
                intervals={"rpe": 5.0},
            )
            ratings[str(number)] = (50, None)
        reach_floor(env)
        client = _Client(ratings)
        first, _ = make_service(env, client)

        result = first.backfill(None)

        self.assertEqual(BATCH_LIMIT, result["candidates"])
        oldest = result["historical_next_end"]
        self.assertIsNotNone(oldest)
        # The cursor is the oldest day read; the scheduler resumes the day below.
        self.assertEqual(
            (date.fromisoformat(oldest) + timedelta(days=1)).isoformat(),
            cursor_of(env),
        )
        self.assertFalse(state_of(env)["finished"])
        resumed, _ = make_service(env, client)

        last = resumed.backfill(date.fromisoformat(oldest))

        self.assertEqual(5, last["candidates"])
        self.assertIsNone(last["historical_next_end"])
        self.assertEqual(sorted(ratings), sorted(set(client.read)))
        self.assertEqual(len(client.read), len(set(client.read)))
        self.assertEqual(total, state_of(env)["backfilled"])

    def test_fixture_mode_reads_nothing(self) -> None:
        seed(self.env, 1, date(2026, 11, 3), intervals={"rpe": 6.0})
        service, reader = make_service(self.env, _Client({}), configured=False)

        self.assertFalse(service.available())
        with self.assertRaises(AppError):
            service.backfill(None)
        self.assertEqual(0, reader.calls)

    def test_a_local_load_pass_is_requested_after_the_garmin_job(self) -> None:
        started = Mock()
        hook = refresh_after_job(started)

        hook({"provider": "garmin", "type": RATING_BACKFILL})

        started.assert_called_once_with()


class ExecutorTests(unittest.TestCase):
    def owner(self, service: Any) -> GarminSyncJobOwner:
        return GarminSyncJobOwner(
            historical_sync=Mock(),
            garmin_sync_service=Mock(),
            morning_body_battery_service=Mock(),
            garmin_fixture_loader=Mock(),
            all_sync_days=-1,
            rating_backfill_service=service,
        )

    def test_the_job_passes_its_end_day_and_skips_in_fixture_mode(self) -> None:
        service = Mock()
        service.available.return_value = True
        service.backfill.return_value = {"status": "ok"}
        owner = self.owner(service)

        owner.execute({"type": RATING_BACKFILL}, {"end_date": "2026-10-05"}, "x")
        service.backfill.assert_called_once_with(date(2026, 10, 5))

        service.available.return_value = False
        service.backfill.reset_mock()
        result = owner.execute({"type": RATING_BACKFILL}, {}, "x")
        service.backfill.assert_not_called()
        self.assertEqual("not_configured", result["reason"])

    def test_the_chain_has_its_own_cursor_and_is_garmin_only(self) -> None:
        from backend.providers.descriptors import GARMIN_ID
        from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

        self.assertEqual(
            RATING_HISTORY_CURSOR, BACKFILL_CURSOR_STREAMS[RATING_BACKFILL]
        )
        self.assertTrue(
            DEFAULT_PROVIDER_REGISTRY.supports_job(GARMIN_ID, RATING_BACKFILL)
        )
        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.supports_job("intervals", RATING_BACKFILL)
        )


def _token(label: str) -> str:
    return f"header.{label}.signature"


class _Response(io.BytesIO):
    status = 200


class FakePersonalApi:
    def __init__(
        self,
        reject_token: bool = False,
        limit_on: str | None = None,
        data_status: int | None = None,
        data_status_on: str | None = None,
    ) -> None:
        self.token_exchanges = 0
        self.paths: list[str] = []
        self.reject_token = reject_token
        self.limit_on = limit_on
        self.data_status = data_status
        self.data_status_on = data_status_on

    def __call__(self, request: Any, timeout: float) -> _Response:
        path = urlparse(request.full_url).path
        if path == TOKEN_PATH:
            self.token_exchanges += 1
            if self.reject_token:
                raise HTTPError(request.full_url, 401, "no", Message(), io.BytesIO())
            return _Response(f'"{_token("t")}"'.encode())
        self.paths.append(path)
        if self.limit_on and path.endswith(self.limit_on):
            raise HTTPError(request.full_url, 429, "slow", Message(), io.BytesIO())
        if self.data_status and (
            self.data_status_on is None or path.endswith(self.data_status_on)
        ):
            raise HTTPError(
                request.full_url, self.data_status, "no", Message(), io.BytesIO()
            )
        body = {"summaryDTO": {"directWorkoutRpe": 60, "directWorkoutFeel": 100}}
        return _Response(json.dumps(body).encode())


def _personal_client(api: FakePersonalApi) -> GarminTransportClient:
    return GarminTransportClient(GarminPersonalClient(SYNTHETIC_KEY, opener=api), None)


def collect(
    client: Any, ids: list[str], hooks: RatingReadHooks | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    collect_activity_ratings(
        client,
        [(identifier, "2026-10-01 07:00:00") for identifier in ids],
        rows.append,
        skipped.append,
        external_call=_external_call,
        hooks=hooks or _hooks(),
        sleep=_no_sleep,
    )
    return rows, skipped


class TransportTests(unittest.TestCase):
    def test_the_reads_use_the_transport_with_one_token_exchange(self) -> None:
        api = FakePersonalApi()

        rows, skipped = collect(_personal_client(api), ["11", "12", "13"])

        self.assertEqual((3, 0), (len(rows), len(skipped)))
        self.assertEqual(1, api.token_exchanges)
        self.assertEqual(
            [f"/activity-service/activity/{n}" for n in (11, 12, 13)], api.paths
        )

    def test_the_calls_are_paced(self) -> None:
        waits: list[float] = []
        collect_activity_ratings(
            _Client({"1": (50, None), "2": (50, None), "3": (50, None)}),
            [("1", ""), ("2", ""), ("3", "")],
            lambda _row: None,
            lambda _id: None,
            external_call=_external_call,
            hooks=_hooks(),
            sleep=waits.append,
            delay_seconds=1.5,
        )
        self.assertEqual([1.5, 1.5], waits)

    def test_a_rate_limit_ends_the_read(self) -> None:
        api = FakePersonalApi(limit_on="/12")
        rows: list[dict[str, Any]] = []

        with self.assertRaises(RatingReadStopped) as stopped:
            collect_activity_ratings(
                _personal_client(api),
                [("11", ""), ("12", ""), ("13", "")],
                rows.append,
                lambda _id: None,
                external_call=_external_call,
                hooks=_hooks(),
                sleep=_no_sleep,
            )

        self.assertEqual(
            (RATE_LIMITED, "12"),
            (stopped.exception.kind, stopped.exception.activity_id),
        )
        self.assertEqual(1, len(rows))

    def test_a_failed_token_exchange_with_the_flagged_key_ends_the_read(self) -> None:
        with self.assertRaises(RatingReadStopped) as stopped:
            collect(
                _personal_client(FakePersonalApi(reject_token=True)),
                ["11"],
                _hooks(rejected=True),
            )

        self.assertEqual(KEY_REJECTED, stopped.exception.kind)

    def test_a_persistent_401_on_a_data_read_stops_without_the_key_verdict(
        self,
    ) -> None:
        api = FakePersonalApi(data_status=401)

        with self.assertRaises(RatingReadStopped) as stopped:
            collect(_personal_client(api), ["11", "12"])

        self.assertEqual(AUTH_FAILED, stopped.exception.kind)
        # The client renewed the token once before giving up.
        self.assertEqual(2, api.token_exchanges)

    def test_a_403_on_one_activity_is_skipped(self) -> None:
        api = FakePersonalApi(data_status=403, data_status_on="/11")

        rows, skipped = collect(_personal_client(api), ["11", "12"])

        self.assertEqual((1, ["11"]), (len(rows), skipped))

    def test_a_server_error_stops_the_read_as_failed(self) -> None:
        with self.assertRaises(RatingReadStopped) as stopped:
            collect(_personal_client(FakePersonalApi(data_status=502)), ["11"])

        self.assertEqual(FAILED, stopped.exception.kind)

    def test_an_unreadable_id_is_skipped(self) -> None:
        rows, skipped = collect(_personal_client(FakePersonalApi()), ["x", "11"])

        self.assertEqual((1, ["x"]), (len(rows), skipped))


class RemoteReaderTests(unittest.TestCase):
    def reader(self) -> GarminRemoteReader:
        config = SimpleNamespace(
            garmin_personal_api_key=SYNTHETIC_KEY,
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
            lambda: date(2026, 11, 7),
            FLOOR,
            90,
            -1,
        )
        state = cast(Mock, reader._state_service)
        state.personal_key_rejected.return_value = False

        def remember(accepted: bool) -> None:
            state.personal_key_rejected.return_value = not accepted

        state.record_personal_key_result.side_effect = remember
        return reader

    def fetch(self, reader: GarminRemoteReader, api: FakePersonalApi) -> list[str]:
        personal = GarminPersonalClient(
            SYNTHETIC_KEY, opener=api, key_result=reader._record_key_result
        )
        skipped: list[str] = []
        with (
            patch(
                "backend.sync.garmin_service._personal_client", return_value=personal
            ),
            patch("backend.providers.garmin_rating_history.time.sleep"),
        ):
            reader.fetch_activity_ratings(
                [("11", ""), ("12", "")],
                lambda _row: None,
                skipped.append,
                nullcontext,
            )
        return skipped

    def test_a_rejected_key_exchange_flags_the_key(self) -> None:
        reader = self.reader()

        with self.assertRaises(RatingReadStopped) as stopped:
            self.fetch(reader, FakePersonalApi(reject_token=True))

        self.assertEqual(KEY_REJECTED, stopped.exception.kind)
        state = cast(Mock, reader._state_service)
        state.record_personal_key_result.assert_called_with(False)

    def test_a_data_401_never_flags_the_key(self) -> None:
        reader = self.reader()

        with self.assertRaises(RatingReadStopped) as stopped:
            self.fetch(reader, FakePersonalApi(data_status=401))

        self.assertEqual(AUTH_FAILED, stopped.exception.kind)
        state = cast(Mock, reader._state_service)
        self.assertNotIn(call(False), state.record_personal_key_result.mock_calls)

    def test_a_rate_limit_is_a_stop(self) -> None:
        with self.assertRaises(RatingReadStopped) as stopped:
            self.fetch(self.reader(), FakePersonalApi(limit_on="/12"))

        self.assertEqual(RATE_LIMITED, stopped.exception.kind)


class StopErrorTests(unittest.TestCase):
    def test_the_service_maps_each_stop_to_its_job_error(self) -> None:
        expected = {
            RATE_LIMITED: (429, "rate_limited"),
            KEY_REJECTED: (401, PERSONAL_KEY_REJECTED_REASON),
            AUTH_FAILED: (503, "provider_unavailable"),
        }
        for kind, outcome in expected.items():
            with self.subTest(kind=kind):
                env = make_env(self)
                seed(env, 1, date(2026, 11, 3), intervals={"rpe": 6.0})
                reader = Mock()
                reader.fetch_activity_ratings.side_effect = RatingReadStopped(kind, "1")
                service = GarminRatingBackfillService(
                    reader=reader,
                    database_manager=_Manager(env.db),
                    snapshot_writer=env.writer,
                    key_values=env.key_values,
                    coordination=env.coordination,
                    utc_now=lambda: NOW,
                    configured=lambda: True,
                    earliest_date=FLOOR,
                )

                with self.assertRaises(AppError) as raised:
                    service.backfill(None)

                self.assertEqual(
                    outcome, (raised.exception.status, raised.exception.reason)
                )
                self.assertIsNone(cursor_of(env))
                self.assertEqual({}, state_of(env)["failures"])


class DiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = make_env(self)

    def test_the_section_carries_counts_only(self) -> None:
        env = self.env
        seed(env, 1, date(2026, 11, 3), intervals={"rpe": 6.0, "feel": 1.0})
        seed(env, 2, date(2026, 11, 4), intervals={"rpe": 6.0}, garmin=False)
        reach_floor(env)
        before = summarize_rating_backfill(env.key_values, env.db)
        self.assertEqual("not_started", before["cursor"])
        service, _reader = make_service(env, _Client({"1": (60, 100)}))
        service.backfill(None)

        counts = summarize_rating_backfill(env.key_values, env.db)

        self.assertEqual(
            {
                "candidates": 0,
                "backfilled": 1,
                "no_rating_at_garmin": 0,
                "already_rated": 1,
                "skipped_by_error": 0,
                "no_raw_row": 0,
                "no_garmin_copy": 1,
                "cursor": "finished",
                "finished": True,
            },
            counts,
        )
        for value in counts.values():
            self.assertIsInstance(value, (int, bool, str))
        self.assertNotIn("2026", json.dumps(counts))
