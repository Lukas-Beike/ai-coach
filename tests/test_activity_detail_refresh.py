"""Read-only provider refresh, canonical storage and failure atomicity contracts."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import legacy_detail_kv
from activity_row_support import FixedActivityRows
from canonical_detail_support import INTERVALS, open_manager, seed_intervals_activity

from backend.activities.detail_analysis_reads import calendar_profiles
from backend.activities.detail_projection import DETAIL_PROJECTION_VERSION
from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.canonical.vocabulary import (
    ActivityDetailKind,
    ActivityDetailOrigin,
    ProviderId,
    StreamChannel,
    StreamResolution,
)
from backend.db import DatabaseManager, row_factory
from backend.db.activity_detail_store import analysis_row_for_record, detail_sets_for
from backend.errors import AppError, ProviderErrorClassifier, provider_error
from backend.sync.activity_detail_canonical import (
    CanonicalDetailWriter,
    DetailWriteOutcome,
    DetailWriteResult,
)
from backend.sync.activity_details import (
    MAX_STREAM_POINTS,
    ActivityDetailRefreshService,
    normalize_streams,
)
from backend.sync.jobs import JobValidationError, normalize_sync_job_request

DETAIL_KEY_PREFIX = "activity_detail:"


def detail_sets(manager, activity_id):
    """Return the stored canonical detail sets of one Intervals activity by kind."""
    with manager.reader() as db:
        return {
            item.detail.kind: item for item in detail_sets_for(db, INTERVALS, activity_id)
        }


def analysis_payload(manager, activity_id):
    with manager.reader() as db:
        row = analysis_row_for_record(db, INTERVALS, activity_id)
    return None if row is None else row["payload"]


def kv_detail_keys(manager):
    with manager.reader() as db:
        return [
            row["key"]
            for row in db.execute(
                "SELECT key FROM kv WHERE substr(key, 1, ?) = ?",
                (len(DETAIL_KEY_PREFIX), DETAIL_KEY_PREFIX),
            )
        ]


def canonical_snapshot(manager):
    """Every canonical detail row, to prove that nothing changed."""
    with manager.reader() as db:
        return [
            [
                tuple(row.values())
                for row in db.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")
            ]
            for table in (
                "activity_detail_sets",
                "activity_stream_channels",
                "activity_laps",
                "activity_zone_times",
                "activity_detail_analysis",
            )
        ]


class ActivityDetailRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(lambda: self.manager.close())
        seed_intervals_activity(self.manager, "CaseSensitive-1")
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
            canonical=CanonicalDetailWriter(),
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
        # A new manager on the same file stands in for an application restart.
        self.manager.close()
        self.manager = DatabaseManager(
            Path(self.directory.name) / "detail.db", sqlite3, row_factory=row_factory
        )
        streams = detail_sets(self.manager, "CaseSensitive-1")[ActivityDetailKind.STREAMS]
        self.assertEqual(StreamResolution.FULL, streams.detail.resolution)
        self.assertEqual(3001, len(streams.detail.channels[StreamChannel.POWER_W]))
        self.assertIs(ProviderId.INTERVALS, streams.detail.provenance.provider)
        self.assertEqual(ActivityDetailOrigin.FETCH, streams.detail.origin)
        self.assertEqual("2026-10-02T08:00:00+00:00", streams.fetched_at)
        payload = analysis_payload(self.manager, "CaseSensitive-1")
        self.assertEqual("2026-10-02T08:00:00Z", payload["observed_at"])
        self.assertNotIn("private_field", json.dumps(payload))
        # The refresh writes canonical rows only, never a kv detail record.
        self.assertEqual([], kv_detail_keys(self.manager))
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
        streams = detail_sets(self.manager, "CaseSensitive-1")[ActivityDetailKind.STREAMS]
        self.assertEqual(
            (14.0, 15.0), streams.detail.channels[StreamChannel.TEMPERATURE_C]
        )

    def test_failed_second_fetch_preserves_previous_record(self):
        self.api.get.side_effect = self.responses()
        self.service.refresh("CaseSensitive-1")
        before = canonical_snapshot(self.manager)
        self.assertTrue(before[0])
        self.api.get.side_effect = [
            self.responses()[0],
            AppError(503, "Synthetic failure"),
        ]
        with self.assertRaises(AppError):
            self.service.refresh("CaseSensitive-1")
        self.assertEqual(before, canonical_snapshot(self.manager))

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
        self.assertEqual({}, detail_sets(self.manager, "CaseSensitive-1"))
        self.assertIsNone(analysis_payload(self.manager, "CaseSensitive-1"))

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
    """Prefetch staleness comes from the canonical fingerprints only."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        self.store = ActivityDetailStore(self.manager)
        self.rows = []
        self.add_rows(
            [
                {
                    "id": f"a{day:02d}",
                    "start_date_local": f"2026-10-{day:02d}T08:00:00",
                }
                for day in range(1, 13)
            ]
        )
        self.api = Mock()
        self.api.get.side_effect = self.provider

    def add_rows(self, rows):
        """Add summaries and their local activity records, so details can be stored."""
        for row in rows:
            seed_intervals_activity(self.manager, row["id"])
        self.rows += rows

    def provider(self, path, params):
        activity_id = path.split("/")[2]
        if path.endswith("/streams.json"):
            return [
                {"type": "time", "data": [0, 1, 2]},
                {"type": "watts", "data": [200, 210, 220]},
            ]
        return {"id": activity_id, "moving_time": 1000}

    def has_details(self, activity_id):
        return bool(detail_sets(self.manager, activity_id))

    def canonical_update(self, sql, parameters=()):
        with self.manager.unit_of_work() as db:
            db.execute(sql, parameters)

    def prefetched_service(self):
        """Prefetch once, then forget the provider calls of that run."""
        self.service().prefetch_new()
        self.api.get.reset_mock()

    def service(self, configured=True):
        return ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=FixedActivityRows(self.rows),
            store=self.store,
            utc_now=lambda: "2026-10-18T08:00:00Z",
            configured=configured,
            canonical=CanonicalDetailWriter(),
        )

    def fetched_ids(self):
        return [
            call.args[0].split("/")[2]
            for call in self.api.get.call_args_list
            if not call.args[0].endswith("/streams.json")
        ]

    def test_first_run_loads_the_ten_newest_activities_once(self):
        self.assertEqual({"fetched": 10, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(
            [f"a{day:02d}" for day in range(12, 2, -1)], self.fetched_ids()
        )
        self.assertFalse(self.has_details("a02"))
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()

    def leave_legacy_kv_records(self, **changes):
        """Store kv records like an earlier release, matching the current summaries."""
        with self.manager.unit_of_work() as db:
            for row in self.rows:
                record = {
                    "activity_id": row["id"],
                    "projection_version": DETAIL_PROJECTION_VERSION,
                    "observed_at": "2026-10-01T08:00:00Z",
                    "activity": {"streams": {}},
                    "summary_sha256": summary_fingerprint(row),
                    **changes,
                }
                legacy_detail_kv.save_in(db, row["id"], record)

    def test_leftover_kv_record_does_not_settle_prefetch(self):
        self.prefetched_service()
        self.canonical_update("DELETE FROM activity_detail_sets")
        self.canonical_update("DELETE FROM activity_detail_analysis")
        self.leave_legacy_kv_records()
        self.assertEqual({"fetched": 10, "failed": 0}, self.service().prefetch_new())
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())

    def test_leftover_kv_record_of_an_older_projection_does_not_reload(self):
        # Canonical rows decide; the kv projection version no longer participates.
        self.prefetched_service()
        self.leave_legacy_kv_records(projection_version=None)
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()

    def test_legacy_backfilled_set_with_matching_hash_is_not_loaded_again(self):
        self.prefetched_service()
        self.canonical_update(
            "UPDATE activity_detail_sets SET origin = ?",
            (ActivityDetailOrigin.LEGACY_BACKFILL.value,),
        )
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()

    def test_set_of_an_older_mapper_with_matching_hash_is_not_loaded_again(self):
        self.prefetched_service()
        self.canonical_update("UPDATE activity_detail_sets SET mapper_version = 1")
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()

    def test_changed_hash_without_kv_record_is_loaded_again(self):
        self.prefetched_service()
        self.rows[-1] = {**self.rows[-1], "name": "Renamed in Intervals.icu"}
        self.assertEqual({"fetched": 1, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(["a12"], self.fetched_ids())

    def test_analysis_only_row_with_matching_hash_is_not_loaded_again(self):
        self.prefetched_service()
        self.canonical_update("DELETE FROM activity_detail_sets")
        # Payloads written before analysis version 2 carry no summary hash.
        self.canonical_update(
            "UPDATE activity_detail_analysis "
            "SET payload = json_remove(payload, '$.summary_sha256')"
        )
        self.canonical_update(
            "UPDATE activity_detail_analysis SET payload = json_set(payload, "
            "'$.summary_sha256', ?) WHERE activity_id = ("
            "SELECT activity_id FROM activity_records WHERE provider = ? "
            "AND provider_activity_id = ?)",
            (summary_fingerprint(self.rows[-1]), INTERVALS, "a12"),
        )
        self.assertEqual({"fetched": 9, "failed": 0}, self.service().prefetch_new())
        self.assertNotIn("a12", self.fetched_ids())

    def test_changed_summary_is_loaded_again(self):
        self.service().prefetch_new()
        self.rows[-1] = {**self.rows[-1], "name": "Renamed in Intervals.icu"}
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 1, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(["a12"], self.fetched_ids())

    def test_activity_specific_failure_skips_only_that_activity(self):
        def failing(path, params):
            if "a11" in path:
                raise AppError(502, "Synthetic invalid streams")
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING") as logs:
            result = self.service().prefetch_new()
        self.assertEqual({"fetched": 9, "failed": 1}, result)
        self.assertEqual(
            [f"a{day:02d}" for day in range(12, 2, -1)], self.fetched_ids()
        )
        self.assertFalse(self.has_details("a11"))
        self.assertTrue(self.has_details("a03"))
        self.assertNotIn("Synthetic invalid streams", "\n".join(logs.output))
        failure = self.store.failures(["a11", "a12"])
        self.assertEqual(["a11"], list(failure))
        self.assertEqual("2026-10-18T08:00:00Z", failure["a11"]["observed_at"])
        self.assertIn("fehlerhaft", failure["a11"]["message"])
        self.assertNotIn("Synthetic", failure["a11"]["message"])
        # Detail scans for calendar and analysis ignore failure records.
        self.assertNotIn("a11", calendar_profiles(self.manager))

    def test_recorded_failure_waits_for_changed_summary_or_manual_reload(self):
        self.test_activity_specific_failure_skips_only_that_activity()
        self.api.get.side_effect = self.provider
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()

        self.service().refresh("a11")
        self.assertTrue(self.has_details("a11"))
        self.assertEqual({}, self.store.failures(["a11"]))

    def test_recorded_failure_is_retried_after_summary_change(self):
        self.test_activity_specific_failure_skips_only_that_activity()
        self.api.get.side_effect = self.provider
        self.api.get.reset_mock()
        self.rows[-2] = {**self.rows[-2], "name": "Renamed in Intervals.icu"}
        self.assertEqual({"fetched": 1, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(["a11"], self.fetched_ids())
        self.assertEqual({}, self.store.failures(["a11"]))

    def test_summary_reverted_to_stored_details_clears_the_failure(self):
        self.api.get.side_effect = self.provider
        self.assertEqual({"fetched": 10, "failed": 0}, self.service().prefetch_new())
        original = self.rows[-2]
        self.rows[-2] = {**original, "name": "Renamed in Intervals.icu"}

        def failing(path, params):
            if "a11" in path:
                raise AppError(502, "Synthetic invalid streams")
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING"):
            self.service().prefetch_new()
        self.assertIn("a11", self.store.failures(["a11"]))
        self.rows[-2] = original
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()
        self.assertEqual({}, self.store.failures(["a11"]))

    def run_with_failure_on_a11(self, error):
        self.api.get.reset_mock()
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM kv")
            db.execute("DELETE FROM activity_detail_sets")
            db.execute("DELETE FROM activity_detail_analysis")

        def failing(path, params):
            if "a11" in path:
                raise error
            return self.provider(path, params)

        self.api.get.side_effect = failing
        with self.assertLogs("backend.sync.activity_details", "WARNING"):
            return self.service().prefetch_new()

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
            result = self.service().prefetch_new()
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
        self.service().prefetch_new(guard)
        self.assertEqual(["enter", "exit", "enter", "exit"], events)

    def test_unconfigured_provider_is_not_called(self):
        self.assertEqual(
            {"fetched": 0, "failed": 0},
            self.service(configured=False).prefetch_new(),
        )
        self.api.get.assert_not_called()

    def test_every_new_activity_loads_while_older_ones_stay_unloaded(self):
        self.service().prefetch_new()
        self.assertEqual("2026-10-03T08:00:00", self.store.prefetch_floor())
        self.add_rows(
            [
                {
                    "id": f"n{index:02d}",
                    "start_date_local": f"2026-11-{index:02d}T08:00:00",
                }
                for index in range(1, 31)
            ]
        )
        self.api.get.reset_mock()
        # More new activities than one run loads: the rest follow on the next refresh.
        self.assertEqual({"fetched": 25, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(
            [f"n{index:02d}" for index in range(30, 5, -1)], self.fetched_ids()
        )
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 5, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(
            [f"n{index:02d}" for index in range(5, 0, -1)], self.fetched_ids()
        )
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.api.get.assert_not_called()
        self.assertFalse(self.has_details("a01"))
        self.assertFalse(self.has_details("a02"))

    def test_floor_is_kept_once_set(self):
        self.service().prefetch_new()
        self.rows = self.rows[-1:]
        self.service().prefetch_new()
        self.assertEqual("2026-10-03T08:00:00", self.store.prefetch_floor())

    def test_floor_without_local_activities_starts_today(self):
        self.rows = []
        self.assertEqual({"fetched": 0, "failed": 0}, self.service().prefetch_new())
        self.assertEqual("2026-10-18", self.store.prefetch_floor())
        self.rows = []
        self.add_rows(
            [
                {"id": "old", "start_date_local": "2026-10-17T08:00:00"},
                {"id": "new", "start_date_local": "2026-10-18T07:00:00"},
            ]
        )
        self.assertEqual({"fetched": 1, "failed": 0}, self.service().prefetch_new())
        self.assertEqual(["new"], self.fetched_ids())

    def test_floor_without_local_activities_uses_the_athlete_local_date(self):
        self.rows = []
        service = ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=FixedActivityRows(self.rows),
            store=self.store,
            # 23:30 UTC on the 18th is already the 19th in the athlete's zone.
            utc_now=lambda: "2026-10-18T23:30:00Z",
            configured=True,
            canonical=CanonicalDetailWriter(),
            local_date=lambda: "2026-10-19",
        )
        service.prefetch_new()
        self.assertEqual("2026-10-19", self.store.prefetch_floor())


class UnstoredWriter(CanonicalDetailWriter):
    """A writer whose fetch write stores nothing."""

    def __init__(self, outcome):
        super().__init__()
        self.outcome = outcome

    def write_fetch(self, db, **kwargs):
        return DetailWriteResult(self.outcome)


class ActivityDetailCanonicalRefreshTests(unittest.TestCase):
    """A refresh writes only canonical rows and clears the failure note with them."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        seed_intervals_activity(self.manager, "9001")
        self.store = ActivityDetailStore(self.manager)
        self.api = Mock()
        self.api.get.side_effect = self.provider
        self.planned_units = Mock(return_value=[])

    def provider(self, path, params):
        if path.endswith("/streams.json"):
            return [
                {"type": "time", "data": [0, 1, 2]},
                {"type": "watts", "data": [200, 210, 220]},
            ]
        return {"id": "9001", "name": "Synthetic ride", "moving_time": 1000}

    def service(self, canonical):
        return ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=FixedActivityRows([{"id": "9001"}]),
            store=self.store,
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
            read_planned_units=self.planned_units,
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

    def save_failure(self):
        self.store.save_failure(
            "9001", "0" * 64, "Synthetic note", "2026-10-01T08:00:00Z"
        )

    def test_refresh_writes_canonical_rows_without_a_kv_record(self):
        result = self.service(CanonicalDetailWriter()).refresh("9001")
        self.assertEqual("completed", result["status"])
        self.assertGreater(self.canonical_rows(), 0)
        self.assertIsNotNone(analysis_payload(self.manager, "9001"))
        self.assertEqual([], kv_detail_keys(self.manager))

    def test_prefetch_stores_new_activity_in_the_canonical_tables(self):
        self.assertEqual(
            {"fetched": 1, "failed": 0},
            self.service(CanonicalDetailWriter()).prefetch_new(),
        )
        self.assertGreater(self.canonical_rows(), 0)
        self.assertEqual([], kv_detail_keys(self.manager))

    def test_refresh_clears_the_failure_note_with_the_canonical_rows(self):
        self.save_failure()
        self.assertIn("9001", self.store.failures(["9001"]))
        self.service(CanonicalDetailWriter()).refresh("9001")
        self.assertEqual({}, self.store.failures(["9001"]))
        self.assertGreater(self.canonical_rows(), 0)

    def test_failed_canonical_write_commits_nothing(self):
        class RaisingWriter(CanonicalDetailWriter):
            def write_fetch(self, db, **kwargs):
                super().write_fetch(db, **kwargs)
                raise RuntimeError("simulated canonical failure")

        self.save_failure()
        with self.assertRaises(RuntimeError):
            self.service(RaisingWriter()).refresh("9001")
        self.assertEqual(0, self.canonical_rows())
        self.assertIsNone(analysis_payload(self.manager, "9001"))
        self.assertEqual([], kv_detail_keys(self.manager))
        # The failure note rolls back with the rows that would have replaced it.
        self.assertIn("9001", self.store.failures(["9001"]))

    def test_unstored_write_fails_and_keeps_the_failure_note(self):
        for outcome in (DetailWriteOutcome.NO_RECORD, DetailWriteOutcome.INVALID):
            with self.subTest(outcome):
                self.save_failure()
                with self.assertRaises(AppError) as raised:
                    self.service(UnstoredWriter(outcome)).refresh("9001")
                self.assertEqual(502, raised.exception.status)
                self.assertIn("9001", self.store.failures(["9001"]))

    def test_prefetch_records_a_failure_when_nothing_was_stored(self):
        service = self.service(UnstoredWriter(DetailWriteOutcome.NO_RECORD))
        self.assertEqual({"fetched": 0, "failed": 1}, service.prefetch_new())
        self.assertIn("9001", self.store.failures(["9001"]))
        self.api.get.reset_mock()
        self.assertEqual({"fetched": 0, "failed": 0}, service.prefetch_new())
        self.api.get.assert_not_called()

    def test_frozen_targets_are_reused_from_the_canonical_analysis(self):
        self.service(CanonicalDetailWriter()).refresh("9001")
        self.planned_units.assert_called_once_with()
        frozen = {"frozen_at": "2026-10-01T08:00:00Z", "basis": "synthetic"}
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_detail_analysis "
                "SET payload = json_set(payload, '$.target_snapshot', json(?))",
                (json.dumps(frozen),),
            )
        self.planned_units.reset_mock()
        self.service(CanonicalDetailWriter()).refresh("9001")
        payload = analysis_payload(self.manager, "9001")
        self.assertEqual(frozen, payload["target_snapshot"])
        self.planned_units.assert_not_called()


if __name__ == "__main__":
    unittest.main()
