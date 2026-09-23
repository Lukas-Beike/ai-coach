from __future__ import annotations

import threading
import unittest
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

from backend.config import Config
from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers.intervals import IntervalsApiClient
from backend.sync.intervals import IntervalsSnapshotReader


class FakeSyncStateRepository:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot

    def latest_snapshot(self):
        return self.snapshot


class FakeIntervalsApi:
    def __init__(self, *, on_collection=None, rows=None):
        self.calls = []
        self.on_collection = on_collection
        self.rows = rows or {}
        self.pagination = {}

    def get(self, path, params=None, *, cancel_event=None):
        self.calls.append(("get", path, params))
        return {
            "id": "athlete",
            "name": "Synthetic Athlete",
            "provider_only": "retained",
        }

    def get_paged_collection(
        self, path, params, collection, page_size=500, cancel_event=None
    ):
        self.calls.append((collection, path, dict(params or {})))
        if self.on_collection is not None:
            self.on_collection(collection)
        return list(self.rows.get(collection, []))


def test_config() -> Config:
    return Config(
        port=8090,
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_model="test",
        gemini_api_key="",
        gemini_model="test",
        ai_provider="openai",
        intervals_api_key="test-key",
        intervals_athlete_id="athlete/1",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="",
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="test-password-long-enough",
        secure_cookies=False,
        data_retention_days=30,
    )


def make_reader(api, snapshot=None, *, earliest=date(2024, 1, 1), chunk_days=2):
    return IntervalsSnapshotReader(
        config=test_config(),
        api_client=api,
        sync_state_repository=FakeSyncStateRepository(snapshot),
        local_now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        utc_now=lambda: "2026-01-01T00:00:00+00:00",
        earliest_date=earliest,
        chunk_days=chunk_days,
        all_sync_days=-1,
        calendar_history_days=35,
        calendar_future_days=35,
    )


class IntervalsSnapshotReaderTests(unittest.TestCase):
    def test_incremental_merge_and_full_sync_behavior(self):
        activities = [
            {"id": str(index), "name": f"Activity {index}", "private": "raw"}
            for index in range(505)
        ]
        old_snapshot = {
            "recent_activities": [{"id": "older", "name": "Older"}],
            "recent_wellness": [{"id": "older-day", "ctl": 10}],
            "raw_provider_data": {
                "activities": [{"id": "older", "private": "old raw"}],
                "wellness": [{"id": "older-day", "private": "old raw"}],
            },
        }
        api = FakeIntervalsApi(
            rows={
                "activities": activities,
                "wellness": [{"id": "today", "private": "raw"}],
            }
        )
        reader = make_reader(api, old_snapshot)

        incremental = reader.fetch_snapshot(activity_days=3, end_date=date(2024, 1, 10))

        self.assertTrue(incremental["incremental"])
        self.assertEqual(incremental["incremental_window_days"], 3)
        self.assertEqual(len(incremental["recent_activities"]), 500)
        self.assertEqual(incremental["recent_activities"][0]["id"], "0")
        self.assertEqual(
            incremental["raw_provider_data"]["activities"][-1]["id"], "older"
        )
        self.assertEqual(len(incremental["raw_provider_data"]["activities"]), 506)
        self.assertEqual(
            incremental["raw_provider_data"]["activities"][0]["private"], "raw"
        )

        full = reader.fetch_snapshot(activity_days=-1, end_date=date(2024, 1, 10))

        self.assertNotIn("incremental", full)
        self.assertEqual(len(full["recent_activities"]), 505)
        self.assertEqual(len(full["raw_provider_data"]["activities"]), 505)

    def test_historical_date_windows_and_calendar_window(self):
        api = FakeIntervalsApi()
        reader = make_reader(api)

        reader.fetch_snapshot(activity_days=5, end_date=date(2024, 1, 10))

        activity_windows = [
            params
            for collection, _path, params in api.calls
            if collection == "activities"
        ]
        self.assertEqual(
            activity_windows,
            [
                {"oldest": "2024-01-06", "newest": "2024-01-07"},
                {"oldest": "2024-01-08", "newest": "2024-01-09"},
                {"oldest": "2024-01-10", "newest": "2024-01-10"},
            ],
        )
        events = next(call for call in api.calls if call[0] == "events")
        self.assertEqual(events[2], {"oldest": "2023-12-06", "newest": "2024-02-14"})

    def test_full_sync_starts_at_earliest_date_and_keeps_raw_provider_rows(self):
        request_urls = []

        def request(method, url, **_kwargs):
            parsed = urlparse(url)
            request_urls.append((method, parsed.path, parse_qs(parsed.query)))
            if parsed.path.endswith("/athlete/athlete%2F1"):
                return {"id": "athlete", "name": "Athlete", "private": "athlete raw"}
            if parsed.path.endswith("/activities"):
                return [{"id": "a1", "name": "Activity", "private": "activity raw"}]
            if parsed.path.endswith("/wellness"):
                return [{"id": "w1", "ctl": 42, "private": "wellness raw"}]
            return [{"id": "e1", "name": "Event", "private": "event raw"}]

        api = IntervalsApiClient(api_key="test-key", request=request)
        reader = make_reader(api, earliest=date(2024, 1, 1), chunk_days=2)

        snapshot = reader.fetch_snapshot(activity_days=-1, end_date=date(2024, 1, 3))

        activity_calls = [
            call for call in request_urls if call[1].endswith("/activities")
        ]
        self.assertEqual(len(activity_calls), 2)
        self.assertEqual(activity_calls[0][2]["oldest"], ["2024-01-01"])
        self.assertEqual(activity_calls[0][2]["newest"], ["2024-01-02"])
        self.assertEqual(activity_calls[1][2]["oldest"], ["2024-01-03"])
        self.assertEqual(
            snapshot["raw_provider_data"]["activities"][0]["private"], "activity raw"
        )
        self.assertEqual(
            snapshot["raw_provider_data"]["wellness"][0]["private"], "wellness raw"
        )
        self.assertEqual(
            snapshot["raw_provider_data"]["upcoming_calendar"][0]["private"],
            "event raw",
        )
        self.assertNotIn("private", snapshot["recent_activities"][0])
        self.assertEqual(
            snapshot["provider_sync"]["pagination"]["activities"]["records"], 2
        )

    def test_cancellation_before_io_and_between_provider_steps(self):
        cancelled = threading.Event()
        cancelled.set()
        api = FakeIntervalsApi()
        reader = make_reader(api)

        with self.assertRaises(AppError) as before_io:
            reader.fetch_snapshot(activity_days=2, cancel_event=cancelled)
        self.assertEqual(before_io.exception.status, 499)
        self.assertEqual(before_io.exception.message, COACH_ABORTED_ERROR)
        self.assertEqual(before_io.exception.reason, "chat_cancelled")
        self.assertEqual(api.calls, [])

        cancelled.clear()

        def cancel_after_activities(collection):
            if collection == "activities":
                cancelled.set()

        api = FakeIntervalsApi(on_collection=cancel_after_activities)
        reader = make_reader(api)
        with self.assertRaises(AppError) as between_steps:
            reader.fetch_snapshot(activity_days=2, cancel_event=cancelled)
        self.assertEqual(between_steps.exception.reason, "chat_cancelled")
        self.assertEqual([call[0] for call in api.calls], ["activities"])

    def test_performance_refresh_reads_only_athlete_and_ninety_day_wellness(self):
        api = FakeIntervalsApi(rows={"performance_wellness": [{"id": "w1", "ctl": 5}]})
        reader = make_reader(api)
        existing = {
            "recent_activities": [{"id": "a1", "name": "Existing activity"}],
            "upcoming_calendar": [{"id": "e1", "name": "Existing event"}],
        }

        snapshot = reader.fetch_performance_snapshot(existing)

        self.assertEqual(
            [call[0] for call in api.calls], ["get", "performance_wellness"]
        )
        self.assertEqual(
            api.calls[1][2], {"oldest": "2025-10-03", "newest": "2026-01-01"}
        )
        self.assertEqual(snapshot["recent_activities"][0]["id"], "a1")
        self.assertEqual(snapshot["upcoming_calendar"][0]["id"], "e1")
        self.assertEqual(set(snapshot["raw_provider_data"]), {"athlete", "wellness"})

    def test_provider_error_is_passed_through_unchanged(self):
        error = RuntimeError("provider failure")
        api = FakeIntervalsApi()
        api.get_paged_collection = lambda *args, **kwargs: (_ for _ in ()).throw(error)
        reader = make_reader(api)

        with self.assertRaises(RuntimeError) as raised:
            reader.fetch_snapshot(activity_days=2)

        self.assertIs(raised.exception, error)


if __name__ == "__main__":
    unittest.main()
