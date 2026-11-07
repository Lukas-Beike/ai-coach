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
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch
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
    RatingReadRateLimited,
    RatingReadRejected,
    collect_activity_ratings,
)
from backend.sync.cursors import read_cursor
from backend.sync.executor import GarminSyncJobOwner
from backend.sync.garmin_rating_backfill import (
    BATCH_LIMIT,
    STATE_KEY,
    GarminRatingBackfillService,
    RatingCandidate,
    RatingSelection,
    select_rating_candidates,
)
from backend.sync.garmin_service import GarminRemoteReader
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.jobs import (
    BACKFILL_CURSOR_STREAMS,
    RATING_BACKFILL,
    RATING_HISTORY_CURSOR,
)
from backend.sync.local_load import refresh_after_job

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-11-07T20:00:00+00:00"
FLOOR = date(2020, 1, 1)
SYNTHETIC_KEY = "synthetic-personal-key"


def _external_call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


def _no_sleep(_seconds: float) -> None:
    return None


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
        self.released = 0

    @contextmanager
    def operation(self):
        yield

    def acquire(self, *, timeout: float | None = None) -> bool:
        return True

    def release(self) -> None:
        self.released += 1


class _Client:
    """The ``get_activity`` shape of both transports; ratings by activity id."""

    def __init__(self, ratings: dict[str, Any]) -> None:
        self.ratings = ratings
        self.read: list[str] = []

    def get_activity(self, activity_id: str) -> Any:
        self.read.append(activity_id)
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
    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls = 0

    def fetch_activity_ratings(self, activities: Any, sink: Any) -> int:
        self.calls += 1
        return collect_activity_ratings(
            self.client,
            activities,
            sink,
            external_call=_external_call,
            sleep=_no_sleep,
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


class BackfillCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = sqlite3.connect(Path(temporary.name) / "ratings.db")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        initialize_schema(self.db)
        self.db.commit()
        self.key_values = KeyValueRepository(lambda: NOW)
        self.writer = GarminSnapshotWriter(self.key_values, lambda: ZONE)
        self.coordination = _Coordination()

    def seed(
        self,
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
                self.db,
                _intervals_record(f"i{number}", started, **intervals),
                local_date=day,
                mapper_version=1,
                fetched_at=NOW,
                now=NOW,
            )
        if garmin:
            sections: dict[str, Any] = {
                "activities": [_garmin_row(number, started)],
            }
            if garmin_rating is not None:
                sections["activity_ratings"] = [
                    {"activityId": str(number), **garmin_rating}
                ]
            self.writer.write_refresh(
                self.db,
                fetched_at=NOW,
                sections=sections,
                view={},
                windows={},
                allowed=frozenset(sections),
            )
        self.db.commit()

    def service(
        self, client: Any, configured: bool = True
    ) -> tuple[GarminRatingBackfillService, _Reader]:
        reader = _Reader(client)
        return (
            GarminRatingBackfillService(
                reader=reader,
                database_manager=_Manager(self.db),
                snapshot_writer=self.writer,
                key_values=self.key_values,
                coordination=self.coordination,
                utc_now=lambda: NOW,
                configured=lambda: configured,
                earliest_date=FLOOR,
            ),
            reader,
        )

    def garmin_record(self, number: int) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT json_extract(details, '$.rpe') AS rpe, "
            "json_extract(details, '$.feel') AS feel, activity_id FROM activity_records "
            "WHERE provider = 'garmin' AND provider_activity_id = ?",
            (str(number),),
        ).fetchone()
        return dict(row)

    def cursor(self) -> Any:
        return read_cursor(self.db, "garmin", RATING_HISTORY_CURSOR).get("cursor")

    def state(self) -> dict[str, Any]:
        return json.loads(self.key_values.get(self.db, STATE_KEY) or "{}")


class SelectionTests(BackfillCase):
    def test_sessions_are_classified_by_their_garmin_copy(self) -> None:
        day = date(2026, 11, 3)
        self.seed(1, day, intervals={"rpe": 6.0, "feel": 1.0})
        self.seed(
            2,
            day + timedelta(days=1),
            intervals={"rpe": 5.0},
            garmin_rating={"directWorkoutRpe": 50, "directWorkoutFeel": None},
        )
        self.seed(3, day + timedelta(days=2), intervals={"rpe": 7.0}, garmin=False)
        self.seed(4, day + timedelta(days=3), intervals={})
        self.seed(5, day + timedelta(days=4), intervals=None)

        selection = select_rating_candidates(self.db)

        self.assertEqual(["1"], [c.garmin_activity_id for c in selection.candidates])
        self.assertEqual(1, selection.already_rated)
        self.assertEqual(1, selection.no_garmin_copy)

    def test_a_read_rating_row_without_values_is_not_selected_again(self) -> None:
        self.seed(
            1,
            date(2026, 11, 3),
            intervals={"rpe": 6.0},
            garmin_rating={"directWorkoutRpe": None, "directWorkoutFeel": None},
        )

        selection = select_rating_candidates(self.db)

        self.assertEqual((), selection.candidates)
        self.assertEqual(1, selection.already_rated)

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


class ServiceTests(BackfillCase):
    def test_a_rating_is_stored_on_the_garmin_scales_and_rerun_changes_nothing(
        self,
    ) -> None:
        self.seed(1, date(2026, 11, 3), intervals={"rpe": 6.0, "feel": 1.0})
        client = _Client({"1": (60, 100)})
        service, _reader = self.service(client)

        result = service.backfill(None)

        self.assertEqual(1, result["backfilled"])
        self.assertIsNone(result["historical_next_end"])
        record = self.garmin_record(1)
        # Garmin 60 -> RPE 6; feel 100 (very strong) -> 5 - 100 / 25 = 1.
        self.assertEqual((6.0, 1.0), (record["rpe"], record["feel"]))
        self.assertEqual(FLOOR.isoformat(), self.cursor())
        self.assertTrue(self.state()["finished"])
        stored = garmin_store.read_item(self.db, "activity_ratings", "1")
        self.assertEqual(60, cast(dict[str, Any], stored)["directWorkoutRpe"])
        before = self.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0]
        rerun_client = _Client({})
        rerun, _ = self.service(rerun_client)

        again = rerun.backfill(None)

        self.assertEqual(0, again["candidates"])
        self.assertEqual([], rerun_client.read)
        self.assertEqual(
            before,
            self.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0],
        )
        self.assertEqual(
            (6.0, 1.0), (self.garmin_record(1)["rpe"], self.garmin_record(1)["feel"])
        )

    def test_a_rate_limit_parks_the_cursor_and_keeps_the_rows_read(self) -> None:
        for number in (1, 2, 3):
            self.seed(number, date(2026, 11, number), intervals={"rpe": 5.0})
        limited = provider_http.classify_provider_status(429, "garmin")
        client = _Client({"3": (50, None), "2": limited, "1": (50, None)})
        service, _reader = self.service(client)

        with self.assertRaises(RatingReadRateLimited):
            service.backfill(None)

        self.assertEqual(["3", "2"], client.read)
        self.assertIsNone(self.cursor())
        self.assertEqual(5.0, self.garmin_record(3)["rpe"])
        self.assertIsNone(self.garmin_record(2)["rpe"])
        self.assertFalse(self.state()["finished"])
        self.assertEqual(1, self.coordination.released)

    def test_one_bad_activity_is_skipped_and_counted(self) -> None:
        self.seed(1, date(2026, 11, 1), intervals={"rpe": 5.0})
        self.seed(2, date(2026, 11, 2), intervals={"rpe": 5.0})
        missing = provider_http.classify_provider_status(404, "garmin")
        service, _reader = self.service(_Client({"2": missing, "1": (50, None)}))

        result = service.backfill(None)

        self.assertEqual((1, 1), (result["skipped"], result["backfilled"]))
        self.assertEqual(1, self.state()["skipped"])
        self.assertEqual(5.0, self.garmin_record(1)["rpe"])
        self.assertIsNone(self.garmin_record(2)["rpe"])

    def test_the_chain_resumes_below_the_cursor_after_a_restart(self) -> None:
        total = BATCH_LIMIT + 5
        ratings = {}
        for number in range(1, total + 1):
            self.seed(
                number,
                date(2026, 9, 1) + timedelta(days=number),
                intervals={"rpe": 5.0},
            )
            ratings[str(number)] = (50, None)
        client = _Client(ratings)
        first, _ = self.service(client)

        result = first.backfill(None)

        self.assertEqual(BATCH_LIMIT, result["candidates"])
        oldest = result["historical_next_end"]
        self.assertIsNotNone(oldest)
        # The cursor is the oldest day read; the scheduler resumes the day below.
        self.assertEqual(
            (date.fromisoformat(oldest) + timedelta(days=1)).isoformat(),
            self.cursor(),
        )
        self.assertFalse(self.state()["finished"])
        resumed, _ = self.service(client)

        last = resumed.backfill(date.fromisoformat(oldest))

        self.assertEqual(5, last["candidates"])
        self.assertIsNone(last["historical_next_end"])
        self.assertEqual(sorted(ratings), sorted(set(client.read)))
        self.assertEqual(len(client.read), len(set(client.read)))
        self.assertEqual(total, self.state()["backfilled"])

    def test_fixture_mode_reads_nothing(self) -> None:
        self.seed(1, date(2026, 11, 3), intervals={"rpe": 6.0})
        service, reader = self.service(_Client({}), configured=False)

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

    def test_startup_enqueues_the_chain_until_its_cursor_is_at_the_floor(self) -> None:
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
    def __init__(self, reject_token: bool = False, limit_on: str | None = None) -> None:
        self.token_exchanges = 0
        self.paths: list[str] = []
        self.reject_token = reject_token
        self.limit_on = limit_on

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
        body = {"summaryDTO": {"directWorkoutRpe": 60, "directWorkoutFeel": 100}}
        return _Response(json.dumps(body).encode())


def _personal_client(api: FakePersonalApi, **kwargs: Any) -> GarminTransportClient:
    return GarminTransportClient(
        GarminPersonalClient(SYNTHETIC_KEY, opener=api, **kwargs), None
    )


class TransportTests(unittest.TestCase):
    def collect(self, client: Any, ids: list[str]) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        skipped = collect_activity_ratings(
            client,
            [(identifier, "2026-10-01 07:00:00") for identifier in ids],
            rows.append,
            external_call=_external_call,
            sleep=_no_sleep,
        )
        return rows, skipped

    def test_the_reads_use_the_transport_with_one_token_exchange(self) -> None:
        api = FakePersonalApi()

        rows, skipped = self.collect(_personal_client(api), ["11", "12", "13"])

        self.assertEqual(3, len(rows))
        self.assertEqual(0, skipped)
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
            external_call=_external_call,
            sleep=waits.append,
            delay_seconds=1.5,
        )
        self.assertEqual([1.5, 1.5], waits)

    def test_a_rate_limit_ends_the_read(self) -> None:
        api = FakePersonalApi(limit_on="/12")
        rows: list[dict[str, Any]] = []

        with self.assertRaises(RatingReadRateLimited):
            collect_activity_ratings(
                _personal_client(api),
                [("11", ""), ("12", ""), ("13", "")],
                rows.append,
                external_call=_external_call,
                sleep=_no_sleep,
            )

        self.assertEqual(1, len(rows))
        self.assertEqual(
            ["/activity-service/activity/11", "/activity-service/activity/12"],
            api.paths,
        )

    def test_a_rejected_key_ends_the_read(self) -> None:
        with self.assertRaises(RatingReadRejected):
            self.collect(_personal_client(FakePersonalApi(reject_token=True)), ["11"])

    def test_an_unreadable_id_is_skipped(self) -> None:
        rows, skipped = self.collect(_personal_client(FakePersonalApi()), ["x", "11"])

        self.assertEqual((1, 1), (len(rows), skipped))


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
        return GarminRemoteReader(
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

    def fetch(self, reader: GarminRemoteReader, api: FakePersonalApi) -> None:
        key_result = reader._record_key_result
        personal = GarminPersonalClient(
            SYNTHETIC_KEY, opener=api, key_result=key_result
        )
        with (
            patch(
                "backend.sync.garmin_service._personal_client", return_value=personal
            ),
            patch("backend.providers.garmin_rating_history.time.sleep"),
        ):
            reader.fetch_activity_ratings([("11", ""), ("12", "")], lambda _row: None)

    def test_a_rejected_key_stops_with_the_visible_flag(self) -> None:
        reader = self.reader()

        with self.assertRaises(AppError) as raised:
            self.fetch(reader, FakePersonalApi(reject_token=True))

        self.assertEqual(PERSONAL_KEY_REJECTED_REASON, raised.exception.reason)
        reader._state_service.record_personal_key_result.assert_called_with(False)

    def test_a_rate_limit_is_a_retryable_error(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.fetch(self.reader(), FakePersonalApi(limit_on="/12"))

        self.assertEqual(
            (429, "rate_limited"), (raised.exception.status, raised.exception.reason)
        )


class DiagnosticsTests(BackfillCase):
    def test_the_section_carries_counts_only(self) -> None:
        self.seed(1, date(2026, 11, 3), intervals={"rpe": 6.0, "feel": 1.0})
        self.seed(2, date(2026, 11, 4), intervals={"rpe": 6.0}, garmin=False)
        before = summarize_rating_backfill(self.key_values, self.db, FLOOR)
        self.assertEqual("not_started", before["cursor"])
        service, _reader = self.service(_Client({"1": (60, 100)}))
        service.backfill(None)

        counts = summarize_rating_backfill(self.key_values, self.db, FLOOR)

        self.assertEqual(
            {
                "candidates": 0,
                "backfilled": 1,
                "no_rating_at_garmin": 0,
                "already_rated": 1,
                "skipped_by_error": 0,
                "no_garmin_copy": 1,
                "cursor": "finished",
                "finished": True,
            },
            counts,
        )
        for value in counts.values():
            self.assertIsInstance(value, (int, bool, str))
        self.assertNotIn("2026", json.dumps(counts))
