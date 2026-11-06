"""One-off Garmin wellness history backfill (#1730).

Synthetic payloads shaped after the sanitized 2026-11-03 SDK and Personal API
answers; temporary SQLite and fake clients only, no Garmin account or token.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import garmin_store
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.providers.garmin_wellness_history import (
    collect_wellness_history,
    has_night_values,
)
from backend.sync.executor import GarminSyncJobOwner, HistoricalSyncJobOwner
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.garmin_wellness_history import GarminWellnessHistoryService

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-11-06T20:00:00+00:00"
START = date(2021, 3, 1)
END = date(2021, 3, 2)


def _external_call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


def _night_dto(day: str, spo2: float = 95.0) -> dict[str, Any]:
    return {
        "id": 1,
        "calendarDate": day,
        "sleepTimeSeconds": 25_000,
        "averageSpO2Value": spo2,
        "lowestSpO2Value": 84,
        "averageRespirationValue": 14.0,
        "avgHeartRate": 48.0,
        "sleepScores": {"overall": {"value": 81}},
    }


class SdkClient:
    """The SDK shape: the sleep range carries statistics only."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.failing_night: str | None = None

    def get_sleep_daily(self, start: str, end: str) -> list[dict[str, Any]]:
        self.calls.append(("get_sleep_daily", (start, end)))
        return [
            {"calendarDate": "2021-03-01", "values": {"totalSleepTimeInSeconds": 1}},
            {"calendarDate": "2021-03-02", "values": {"totalSleepTimeInSeconds": 2}},
            # Outside the window: never read again or stored.
            {"calendarDate": "2021-02-27", "values": {"totalSleepTimeInSeconds": 3}},
        ]

    def get_sleep_data(self, day: str) -> dict[str, Any]:
        self.calls.append(("get_sleep_data", (day,)))
        if day == self.failing_night:
            raise RuntimeError("night unavailable")
        return {
            "dailySleepDTO": _night_dto(day),
            "wellnessEpochSPO2DataDTOList": [{"spo2Reading": 93}],
            "restingHeartRate": 45,
        }

    def get_hrv_data_range(self, start: str, end: str) -> dict[str, Any]:
        self.calls.append(("get_hrv_data_range", (start, end)))
        return {
            "hrvSummaries": [
                {"calendarDate": "2021-03-01", "lastNightAvg": 57, "weeklyAvg": 54}
            ]
        }

    def get_daily_summaries(self, start: str, end: str) -> dict[str, Any]:
        self.calls.append(("get_daily_summaries", (start, end)))
        return {
            "data": [
                {
                    "calendarDate": "2021-03-01",
                    "heartRate": {"minValue": 45, "restingValue": 46},
                },
                {"calendarDate": "2021-03-02", "heartRate": {"restingValue": 0}},
            ]
        }

    def get_weigh_ins(self, start: str, end: str) -> dict[str, Any]:
        self.calls.append(("get_weigh_ins", (start, end)))
        return {
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2021-03-01",
                    "latestWeight": {
                        "samplePk": 77,
                        "calendarDate": "2021-03-01",
                        "weight": 90_000.0,
                        "timestampGMT": 1_614_585_600_000,
                    },
                }
            ]
        }


class PersonalClient(SdkClient):
    """The Personal API shape: wrapped range nights already carry night values."""

    def get_sleep_daily(self, start: str, end: str) -> list[dict[str, Any]]:
        self.calls.append(("get_sleep_daily", (start, end)))
        return [
            {"calendarDate": day, "dailySleepDTO": _night_dto(day)}
            for day in ("2021-03-01", "2021-03-02")
        ]


class CollectorTests(unittest.TestCase):
    def collect(self, client: Any) -> dict[str, Any]:
        return collect_wellness_history(
            client, START, END, external_call=_external_call, redact=str
        )

    def test_sdk_statistics_nights_are_read_as_full_night_elements(self) -> None:
        client = SdkClient()
        payload = self.collect(client)

        self.assertEqual(
            [call for call in client.calls if call[0] == "get_sleep_data"],
            [("get_sleep_data", ("2021-03-01",)), ("get_sleep_data", ("2021-03-02",))],
        )
        self.assertEqual(
            payload["sleep"],
            [
                {"calendarDate": day, "dailySleepDTO": _night_dto(day)}
                for day in ("2021-03-01", "2021-03-02")
            ],
        )
        self.assertTrue(all(has_night_values(night) for night in payload["sleep"]))
        self.assertEqual(payload["errors"], [])

    def test_personal_range_nights_with_night_values_need_no_night_read(self) -> None:
        client = PersonalClient()
        payload = self.collect(client)

        self.assertNotIn("get_sleep_data", [name for name, _ in client.calls])
        self.assertEqual(len(payload["sleep"]), 2)

    def test_resting_heart_rate_comes_from_the_daily_summaries(self) -> None:
        payload = self.collect(SdkClient())

        self.assertEqual(
            payload["resting_hr"],
            [{"calendarDate": "2021-03-01", "restingHeartRate": 46.0}],
        )
        self.assertEqual(
            [row["calendarDate"] for row in payload["hrv"]], ["2021-03-01"]
        )

    def test_daily_summaries_are_read_in_ranges_of_at_most_31_days(self) -> None:
        client = SdkClient()
        collect_wellness_history(
            client,
            date(2021, 1, 1),
            date(2021, 3, 31),
            external_call=_external_call,
            redact=str,
        )

        self.assertEqual(
            [args for name, args in client.calls if name == "get_daily_summaries"],
            [
                ("2021-01-01", "2021-01-31"),
                ("2021-02-01", "2021-03-03"),
                ("2021-03-04", "2021-03-31"),
            ],
        )

    def test_a_range_without_weigh_ins_is_no_record(self) -> None:
        client = SdkClient()
        client.get_weigh_ins = lambda _start, _end: {  # type: ignore[method-assign]
            "dailyWeightSummaries": [],
            "totalAverage": {"weight": None},
        }
        payload = self.collect(client)

        self.assertEqual(payload["weight"], [])
        self.assertEqual(payload["provider_sync"]["pagination"]["weight"]["records"], 0)

    def test_a_failed_night_marks_only_the_sleep_incomplete(self) -> None:
        client = SdkClient()
        client.failing_night = "2021-03-02"
        payload = self.collect(client)

        pagination = payload["provider_sync"]["pagination"]
        self.assertFalse(pagination["sleep"]["complete"])
        self.assertNotIn("sleep", payload)
        self.assertEqual([error["source"] for error in payload["errors"]], ["sleep"])
        self.assertTrue(pagination["hrv"]["complete"])
        self.assertIn("resting_hr", payload)


class _Manager:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    @contextmanager
    def unit_of_work(self):
        yield self.db
        self.db.commit()


class _Coordination:
    def __init__(self, free: bool = True) -> None:
        self.free = free
        self.released = 0

    @contextmanager
    def operation(self):
        yield

    def acquire(self, *, timeout: float | None = None) -> bool:
        return self.free

    def release(self) -> None:
        self.released += 1


class _Cursors:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, str]] = []

    def update_cursor(
        self, provider: str, stream: str, cursor: str, high_water_mark: Any = None
    ) -> None:
        self.writes.append((provider, stream, cursor))


class _Reader:
    def __init__(self, client: Any) -> None:
        self.client = client

    def fetch_wellness_history(self, start: date, end: date) -> dict[str, Any]:
        return collect_wellness_history(
            self.client, start, end, external_call=_external_call, redact=str
        )


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = sqlite3.connect(Path(temporary.name) / "wellness.db")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        initialize_schema(self.db)
        self.db.commit()
        self.writer = GarminSnapshotWriter(
            KeyValueRepository(lambda: NOW), lambda: ZONE
        )
        self.cursors = _Cursors()
        self.coordination = _Coordination()

    def service(self, client: Any) -> GarminWellnessHistoryService:
        return GarminWellnessHistoryService(
            reader=_Reader(client),
            database_manager=_Manager(self.db),
            snapshot_writer=self.writer,
            sync_state_repository=self.cursors,
            coordination=self.coordination,
            utc_now=lambda: NOW,
            configured=lambda: True,
        )

    def store(self, sections: dict[str, Any]) -> None:
        self.writer.write_refresh(
            self.db,
            fetched_at="2026-10-01T08:00:00+00:00",
            sections=sections,
            view={},
            windows={},
            allowed=frozenset(sections),
        )
        self.db.commit()

    def record_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0]

    def metrics(self, day: str) -> dict[str, float]:
        return {
            row["metric"]: row["value"]
            for row in self.db.execute(
                "SELECT metric, value FROM observations WHERE provider = 'garmin' "
                "AND observed_on = ? AND state = 'active'",
                (day,),
            )
        }

    def test_backfill_adds_night_values_resting_hr_hrv_and_weight(self) -> None:
        result = self.service(SdkClient()).backfill(2, END)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["start"], "2021-03-01")
        metrics = self.metrics("2021-03-01")
        for metric, value in (
            ("spo2", 95.0),
            ("spo2_lowest", 84.0),
            ("respiration_rate", 14.0),
            ("sleeping_hr", 48.0),
            ("resting_hr", 46.0),
            ("hrv_rmssd", 57.0),
            ("weight", 90.0),
        ):
            with self.subTest(metric=metric):
                self.assertEqual(metrics.get(metric), value)
        self.assertEqual(
            self.cursors.writes, [("garmin", "wellness_history", "2021-03-01")]
        )
        self.assertEqual(self.coordination.released, 1)

    def test_stored_days_stay_untouched_and_nothing_is_deleted(self) -> None:
        stored_summary = {
            "calendarDate": "2021-03-01",
            "heartRate": {"restingValue": 50},
        }
        stored_resting = {"calendarDate": "2021-03-01", "restingHeartRate": 52}
        stored_night = {
            "calendarDate": "2021-03-02",
            "dailySleepDTO": _night_dto("2021-03-02", spo2=91.0),
        }
        self.store(
            {
                "daily_stats": [stored_summary],
                "resting_hr": [stored_resting],
                "sleep": [stored_night],
            }
        )
        before = self.record_count()

        self.service(SdkClient()).backfill(2, END)

        self.assertGreaterEqual(self.record_count(), before)
        self.assertEqual(
            garmin_store.read_item(self.db, "daily_stats", "2021-03-01"),
            stored_summary,
        )
        self.assertEqual(
            garmin_store.read_item(self.db, "resting_hr", "2021-03-01"),
            stored_resting,
        )
        # A stored night that already has night values keeps them.
        self.assertEqual(
            garmin_store.read_item(self.db, "sleep", "2021-03-02"), stored_night
        )
        self.assertEqual(self.metrics("2021-03-02")["spo2"], 91.0)

    def test_a_stored_night_without_night_values_gains_the_full_night(self) -> None:
        self.store(
            {
                "sleep": [
                    {
                        "calendarDate": "2021-03-01",
                        "values": {"totalSleepTimeInSeconds": 25_000},
                    }
                ]
            }
        )

        self.service(SdkClient()).backfill(2, END)

        stored = garmin_store.read_item(self.db, "sleep", "2021-03-01")
        self.assertTrue(has_night_values(stored))
        self.assertEqual(self.metrics("2021-03-01")["spo2"], 95.0)

    def test_weigh_ins_merge_into_the_stored_envelope(self) -> None:
        recent = {
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2026-11-04",
                    "latestWeight": {
                        "samplePk": 99,
                        "calendarDate": "2026-11-04",
                        "weight": 88_000.0,
                        "timestampGMT": 1_793_779_200_000,
                    },
                }
            ]
        }
        self.store({"weight": [recent]})

        self.service(SdkClient()).backfill(2, END)

        self.assertEqual(self.metrics("2026-11-04")["weight"], 88.0)
        self.assertEqual(self.metrics("2021-03-01")["weight"], 90.0)

    def test_a_partial_window_keeps_the_cursor(self) -> None:
        client = SdkClient()
        client.failing_night = "2021-03-02"

        result = self.service(client).backfill(2, END)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.cursors.writes, [])
        # The other sources of the window are still stored.
        self.assertEqual(self.metrics("2021-03-01")["resting_hr"], 46.0)

    def test_a_busy_garmin_sync_fails_the_chunk_without_a_read(self) -> None:
        self.coordination.free = False
        client = SdkClient()

        with self.assertRaises(AppError) as raised:
            self.service(client).backfill(2, END)

        self.assertEqual(raised.exception.reason, "provider_busy")
        self.assertEqual(client.calls, [])


class _State:
    def __init__(self) -> None:
        self.cursors: list[tuple[str, str, str]] = []

    def update_cursor(self, provider: str, stream: str, cursor: str, *_: Any) -> None:
        self.cursors.append((provider, stream, cursor))

    def sync_period(self, *_: Any) -> int:
        return 30


class _Queue:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def enqueue(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))

    def backfill_continued(
        self, provider: str, end_date: str, created_since: str, job_type: str
    ) -> bool:
        return any(
            args[:2] == (provider, job_type) and args[2]["end_date"] == end_date
            for args, _ in self.calls
        )


class _Wellness:
    def __init__(self, records: int = 3) -> None:
        self.records = records
        self.calls: list[tuple[int, date]] = []

    def backfill(self, days: int, end: date) -> dict[str, Any]:
        self.calls.append((days, end))
        return {"status": "ok", "window_records": self.records}


class _Unused:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected call {name}")


class ExecutorTests(unittest.TestCase):
    def owner(self, wellness: Any) -> tuple[GarminSyncJobOwner, HistoricalSyncJobOwner]:
        self.state = _State()
        self.queue = _Queue()
        historical = HistoricalSyncJobOwner(
            sync_state_repository=self.state,
            queue_service=self.queue,
            local_now=lambda: datetime(2026, 11, 6, 12, tzinfo=UTC),
            sync_period_defaults={},
            all_sync_days=-1,
            sync_chunk_days=90,
            sync_earliest_date=date(2020, 1, 1),
        )
        owner = GarminSyncJobOwner(
            historical_sync=historical,
            garmin_sync_service=_Unused(),
            morning_body_battery_service=_Unused(),
            garmin_fixture_loader=_Unused(),
            all_sync_days=-1,
            wellness_history_service=wellness,
        )
        return owner, historical

    def test_the_first_chunk_ends_below_the_automatic_window_and_continues(
        self,
    ) -> None:
        wellness = _Wellness()
        owner, historical = self.owner(wellness)
        job = {"id": "job-1", "type": "wellness_backfill", "provider": "garmin"}

        result = owner.execute(job, {"days": 90}, "startup")
        historical.queue_next(job, result, "completed")

        self.assertEqual(wellness.calls, [(90, date(2026, 11, 4))])
        self.assertEqual(result["historical_next_end"], "2026-08-06")
        args, kwargs = self.queue.calls[0]
        self.assertEqual(args[:2], ("garmin", "wellness_backfill"))
        self.assertEqual(args[2]["end_date"], "2026-08-06")
        self.assertEqual(kwargs["requested_by"], "backfill")

    def test_two_empty_chunks_park_the_wellness_cursor_at_the_floor(self) -> None:
        owner, _ = self.owner(_Wellness(records=0))
        job = {"id": "job-2", "type": "wellness_backfill", "provider": "garmin"}

        result = owner.execute(
            job, {"days": 90, "end_date": "2023-01-01", "empty_chunks": 1}, "backfill"
        )

        self.assertIsNone(result["historical_next_end"])
        self.assertEqual(
            self.state.cursors, [("garmin", "wellness_history", "2020-01-01")]
        )

    def test_a_window_below_the_floor_ends_without_a_read(self) -> None:
        wellness = _Wellness()
        owner, _ = self.owner(wellness)
        job = {"id": "job-3", "type": "wellness_backfill", "provider": "garmin"}

        result = owner.execute(job, {"end_date": "2019-12-31"}, "backfill")

        self.assertEqual(result["historical_next_end"], None)
        self.assertEqual(wellness.calls, [])
        self.assertEqual(
            self.state.cursors, [("garmin", "wellness_history", "2020-01-01")]
        )


if __name__ == "__main__":
    unittest.main()
