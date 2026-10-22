from __future__ import annotations

import threading
import unittest
from datetime import UTC, date, datetime, timedelta
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
        if path.endswith("/activity-power-curves"):
            return self.rows.get("power_curves", {"secs": [], "curves": []})
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
        local_now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
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

    def test_short_window_keeps_sync_period_wellness_in_day_order(self):
        start = date(2025, 9, 1)
        stored = [
            {"id": (start + timedelta(days=index)).isoformat(), "ctl": index}
            for index in range(100)
        ]
        latest = (start + timedelta(days=99)).isoformat()
        today = (start + timedelta(days=100)).isoformat()
        api = FakeIntervalsApi(
            rows={"wellness": [{"id": latest, "ctl": 99}, {"id": today, "ctl": 100}]}
        )
        reader = make_reader(api, {"recent_wellness": stored})

        narrow = reader.fetch_snapshot(activity_days=2)
        kept = reader.fetch_snapshot(activity_days=2, retain_days=84)
        everything = reader.fetch_snapshot(activity_days=2, retain_days=-1)

        self.assertEqual(len(narrow["recent_wellness"]), 43)
        self.assertEqual(len(kept["recent_wellness"]), 85)
        self.assertEqual(len(everything["recent_wellness"]), 101)
        for snapshot in (narrow, kept, everything):
            days = [row["id"] for row in snapshot["recent_wellness"]]
            self.assertEqual(days, sorted(days))
            self.assertEqual(days[-1], today)

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

    def test_historical_chunk_on_stored_history_skips_refresh_only_reads(self):
        stored = {
            "recent_activities": [{"id": "older", "name": "Older"}],
            "cycling_power_profile": {"points": [{"watts": 300}]},
            "raw_provider_data": {
                "athlete": {"id": "athlete", "name": "Stored"},
                "activities": [{"id": "older"}],
                "wellness": [],
            },
        }
        api = FakeIntervalsApi(
            rows={
                "activities": [{"id": "a1"}, {"id": "older"}],
                "wellness": [{"id": "w1"}],
            }
        )
        reader = make_reader(api, stored)

        snapshot = reader.fetch_snapshot(activity_days=2, end_date=date(2024, 1, 10))

        self.assertEqual([call for call in api.calls if call[0] == "get"], [])
        self.assertEqual(
            snapshot["cycling_power_profile"], {"points": [{"watts": 300}]}
        )
        # The count covers this window's fetch, not the merged history.
        self.assertEqual(snapshot["provider_sync"]["window_records"], 3)
        self.assertGreater(len(snapshot["raw_provider_data"]["activities"]), 0)

    def test_refresh_and_first_historical_chunk_still_read_athlete_data(self):
        stored = {"recent_activities": [{"id": "older"}]}
        for existing, end_date in ((stored, None), (None, date(2024, 1, 10))):
            with self.subTest(end_date=end_date):
                api = FakeIntervalsApi()
                reader = make_reader(api, existing)

                snapshot = reader.fetch_snapshot(activity_days=2, end_date=end_date)

                paths = [call[1] for call in api.calls if call[0] == "get"]
                self.assertEqual(
                    paths,
                    [
                        "/athlete/athlete%2F1",
                        "/athlete/athlete%2F1/activity-power-curves",
                    ],
                )
                self.assertEqual(snapshot["provider_sync"]["window_records"], 0)

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

    def test_performance_refresh_reads_athlete_wellness_and_power_curves(self):
        api = FakeIntervalsApi(rows={"performance_wellness": [{"id": "w1", "ctl": 5}]})
        reader = make_reader(api)
        existing = {
            "recent_activities": [{"id": "a1", "name": "Existing activity"}],
            "upcoming_calendar": [{"id": "e1", "name": "Existing event"}],
        }

        snapshot = reader.fetch_performance_snapshot(existing)

        self.assertEqual(
            [call[0] for call in api.calls], ["get", "performance_wellness", "get"]
        )
        self.assertEqual(
            api.calls[1][2], {"oldest": "2025-10-03", "newest": "2026-01-01"}
        )
        self.assertEqual(snapshot["recent_activities"][0]["id"], "a1")
        self.assertEqual(snapshot["upcoming_calendar"][0]["id"], "e1")
        self.assertEqual(set(snapshot["raw_provider_data"]), {"athlete", "wellness"})

    def test_analysis_wellness_refresh_skips_power_curves(self):
        api = FakeIntervalsApi(rows={"performance_wellness": [{"id": "w1", "ctl": 5}]})
        reader = make_reader(api)

        snapshot = reader.fetch_performance_snapshot(
            {"cycling_power_profile": {"status": "ok"}},
            include_power_profile=False,
        )

        self.assertEqual(
            [call[0] for call in api.calls], ["get", "performance_wellness"]
        )
        self.assertNotIn("cycling_power_profile", snapshot)

    def test_power_curves_sync_combines_rides_and_retains_on_optional_failure(self):
        api = FakeIntervalsApi(
            rows={
                "power_curves": {
                    "secs": [5, 60, 3600],
                    "curves": [
                        {
                            "id": "outdoor",
                            "start_date_local": "2025-12-30",
                            "watts": [600, 400, None],
                        },
                        {
                            "id": "indoor",
                            "start_date_local": "2025-12-31",
                            "watts": [550, 420, 250],
                        },
                        {
                            "id": "future",
                            "start_date_local": "2026-01-02",
                            "watts": [900, 800, 700],
                        },
                    ],
                }
            }
        )
        reader = make_reader(api)
        snapshot = reader.fetch_snapshot(activity_days=1)
        profile = snapshot["cycling_power_profile"]
        self.assertEqual([p["watts"] for p in profile["points"]], [600, 420, 250])
        self.assertEqual(
            api.calls[-1][2],
            {
                "oldest": "2025-10-04",
                "newest": "2026-01-01",
                "type": "Ride",
                "secs": "5,60,300,1200,3600",
            },
        )
        api.rows["power_curves"] = "invalid"
        retained = reader._cycling_power_profile("athlete", date(2026, 1, 1), snapshot)
        self.assertEqual(retained["points"], profile["points"])
        self.assertEqual(retained["status"], "failed")

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
