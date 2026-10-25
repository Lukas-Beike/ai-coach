"""Stored activity detail records are deleted only once canonical rows prove them."""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import legacy_detail_kv
from activity_row_support import FixedActivityRows
from canonical_detail_support import (
    INTERVALS,
    NOW,
    open_manager,
    seed_intervals_activity,
)

from backend.activities.detail_projection import _downsample_series
from backend.activities.detail_store import ActivityDetailStore
from backend.canonical.vocabulary import LapKind
from backend.db.activity_detail_store import detail_sets_for
from backend.db.repositories import KeyValueRepository
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import activity_detail_retirement
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from backend.sync.activity_detail_retirement import (
    STATE_KEY,
    ActivityDetailRetirement,
)
from backend.sync.activity_details import ActivityDetailRefreshService
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_backfill_assembly import build_canonical_backfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker

POINTS = 3001
CANONICAL_TABLES = (
    "activity_detail_sets",
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_detail_analysis",
)


class RecordingWriter(CanonicalDetailWriter):
    """Keep each loaded record, so the test can store it as an earlier release did."""

    def __init__(self):
        self.records = {}

    def write_fetch(self, db, **kwargs):
        self.records[kwargs["activity_id"]] = kwargs["record"]
        return super().write_fetch(db, **kwargs)


def provider_detail(activity_id):
    return {
        "id": activity_id,
        "name": "Synthetic intervals",
        "moving_time": 900,
        "icu_hr_zone_times": [300, 400, 200],
        "icu_intervals": [
            {
                "type": "WORK",
                "name": "Work 1",
                "start_time": 0,
                "end_time": 600,
                "average_watts": 280,
                "average_speed": 9.0,
                "max_speed": 11.5,
            },
            {
                "type": "RECOVERY",
                "name": "Recovery 1",
                "start_time": 600,
                "end_time": 900,
                "average_watts": 120,
                "average_speed": 6.0,
                "max_speed": 7.25,
            },
        ],
    }


def provider_streams(points):
    return [
        {"type": "time", "data": list(range(points))},
        {"type": "watts", "data": [200 + step % 50 for step in range(points)]},
        {"type": "heartrate", "data": [130 + step % 20 for step in range(points)]},
    ]


def detail_keys(manager):
    with manager.reader() as db:
        rows = db.execute("SELECT key FROM kv").fetchall()
    return [row["key"] for row in rows if row["key"].startswith("activity_detail:")]


def canonical_snapshot(manager):
    with manager.reader() as db:
        return [
            [
                tuple(row.values())
                for row in db.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")
            ]
            for table in CANONICAL_TABLES
        ]


class RetirementTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.store = ActivityDetailStore(self.manager)
        self.api = Mock()

    def load(self, activity_id, points=12):
        """Fetch one activity and keep its kv record, as an earlier release did."""
        seed_intervals_activity(self.manager, activity_id)
        responses = {
            f"/activity/{activity_id}": provider_detail(activity_id),
            f"/activity/{activity_id}/streams.json": provider_streams(points),
        }
        self.api.get.side_effect = lambda path, params=None: responses[path]
        writer = RecordingWriter()
        ActivityDetailRefreshService(
            api_client=self.api,
            database_manager=self.manager,
            row_reader=FixedActivityRows([{"id": activity_id}]),
            store=self.store,
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
            canonical=writer,
        ).refresh(activity_id)
        record = writer.records[activity_id]
        legacy_detail_kv.save(self.manager, activity_id, record)
        return record

    def save_record(self, record):
        legacy_detail_kv.save(self.manager, record["activity_id"], record)

    def save_raw_record(self, record):
        """Store a record as given, keeping its analysis values unchanged."""
        with self.manager.unit_of_work() as db:
            self.key_values.set(
                db, legacy_detail_kv.key(record["activity_id"]), json.dumps(record)
            )

    def make(self, batch_size=20):
        return ActivityDetailRetirement(
            key_values=self.key_values, clock=lambda: NOW, batch_size=batch_size
        )

    def run_to_completion(self, retirement=None):
        retirement = retirement or self.make()
        for _ in range(100):
            with self.manager.unit_of_work() as db:
                if retirement.run_batch(db).done:
                    return self.counters()
        self.fail("the retirement did not finish")

    def counters(self):
        with self.manager.reader() as db:
            return json.loads(self.key_values.get(db, STATE_KEY))["counters"]

    def execute(self, sql, parameters=()):
        with self.manager.unit_of_work() as db:
            db.execute(sql, parameters)

    def kv_rows(self):
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT key, value FROM kv WHERE key <> ? ORDER BY key", (STATE_KEY,)
            ).fetchall()
        return [(row["key"], row["value"]) for row in rows]

    def kv_record(self, activity_id):
        with self.manager.reader() as db:
            raw = self.key_values.get(db, legacy_detail_kv.key(activity_id))
        return None if raw is None else json.loads(raw)

    def laps(self, activity_id):
        with self.manager.reader() as db:
            stored = {
                item.detail.kind.value: item.detail
                for item in detail_sets_for(db, INTERVALS, activity_id)
            }
        return stored["laps"].laps

    def lap_content_hash(self, activity_id):
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT content_sha256 FROM activity_detail_sets "
                "WHERE provider_activity_id = ? AND detail_kind = 'laps'",
                (activity_id,),
            ).fetchone()
        return row["content_sha256"]


class RetiredRecordTests(RetirementTestCase):
    def test_proven_record_is_deleted_and_other_keys_are_kept(self):
        record = self.load("9201")
        self.store.save_failure("9299", "0" * 64, "Synthetic note", NOW)
        self.store.save_prefetch_floor("2026-10-01T00:00:00", NOW)
        canonical = canonical_snapshot(self.manager)
        kept = [row for row in self.kv_rows() if not row[0].startswith("activity_detail:")]
        calls = self.api.get.call_count
        self.assertTrue(record["activity"]["laps"])
        counters = self.run_to_completion()
        self.assertEqual(1, counters["retired"])
        self.assertEqual(0, counters["laps_refilled"])
        self.assertIsNone(self.kv_record("9201"))
        self.assertEqual(kept, self.kv_rows())
        self.assertEqual(canonical, canonical_snapshot(self.manager))
        # The retirement reads local rows only; no provider is called.
        self.assertEqual(calls, self.api.get.call_count)

    def test_legacy_laps_without_a_kind_match_work_and_recovery_laps(self):
        record = self.load("9202")
        self.assertTrue(all("type" not in lap for lap in record["activity"]["laps"]))
        self.assertEqual(
            [LapKind.WORK, LapKind.RECOVERY], [lap.kind for lap in self.laps("9202")]
        )
        self.assertEqual(1, self.run_to_completion()["retired"])

    def test_downsampled_record_of_full_canonical_streams_is_retired(self):
        record = self.load("9203", points=POINTS)
        streams = record["activity"]["streams"]
        self.assertEqual(POINTS, len(streams["watts"]))
        record["activity"]["streams"] = {
            key: _downsample_series(values) for key, values in streams.items()
        }
        record["full_resolution"] = False
        # The analysis values were computed from the full streams.
        self.save_raw_record(record)
        self.assertLess(len(self.kv_record("9203")["activity"]["streams"]["watts"]), POINTS)
        self.assertEqual(1, self.run_to_completion()["retired"])
        self.assertIsNone(self.kv_record("9203"))

    def test_missing_lap_speed_is_refilled_before_the_record_is_retired(self):
        self.load("9204")
        original = self.lap_content_hash("9204")
        # Lap sets stored before schema v13 have no maximum speed.
        self.execute("UPDATE activity_laps SET max_speed_mps = NULL")
        self.execute(
            "UPDATE activity_detail_sets SET content_sha256 = ? "
            "WHERE detail_kind = 'laps'",
            ("f" * 64,),
        )
        counters = self.run_to_completion()
        self.assertEqual((1, 1), (counters["retired"], counters["laps_refilled"]))
        self.assertEqual([11.5, 7.25], [lap.max_speed_mps for lap in self.laps("9204")])
        self.assertEqual(original, self.lap_content_hash("9204"))

    def test_finished_pass_does_not_run_again(self):
        self.load("9205")
        self.run_to_completion()
        record = self.load("9206")
        self.assertIsNotNone(self.kv_record("9206"))
        with self.manager.unit_of_work() as db:
            self.assertTrue(self.make().run_batch(db).done)
        self.assertEqual(record["summary_sha256"], self.kv_record("9206")["summary_sha256"])


class KeptRecordTests(RetirementTestCase):
    """Every unproven record stays with canonical rows unchanged, counting its reason."""

    def assert_kept(self, reason, activity_id):
        before_kv = self.kv_rows()
        before = canonical_snapshot(self.manager)
        self.assertIn(
            legacy_detail_kv.key(activity_id), [key for key, _ in before_kv]
        )
        counters = self.run_to_completion()
        self.assertEqual(0, counters["retired"])
        self.assertEqual(1, counters[reason])
        self.assertEqual(
            1,
            sum(value for name, value in counters.items() if name != "laps_refilled"),
        )
        self.assertEqual(before_kv, self.kv_rows())
        self.assertEqual(before, canonical_snapshot(self.manager))

    def changed(self, activity_id, change):
        record = self.load(activity_id)
        change(record)
        self.save_record(record)

    def test_value_that_is_not_a_record(self):
        self.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, '[1]', ?)",
            (legacy_detail_kv.key("9300"), NOW),
        )
        self.assert_kept("invalid", "9300")

    def test_record_without_an_activity_record(self):
        record = self.load("9301")
        legacy_detail_kv.save(self.manager, "9399", {**record, "activity_id": "9399"})
        self.execute("DELETE FROM kv WHERE key = ?", (legacy_detail_kv.key("9301"),))
        self.assert_kept("no_record", "9399")

    def test_record_the_mapper_reports_issues_for(self):
        def change(record):
            record["activity"]["laps"][0]["start_time"] = "soon"

        self.changed("9302", change)
        self.assert_kept("mapping_issues", "9302")

    def test_stream_key_the_mapper_would_drop(self):
        def change(record):
            streams = record["activity"]["streams"]
            streams["temp"] = [14.0] * len(streams["time"])
            streams["temperature"] = [15.0] * len(streams["time"])

        self.changed("9303", change)
        self.assert_kept("unmapped_stream", "9303")

    def test_set_missing_from_the_canonical_tables(self):
        self.load("9304")
        self.execute("DELETE FROM activity_detail_sets WHERE detail_kind = 'laps'")
        self.assert_kept("no_canonical", "9304")

    def test_record_of_another_summary(self):
        def change(record):
            record["summary_sha256"] = "c" * 64

        self.changed("9305", change)
        self.assert_kept("fingerprint_mismatch", "9305")

    def test_stream_values_that_differ(self):
        def change(record):
            record["activity"]["streams"]["watts"][3] += 1

        self.changed("9306", change)
        self.assert_kept("streams_unproven", "9306")

    def test_stream_channel_missing_from_the_canonical_set(self):
        self.load("9307")
        self.execute("DELETE FROM activity_stream_channels WHERE channel = 'heart_rate_bpm'")
        self.assert_kept("streams_unproven", "9307")

    def test_lap_bounds_that_differ(self):
        def change(record):
            record["activity"]["laps"][1]["end_time"] = 901

        self.changed("9308", change)
        self.assert_kept("laps_mismatch", "9308")

    def test_lap_metric_that_differs(self):
        def change(record):
            record["activity"]["laps"][0]["average_watts"] = 281

        self.changed("9309", change)
        self.assert_kept("laps_mismatch", "9309")

    def test_zone_seconds_that_differ(self):
        def change(record):
            record["activity"]["icu_hr_zone_times"] = [300, 400, 201]

        self.changed("9310", change)
        self.assert_kept("zones_mismatch", "9310")

    def test_analysis_value_that_differs(self):
        def change(record):
            record["target_snapshot"] = {"frozen_at": NOW}

        self.changed("9311", change)
        self.assert_kept("analysis_mismatch", "9311")

    def test_analysis_missing_from_the_canonical_tables(self):
        self.load("9312")
        self.execute("DELETE FROM activity_detail_analysis")
        self.assert_kept("analysis_mismatch", "9312")

    def test_record_without_details_needs_a_stored_analysis(self):
        record = self.load("9313")
        self.execute("DELETE FROM activity_detail_sets")
        self.execute("DELETE FROM activity_detail_analysis")
        bare = {
            "activity_id": "9313",
            "summary_sha256": record["summary_sha256"],
            "observed_at": NOW,
            "activity": {},
        }
        legacy_detail_kv.save(self.manager, "9313", bare)
        self.assert_kept("analysis_mismatch", "9313")


class CompletedStage:
    """A canonical backfill stage that has already finished."""

    stage = "canonical"

    def run_batch(self, db):
        return BatchReport(items=0, done=True)

    def mark_failed(self, db):
        raise AssertionError("the completed stage cannot fail")


class RetirementWorkerTests(RetirementTestCase):
    def state(self):
        with self.manager.reader() as db:
            return json.loads(self.key_values.get(db, STATE_KEY))

    def drop_lap_speeds(self):
        self.execute("UPDATE activity_laps SET max_speed_mps = NULL")

    def test_assembly_retires_records_after_the_detail_backfill_copied_them(self):
        ids = ("9401", "9402")
        for activity_id in ids:
            self.load(activity_id)
        # Records of a release before the canonical tables: kv only.
        for table in ("activity_detail_sets", "activity_detail_analysis"):
            self.execute(f"DELETE FROM {table}")
        assembly = build_canonical_backfill(
            database=lambda: self.manager,
            key_values=self.key_values,
            zone_provider=lambda: None,
            maintenance_gate=MaintenanceGate(),
            clock=lambda: NOW,
        )
        assembly.worker.run_loop()
        with self.manager.reader() as db:
            self.assertEqual("complete", assembly.detail_backfill.summary(db)["status"])
            summary = assembly.detail_retirement.summary(db)
            origins = {
                row["origin"]
                for row in db.execute("SELECT origin FROM activity_detail_sets")
            }
        self.assertEqual("complete", summary["status"])
        # Run before the copy, every record would have counted ``no_canonical``.
        self.assertEqual(len(ids), summary["counters"]["retired"])
        self.assertEqual({"legacy_backfill"}, origins)
        self.assertEqual([], detail_keys(self.manager))

    def test_failed_batch_rolls_back_refills_and_deletions(self):
        for activity_id in ("9411", "9412"):
            self.load(activity_id)
        self.drop_lap_speeds()
        canonical = canonical_snapshot(self.manager)
        records = self.kv_rows()
        real = activity_detail_retirement._retire
        calls = []

        def retire(db, record, now):
            calls.append(record["activity_id"])
            if len(calls) == 2:
                raise RuntimeError("simulated retirement failure")
            return real(db, record, now)

        worker = CanonicalBackfillWorker(
            backfill=CompletedStage(),
            database=lambda: self.manager,
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
            followups=(self.make(),),
        )
        with (
            patch.object(activity_detail_retirement, "_retire", retire),
            self.assertLogs("backend.sync.canonical_backfill_worker", "ERROR"),
        ):
            worker.run_loop()
        self.assertEqual(2, len(calls))
        # The first record was refilled and deleted in the batch that rolled back.
        self.assertEqual(records, self.kv_rows())
        self.assertEqual(canonical, canonical_snapshot(self.manager))
        state = self.state()
        self.assertEqual(("failed", "", 0), (state["status"], state["cursor"], state["batches"]))
        counters = self.run_to_completion()
        self.assertEqual((2, 2), (counters["retired"], counters["laps_refilled"]))

    def test_restart_resumes_from_the_cursor_and_repeats_nothing(self):
        ids = ("9421", "9422", "9423")
        for activity_id in ids:
            self.load(activity_id)
        keys = [key for key, _ in self.kv_rows()]
        with self.manager.unit_of_work() as db:
            self.assertFalse(self.make(batch_size=1).run_batch(db).done)
        self.assertEqual(keys[0], self.state()["cursor"])
        self.assertEqual(keys[1:], [key for key, _ in self.kv_rows()])
        # A new stage instance stands in for a restart of the application.
        counters = self.run_to_completion(self.make(batch_size=1))
        self.assertEqual(len(ids), counters["retired"])
        self.assertEqual(4, self.state()["batches"])
        canonical = canonical_snapshot(self.manager)
        self.assertEqual(counters, self.run_to_completion(self.make(batch_size=1)))
        self.assertEqual(canonical, canonical_snapshot(self.manager))
        self.assertEqual([], self.kv_rows())


if __name__ == "__main__":
    unittest.main()
