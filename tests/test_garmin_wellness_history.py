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
from typing import Any, cast
from zoneinfo import ZoneInfo

from support import FakeManager

from backend.db import garmin_store
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.providers.garmin_wellness_history import (
    WellnessHistoryHooks,
    WellnessSourcePaused,
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


def _skippable(error: BaseException) -> bool:
    return isinstance(error, ValueError)


HOOKS = WellnessHistoryHooks(skippable=_skippable)


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


def _bare_night(day: str, seconds: int) -> dict[str, Any]:
    return {"calendarDate": day, "values": {"totalSleepTimeInSeconds": seconds}}


def _battery_report(
    day: str, charged: int = 60, drained: int = 55, samples: int = 3
) -> dict[str, Any]:
    """One Body Battery report row shaped after the range answer."""
    midday = int(datetime.fromisoformat(f"{day}T12:00:00+00:00").timestamp() * 1000)
    return {
        "date": day,
        "charged": charged,
        "drained": drained,
        "bodyBatteryValuesArray": [
            [midday + index * 180_000, 40 + index] for index in range(samples)
        ],
    }


class SdkClient:
    """The SDK shape: the sleep range carries statistics only."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.failing_night: str | None = None
        self.night_error: Exception = ValueError("night unreadable")

    def get_sleep_daily(self, start: str, end: str) -> list[dict[str, Any]]:
        self.calls.append(("get_sleep_daily", (start, end)))
        return [
            _bare_night("2021-03-01", 1),
            _bare_night("2021-03-02", 2),
            # Outside the window: never read again or stored.
            _bare_night("2021-02-27", 3),
        ]

    def get_sleep_data(self, day: str) -> dict[str, Any]:
        self.calls.append(("get_sleep_data", (day,)))
        if day == self.failing_night:
            raise self.night_error
        return {
            "dailySleepDTO": _night_dto(day),
            "wellnessEpochSPO2DataDTOList": [{"spo2Reading": 93}],
            "restingHeartRate": 45,
        }

    def get_hrv_data_range(self, start: str, end: str) -> Any:
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

    def get_body_battery(self, start: str, end: str) -> list[dict[str, Any]]:
        self.calls.append(("get_body_battery", (start, end)))
        return [
            _battery_report("2021-03-01", charged=61, drained=52),
            _battery_report("2021-03-02", charged=47, drained=44),
            # Outside the window: never stored.
            _battery_report("2021-02-27"),
        ]

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


def _night_reads(client: SdkClient) -> list[tuple[Any, ...]]:
    return [args for name, args in client.calls if name == "get_sleep_data"]


class CollectorTests(unittest.TestCase):
    def collect(
        self, client: Any, hooks: WellnessHistoryHooks = HOOKS
    ) -> dict[str, Any]:
        return collect_wellness_history(
            client, START, END, external_call=_external_call, hooks=hooks
        )

    def test_sdk_statistics_nights_are_read_as_full_night_elements(self) -> None:
        client = SdkClient()
        payload = self.collect(client)

        self.assertEqual(_night_reads(client), [("2021-03-01",), ("2021-03-02",)])
        self.assertEqual(
            payload["sleep"],
            [
                {"calendarDate": day, "dailySleepDTO": _night_dto(day)}
                for day in ("2021-03-01", "2021-03-02")
            ],
        )
        self.assertEqual(payload["skipped_sources"], [])

    def test_personal_range_nights_with_night_values_need_no_night_read(self) -> None:
        client = PersonalClient()
        payload = self.collect(client)

        self.assertEqual(_night_reads(client), [])
        self.assertEqual(len(payload["sleep"]), 2)

    def test_nights_with_stored_night_values_are_not_read_again(self) -> None:
        client = SdkClient()
        self.collect(
            client,
            WellnessHistoryHooks(
                skippable=_skippable, needs_night=lambda day: day != "2021-03-01"
            ),
        )

        self.assertEqual(_night_reads(client), [("2021-03-02",)])

    def test_resting_heart_rate_comes_from_the_daily_summaries(self) -> None:
        payload = self.collect(SdkClient())

        self.assertEqual(
            payload["resting_hr"],
            [{"calendarDate": "2021-03-01", "restingHeartRate": 46.0}],
        )
        self.assertEqual(
            [row["calendarDate"] for row in payload["hrv"]], ["2021-03-01"]
        )

    def test_daily_summaries_and_body_battery_are_read_in_ranges_of_at_most_31_days(
        self,
    ) -> None:
        client = SdkClient()
        collect_wellness_history(
            client,
            date(2021, 1, 1),
            date(2021, 3, 31),
            external_call=_external_call,
            hooks=HOOKS,
        )

        for call in ("get_daily_summaries", "get_body_battery"):
            with self.subTest(call=call):
                self.assertEqual(
                    [args for name, args in client.calls if name == call],
                    [
                        ("2021-01-01", "2021-01-31"),
                        ("2021-02-01", "2021-03-03"),
                        ("2021-03-04", "2021-03-31"),
                    ],
                )

    def test_body_battery_keeps_only_reports_inside_the_window(self) -> None:
        payload = self.collect(SdkClient())

        self.assertEqual(
            [row["date"] for row in payload["body_battery"]],
            ["2021-03-01", "2021-03-02"],
        )
        self.assertEqual(
            payload["provider_sync"]["pagination"]["body_battery"], {"records": 2}
        )

    def test_a_range_without_weigh_ins_is_no_record(self) -> None:
        client = SdkClient()
        client.get_weigh_ins = lambda _start, _end: {  # type: ignore[method-assign,assignment]
            "dailyWeightSummaries": [],
            "totalAverage": {"weight": None},
        }
        payload = self.collect(client)

        self.assertEqual(payload["weight"], [])
        self.assertEqual(payload["provider_sync"]["pagination"]["weight"]["records"], 0)

    def test_a_skippable_night_failure_keeps_its_range_row(self) -> None:
        client = SdkClient()
        client.failing_night = "2021-03-02"
        payload = self.collect(client)

        self.assertEqual(payload["sleep"][1], _bare_night("2021-03-02", 2))
        self.assertTrue(has_night_values(payload["sleep"][0]))
        self.assertEqual(payload["skipped_sources"], [])

    def test_a_skippable_source_failure_skips_only_that_source(self) -> None:
        client = SdkClient()
        client.get_hrv_data_range = lambda *_: "not a range"  # type: ignore[method-assign]
        failures: list[str] = []
        payload = self.collect(
            client,
            WellnessHistoryHooks(
                skippable=_skippable,
                capability_failure=lambda source, _error: failures.append(source),
            ),
        )

        self.assertEqual(payload["skipped_sources"], ["hrv"])
        self.assertNotIn("hrv", payload)
        # A skipped source leaves the shared capability pause state alone.
        self.assertEqual(failures, [])
        self.assertIn("resting_hr", payload)

    def test_a_retryable_failure_ends_the_read(self) -> None:
        client = SdkClient()
        client.failing_night = "2021-03-02"
        client.night_error = RuntimeError("rate limited")

        with self.assertRaises(RuntimeError):
            self.collect(client)

    def test_a_retryable_source_failure_counts_toward_the_pause(self) -> None:
        client = SdkClient()

        def fail(*_: Any) -> Any:
            raise RuntimeError("rate limited")

        client.get_hrv_data_range = fail  # type: ignore[method-assign,assignment]
        failures: list[str] = []

        with self.assertRaises(RuntimeError):
            self.collect(
                client,
                WellnessHistoryHooks(
                    skippable=_skippable,
                    capability_failure=lambda source, _error: failures.append(source),
                ),
            )
        self.assertEqual(failures, ["hrv"])

    def test_a_failing_body_battery_read_is_skipped_and_counted(self) -> None:
        client = SdkClient()

        def fail(*_: Any) -> Any:
            raise RuntimeError("server error")

        client.get_body_battery = fail  # type: ignore[method-assign,assignment]
        failures: list[str] = []

        payload = self.collect(
            client,
            WellnessHistoryHooks(
                skippable=_skippable,
                capability_failure=lambda source, _error: failures.append(source),
            ),
        )

        self.assertEqual(failures, ["body_battery"])
        self.assertEqual(payload["skipped_sources"], ["body_battery"])
        self.assertNotIn("body_battery", payload)
        self.assertIn("sleep", payload)
        self.assertIn("weight", payload)

    def test_a_paused_body_battery_is_skipped_without_a_call(self) -> None:
        client = SdkClient()

        payload = self.collect(
            client,
            WellnessHistoryHooks(
                skippable=_skippable,
                capability_allowed=lambda source: source != "body_battery",
            ),
        )

        self.assertEqual(payload["skipped_sources"], ["body_battery"])
        self.assertIn("sleep", payload)

    def test_a_paused_source_ends_the_read_before_any_call(self) -> None:
        client = SdkClient()

        with self.assertRaises(WellnessSourcePaused):
            self.collect(
                client,
                WellnessHistoryHooks(
                    skippable=_skippable,
                    capability_allowed=lambda source: source != "sleep",
                ),
            )
        self.assertEqual(client.calls, [])


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
    def __init__(self, client: Any, paused: bool = False) -> None:
        self.client = client
        self.paused = paused

    def fetch_wellness_history(
        self, start: date, end: date, *, needs_night: Any
    ) -> dict[str, Any]:
        if self.paused:
            raise WellnessSourcePaused("sleep")
        return collect_wellness_history(
            self.client,
            start,
            end,
            external_call=_external_call,
            hooks=WellnessHistoryHooks(skippable=_skippable, needs_night=needs_night),
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

    def service(
        self, client: Any, paused: bool = False
    ) -> GarminWellnessHistoryService:
        return GarminWellnessHistoryService(
            reader=_Reader(client, paused),
            database_manager=FakeManager(self.db),
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

    def weight_rows(self) -> list[tuple[Any, ...]]:
        return [
            tuple(row)
            for row in self.db.execute(
                "SELECT id, payload FROM provider_records "
                "WHERE source_record_id LIKE 'weight%' ORDER BY id"
            )
        ]

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

    def test_backfill_stores_body_battery_history_and_its_totals(self) -> None:
        result = self.service(SdkClient()).backfill(2, END)

        self.assertEqual(result["written"]["body_battery"], 2)
        stored = garmin_store.read_item(self.db, "body_battery", "2021-03-01")
        self.assertEqual(stored, _battery_report("2021-03-01", charged=61, drained=52))
        self.assertIsNone(garmin_store.read_item(self.db, "body_battery", "2021-02-27"))
        metrics = self.metrics("2021-03-01")
        self.assertEqual(metrics["body_battery_charged"], 61.0)
        self.assertEqual(metrics["body_battery_drained"], 52.0)
        self.assertEqual(self.metrics("2021-03-02")["body_battery_charged"], 47.0)

    def test_a_repeated_backfill_run_writes_no_body_battery_again(self) -> None:
        self.service(SdkClient()).backfill(2, END)
        records = self.record_count()
        observations = self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[
            0
        ]

        result = self.service(SdkClient()).backfill(2, END)

        self.assertNotIn("body_battery", result["written"])
        self.assertEqual(self.record_count(), records)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            observations,
        )

    def test_a_stored_partial_body_battery_report_gets_the_completed_one(self) -> None:
        self.store({"body_battery": [_battery_report("2021-03-01", 5, 3, samples=1)]})
        self.assertEqual(self.metrics("2021-03-01")["body_battery_charged"], 5.0)

        self.service(SdkClient()).backfill(2, END)

        self.assertEqual(self.metrics("2021-03-01")["body_battery_charged"], 61.0)
        self.assertEqual(self.metrics("2021-03-01")["body_battery_drained"], 52.0)
        active = self.db.execute(
            "SELECT COUNT(*) FROM observations WHERE metric = 'body_battery_charged' "
            "AND observed_on = '2021-03-01' AND state = 'active'"
        ).fetchone()[0]
        self.assertEqual(active, 1)

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
        client = SdkClient()

        self.service(client).backfill(2, END)

        self.assertGreaterEqual(self.record_count(), before)
        self.assertEqual(
            garmin_store.read_item(self.db, "daily_stats", "2021-03-01"),
            stored_summary,
        )
        self.assertEqual(
            garmin_store.read_item(self.db, "resting_hr", "2021-03-01"),
            stored_resting,
        )
        # A stored night that already has night values keeps them, unread.
        self.assertEqual(
            garmin_store.read_item(self.db, "sleep", "2021-03-02"), stored_night
        )
        self.assertEqual(self.metrics("2021-03-02")["spo2"], 91.0)
        self.assertEqual(_night_reads(client), [("2021-03-01",)])

    def test_a_stored_night_without_night_values_gains_the_full_night(self) -> None:
        self.store({"sleep": [_bare_night("2021-03-01", 25_000)]})

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

    def test_weigh_ins_already_stored_rewrite_nothing(self) -> None:
        self.service(SdkClient()).backfill(2, END)
        stored = self.weight_rows()

        result = self.service(SdkClient()).backfill(2, END)

        self.assertNotIn("weight", result["written"])
        self.assertEqual(self.weight_rows(), stored)

    def test_a_retryable_failure_fails_the_chunk_and_keeps_the_cursor(self) -> None:
        client = SdkClient()
        client.failing_night = "2021-03-02"
        client.night_error = RuntimeError("rate limited")
        before = self.record_count()

        with self.assertRaises(RuntimeError):
            self.service(client).backfill(2, END)

        self.assertEqual(self.cursors.writes, [])
        self.assertEqual(self.record_count(), before)
        self.assertEqual(self.coordination.released, 1)

    def test_a_paused_source_fails_the_chunk_as_rate_limited(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service(SdkClient(), paused=True).backfill(2, END)

        self.assertEqual(raised.exception.reason, "rate_limited")
        self.assertEqual(self.cursors.writes, [])

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
        self,
        provider: str,
        end_date: str,
        created_since: str,
        job_type: str,
        exclude_job_id: str = "",
    ) -> bool:
        return any(
            args[:2] == (provider, job_type) and args[2]["end_date"] == end_date
            for args, _ in self.calls
        )


class _Wellness:
    def __init__(self, records: int = 3, available: bool = True) -> None:
        self.records = records
        self.is_available = available
        self.calls: list[tuple[int, date]] = []

    def available(self) -> bool:
        return self.is_available

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
            sync_state_repository=cast(Any, self.state),
            queue_service=cast(Any, self.queue),
            local_now=lambda: datetime(2026, 11, 6, 12, tzinfo=UTC),
            sync_period_defaults={},
            all_sync_days=-1,
            sync_chunk_days=90,
            sync_earliest_date=date(2020, 1, 1),
        )
        owner = GarminSyncJobOwner(
            historical_sync=historical,
            garmin_sync_service=cast(Any, _Unused()),
            morning_body_battery_service=cast(Any, _Unused()),
            garmin_fixture_loader=cast(Any, _Unused()),
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

    def test_fixture_mode_skips_without_cursor_or_continuation(self) -> None:
        wellness = _Wellness(available=False)
        owner, historical = self.owner(wellness)
        job = {"id": "job-4", "type": "wellness_backfill", "provider": "garmin"}

        result = owner.execute(job, {"days": 90}, "startup")
        historical.queue_next(job, result, "completed")

        self.assertEqual(wellness.calls, [])
        self.assertEqual(self.state.cursors, [])
        self.assertEqual(self.queue.calls, [])

    def test_a_window_below_the_floor_ends_without_a_read(self) -> None:
        wellness = _Wellness()
        owner, _ = self.owner(wellness)
        job = {"id": "job-3", "type": "wellness_backfill", "provider": "garmin"}

        result = owner.execute(job, {"end_date": "2019-12-31"}, "backfill")

        self.assertIsNone(result["historical_next_end"])
        self.assertEqual(wellness.calls, [])
        self.assertEqual(
            self.state.cursors, [("garmin", "wellness_history", "2020-01-01")]
        )


if __name__ == "__main__":
    unittest.main()
