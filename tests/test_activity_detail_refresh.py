"""Read-only provider refresh, durable cache and failure atomicity contracts."""

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import Mock

from activity_row_support import FixedActivityRows
from canonical_detail_support import open_manager, seed_intervals_activity

from backend.activities.detail_store import ActivityDetailStore
from backend.errors import AppError, ProviderErrorClassifier, provider_error
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from backend.sync.activity_details import (
    MAX_STREAM_POINTS,
    ActivityDetailRefreshService,
    normalize_streams,
)
from backend.sync.jobs import JobValidationError, normalize_sync_job_request


class Manager:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def unit_of_work(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def reader(self):
        return self.unit_of_work()

    read_snapshot = reader


class ActivityDetailRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = Manager(Path(self.directory.name) / "fixture.sqlite")
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
        self.store = ActivityDetailStore(self.manager)
        self.api = Mock()
        self.rows = FixedActivityRows([{"id": "CaseSensitive-1"}])
        self.service = ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=self.rows,
            store=self.store,
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
        )

    def responses(self):
        return [
            {
                "id": "CaseSensitive-1",
                "name": "Synthetic ride",
                "private_field": "excluded",
            },
            [
                {"type": "time", "data": list(range(3001))},
                {"type": "watts", "data": [200] * 3001},
            ],
        ]

    def test_refresh_keeps_full_resolution_and_provenance_across_restart(self):
        self.api.get.side_effect = self.responses()
        self.assertEqual("completed", self.service.refresh("CaseSensitive-1")["status"])
        saved = ActivityDetailStore(self.manager).get("CaseSensitive-1")
        self.assertEqual(3001, len(saved["activity"]["streams"]["watts"]))
        self.assertEqual("Intervals.icu", saved["source"])
        self.assertEqual("2026-10-02T08:00:00Z", saved["observed_at"])
        self.assertNotIn("private_field", saved["activity"])
        self.assertEqual(
            "/activity/CaseSensitive-1", self.api.get.call_args_list[0].args[0]
        )
        self.api.post.assert_not_called()
        self.api.put.assert_not_called()

    def test_streams_request_uses_extension_and_documented_stream_types(self):
        self.api.get.side_effect = self.responses()
        self.service.refresh("CaseSensitive-1")
        path, params = self.api.get.call_args_list[1].args
        self.assertEqual("/activity/CaseSensitive-1/streams.json", path)
        self.assertEqual(
            "time,distance,altitude,grade_smooth,velocity_smooth,"
            "watts,heartrate,cadence,temp,moving",
            params["types"],
        )

    def test_provider_temp_stream_is_stored_as_temperature(self):
        self.api.get.side_effect = [
            {"id": "CaseSensitive-1"},
            [
                {"type": "time", "data": [0, 1]},
                {"type": "temp", "data": [14, 15]},
            ],
        ]
        self.service.refresh("CaseSensitive-1")
        streams = self.store.get("CaseSensitive-1")["activity"]["streams"]
        self.assertEqual([14, 15], streams["temperature"])
        self.assertNotIn("temp", streams)

    def test_failed_second_fetch_preserves_previous_record(self):
        self.api.get.side_effect = self.responses()
        self.service.refresh("CaseSensitive-1")
        before = self.store.get("CaseSensitive-1")
        self.api.get.side_effect = [
            self.responses()[0],
            AppError(503, "Synthetic failure"),
        ]
        with self.assertRaises(AppError):
            self.service.refresh("CaseSensitive-1")
        self.assertEqual(before, self.store.get("CaseSensitive-1"))

    def test_unknown_id_and_path_syntax_never_reach_provider(self):
        with self.assertRaises(AppError):
            self.service.refresh("unknown")
        for activity_id in ("../x", "x/y", "x?athlete=other", "", "x" * 201):
            with self.subTest(activity_id=activity_id), self.assertRaises(ValueError):
                self.service.refresh(activity_id)
        self.api.get.assert_not_called()

    def test_mismatched_provider_id_is_not_committed(self):
        self.api.get.return_value = {"id": "other"}
        with self.assertRaises(AppError):
            self.service.refresh("CaseSensitive-1")
        self.assertIsNone(self.store.get("CaseSensitive-1"))

    def test_stream_limits_alignment_and_missing_values(self):
        for streams in (
            [{"type": "time", "data": [0, 0]}],
            [{"type": "time", "data": [0, 1]}, {"type": "watts", "data": [1]}],
            [{"type": "time", "data": [0] * (MAX_STREAM_POINTS + 1)}],
        ):
            with self.subTest(length=len(streams)), self.assertRaises(AppError):
                normalize_streams(streams)
        result = normalize_streams(
            [
                {"type": "time", "data": [0, 1, 2]},
                {"type": "watts", "data": [0, None, float("nan")]},
                {"type": "latlng", "data": [[1, 2]]},
            ]
        )
        self.assertEqual([0, None, None], result["watts"])
        self.assertNotIn("latlng", result)

    def test_job_normalization_preserves_case_and_rejects_unrelated_targets(self):
        envelope = normalize_sync_job_request(
            "intervals",
            "activity_details",
            {"activity_id": "CaseSensitive-1"},
            all_sync_days=-1,
        )
        self.assertEqual("CaseSensitive-1", envelope["payload"]["activity_id"])
        garmin = normalize_sync_job_request(
            "garmin",
            "activity_details",
            {"activity_id": "CaseSensitive-1"},
            all_sync_days=-1,
        )
        self.assertEqual("CaseSensitive-1", garmin["payload"]["activity_id"])
        for provider, payload in (
            ("intervals", {"activity_id": "../x"}),
            ("intervals", {"activity_id": "x", "remote_write": True}),
        ):
            with self.subTest(provider=provider), self.assertRaises(JobValidationError):
                normalize_sync_job_request(
                    provider, "activity_details", payload, all_sync_days=-1
                )


class ActivityDetailPrefetchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = Manager(Path(self.directory.name) / "fixture.sqlite")
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
        self.store = ActivityDetailStore(self.manager)
        self.rows = [
            {"id": f"a{day:02d}", "start_date_local": f"2026-10-{day:02d}T08:00:00"}
            for day in range(1, 13)
        ]
        self.api = Mock()
        self.api.get.side_effect = self.provider

    def provider(self, path, params):
        activity_id = path.split("/")[2]
        if path.endswith("/streams.json"):
            return [{"type": "time", "data": [0, 1]}]
        return {"id": activity_id}

    def service(self, configured=True):
        return ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=FixedActivityRows(self.rows),
            store=self.store,
            utc_now=lambda: "2026-10-18T08:00:00Z",
            configured=configured,
        )

    def fetched_ids(self):
        return [
            call.args[0].split("/")[2]
            for call in self.api.get.call_args_list
            if not call.args[0].endswith("/streams.json")
        ]

    def test_loads_only_the_ten_newest_activities_once(self):
        self.assertEqual({"fetched": 10, "failed": 0}, self.service().prefetch_recent())
        self.assertEqual(
            [f"a{day:02d}" for day in range(12, 2, -1)], self.fetched_ids()
        )
        self.assertIsNone(self.store.get("a02"))
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_recent())
        self.api.get.assert_not_called()

    def test_records_from_an_older_projection_are_loaded_again(self):
        self.service().prefetch_recent()
        with self.manager.unit_of_work() as db:
            for row in self.rows[2:]:
                record = self.store.get(row["id"])
                record.pop("projection_version")
                self.store.save_in(db, row["id"], record)
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 10, "failed": 0}, self.service().prefetch_recent())
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_recent())

    def test_changed_summary_is_loaded_again(self):
        self.service().prefetch_recent()
        self.rows[-1] = {**self.rows[-1], "name": "Renamed in Intervals.icu"}
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 1, "failed": 0}, self.service().prefetch_recent())
        self.assertEqual(["a12"], self.fetched_ids())

    def test_activity_specific_failure_skips_only_that_activity(self):
        def failing(path, params):
            if "a11" in path:
                raise AppError(502, "Synthetic invalid streams")
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING") as logs:
            result = self.service().prefetch_recent()
        self.assertEqual({"fetched": 9, "failed": 1}, result)
        self.assertEqual(
            [f"a{day:02d}" for day in range(12, 2, -1)], self.fetched_ids()
        )
        self.assertIsNone(self.store.get("a11"))
        self.assertIsNotNone(self.store.get("a03"))
        self.assertNotIn("Synthetic invalid streams", "\n".join(logs.output))
        failure = self.store.failures(["a11", "a12"])
        self.assertEqual(["a11"], list(failure))
        self.assertEqual("2026-10-18T08:00:00Z", failure["a11"]["observed_at"])
        self.assertIn("fehlerhaft", failure["a11"]["message"])
        self.assertNotIn("Synthetic", failure["a11"]["message"])
        # Detail scans for calendar and analysis ignore failure records.
        self.assertNotIn("a11", self.store.calendar_profiles())

    def test_recorded_failure_waits_for_changed_summary_or_manual_reload(self):
        self.test_activity_specific_failure_skips_only_that_activity()
        self.api.get.side_effect = self.provider
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_recent())
        self.api.get.assert_not_called()

        self.service().refresh("a11")
        self.assertIsNotNone(self.store.get("a11"))
        self.assertEqual({}, self.store.failures(["a11"]))

    def test_recorded_failure_is_retried_after_summary_change(self):
        self.test_activity_specific_failure_skips_only_that_activity()
        self.api.get.side_effect = self.provider
        self.api.get.reset_mock()
        self.rows[-2] = {**self.rows[-2], "name": "Renamed in Intervals.icu"}
        self.assertEqual({"fetched": 1, "failed": 0}, self.service().prefetch_recent())
        self.assertEqual(["a11"], self.fetched_ids())
        self.assertEqual({}, self.store.failures(["a11"]))

    def test_summary_reverted_to_stored_details_clears_the_failure(self):
        self.api.get.side_effect = self.provider
        self.assertEqual({"fetched": 10, "failed": 0}, self.service().prefetch_recent())
        original = self.rows[-2]
        self.rows[-2] = {**original, "name": "Renamed in Intervals.icu"}

        def failing(path, params):
            if "a11" in path:
                raise AppError(502, "Synthetic invalid streams")
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING"):
            self.service().prefetch_recent()
        self.assertIn("a11", self.store.failures(["a11"]))
        self.rows[-2] = original
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_recent())
        self.api.get.assert_not_called()
        self.assertEqual({}, self.store.failures(["a11"]))

    def run_with_failure_on_a11(self, error):
        self.api.get.reset_mock()
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM kv")

        def failing(path, params):
            if "a11" in path:
                raise error
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING"):
            return self.service().prefetch_recent()

    def test_missing_remote_activity_is_skipped(self):
        error = ProviderErrorClassifier.classify_upstream(
            "Synthetic not found", upstream_status=404, reason="provider_http_error"
        )
        self.assertEqual(
            {"fetched": 9, "failed": 1}, self.run_with_failure_on_a11(error)
        )
        self.assertIn(
            "keine Detaildaten", self.store.failures(["a11"])["a11"]["message"]
        )

    def test_provider_wide_failures_stop_the_run(self):
        for upstream_status in (401, 403, 503):
            with self.subTest(upstream_status=upstream_status):
                error = ProviderErrorClassifier.classify_upstream(
                    "Synthetic upstream",
                    upstream_status=upstream_status,
                    reason="provider_http_error",
                )
                self.assertEqual(
                    {"fetched": 1, "failed": 1}, self.run_with_failure_on_a11(error)
                )
                self.assertEqual(["a12", "a11"], self.fetched_ids())
                self.assertEqual({}, self.store.failures(["a11"]))
        with self.subTest("network"):
            self.assertEqual(
                {"fetched": 1, "failed": 1},
                self.run_with_failure_on_a11(provider_error("intervals", "network")),
            )

    def test_rate_limit_stops_without_raising(self):
        def failing(path, params):
            if "a11" in path:
                raise AppError(429, "Synthetic rate limit")
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING") as logs:
            result = self.service().prefetch_recent()
        self.assertEqual({"fetched": 1, "failed": 1}, result)
        self.assertEqual(["a12", "a11"], self.fetched_ids())
        self.assertNotIn("Synthetic rate limit", "\n".join(logs.output))

    def test_guard_wraps_each_provider_refresh(self):
        events = []

        @contextmanager
        def guard():
            events.append("enter")
            yield
            events.append("exit")

        self.rows = self.rows[:2]
        self.service().prefetch_recent(guard)
        self.assertEqual(["enter", "exit", "enter", "exit"], events)

    def test_unconfigured_provider_is_not_called(self):
        self.assertEqual(
            {"fetched": 0, "failed": 0},
            self.service(configured=False).prefetch_recent(),
        )
        self.api.get.assert_not_called()


class ActivityDetailCanonicalRefreshTests(unittest.TestCase):
    """A refresh writes the kv record and its canonical rows in one transaction."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        seed_intervals_activity(self.manager, "9001")
        self.store = ActivityDetailStore(self.manager)
        self.api = Mock()
        self.api.get.side_effect = [
            {"id": "9001", "name": "Synthetic ride", "moving_time": 1000},
            [
                {"type": "time", "data": [0, 1, 2]},
                {"type": "watts", "data": [200, 210, 220]},
            ],
        ]

    def service(self, canonical):
        return ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=FixedActivityRows([{"id": "9001"}]),
            store=self.store,
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
            canonical=canonical,
        )

    def canonical_rows(self):
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM activity_detail_sets "
                "WHERE provider_activity_id = ?",
                ("9001",),
            ).fetchone()
        return row["n"]

    def test_refresh_writes_canonical_rows_with_the_kv_record(self):
        result = self.service(CanonicalDetailWriter()).refresh("9001")
        self.assertEqual("completed", result["status"])
        self.assertIsNotNone(self.store.get("9001"))
        self.assertGreater(self.canonical_rows(), 0)

    def test_failed_canonical_write_leaves_neither_record_nor_rows(self):
        class RaisingWriter(CanonicalDetailWriter):
            def write_fetch(self, db, **kwargs):
                super().write_fetch(db, **kwargs)
                raise RuntimeError("simulated canonical failure")

        with self.assertRaises(RuntimeError):
            self.service(RaisingWriter()).refresh("9001")
        self.assertIsNone(self.store.get("9001"))
        self.assertEqual(0, self.canonical_rows())
