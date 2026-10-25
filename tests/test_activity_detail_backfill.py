"""The one-time copy of stored activity details into the canonical detail tables."""

import json
import tempfile
import unittest

import legacy_detail_kv
from canonical_detail_support import (
    INTERVALS,
    NOW,
    open_manager,
    seed_intervals_activity,
)

from backend.activities.detail_store import ActivityDetailStore
from backend.db.repositories import KeyValueRepository
from backend.providers.intervals_activity_detail_mapping import MAPPER_VERSION
from backend.sync.activity_detail_backfill import (
    DEFAULT_BATCH_SIZE,
    STATE_KEY,
    ActivityDetailBackfill,
)
from backend.sync.activity_detail_canonical import (
    ACTIVITY_DETAIL_ANALYSIS_VERSION,
    CanonicalDetailWriter,
)
from backend.sync.canonical_backfill import BatchReport

SHA = "b" * 64
IDS = ("9101", "9102", "9103", "9104", "9105")


def legacy_record(activity_id):
    return {
        "activity_id": activity_id,
        "observed_at": NOW,
        "summary_sha256": SHA,
        "full_resolution": True,
        "activity": {"streams": {"time": [0, 1, 2], "watts": [200, 210, 220]}},
    }


class FailingWriter:
    """Delegates to the real writer and raises on one call of the pass."""

    def __init__(self, fail_on_call):
        self.inner = CanonicalDetailWriter()
        self.fail_on_call = fail_on_call
        self.calls = 0

    def write_legacy(self, db, *, record, now):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("simulated batch failure")
        return self.inner.write_legacy(db, record=record, now=now)


class ActivityDetailBackfillTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.store = ActivityDetailStore(self.manager)

    def seed(self, ids=IDS):
        for activity_id in ids:
            seed_intervals_activity(self.manager, activity_id)
            legacy_detail_kv.save(self.manager, activity_id, legacy_record(activity_id))

    def make(self, batch_size=2, writer=None):
        return ActivityDetailBackfill(
            key_values=self.key_values,
            writer=writer or CanonicalDetailWriter(),
            clock=lambda: NOW,
            batch_size=batch_size,
        )

    def run_batch(self, backfill):
        with self.manager.unit_of_work() as db:
            return backfill.run_batch(db)

    def run_to_completion(self, backfill):
        reports = []
        for _ in range(100):
            report = self.run_batch(backfill)
            reports.append(report)
            if report.done:
                return reports
        self.fail("the detail backfill did not finish")

    def summary(self, backfill):
        with self.manager.unit_of_work() as db:
            return backfill.summary(db)

    def state(self):
        with self.manager.reader() as db:
            return json.loads(self.key_values.get(db, STATE_KEY))

    def count(self, table, where="", params=()):
        with self.manager.reader() as db:
            row = db.execute(
                f"SELECT COUNT(*) AS n FROM {table} {where}", params
            ).fetchone()
        return row["n"]

    def detail_rows(self):
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT key, value, updated_at FROM kv "
                "WHERE substr(key, 1, 16) = 'activity_detail:' ORDER BY key"
            ).fetchall()
        return [(row["key"], row["value"], row["updated_at"]) for row in rows]

    def distinct_detail_ids(self):
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT DISTINCT provider_activity_id AS activity_id "
                "FROM activity_detail_sets WHERE provider = ?",
                (INTERVALS,),
            ).fetchall()
        return len(rows)

    @staticmethod
    def counted(counters):
        return sum(
            counters[name] for name in ("written", "unchanged", "no_record", "invalid")
        )

    def test_batches_follow_key_order_and_stop_on_a_short_batch(self):
        self.seed()
        reports = self.run_to_completion(self.make(batch_size=2))
        self.assertEqual([2, 2, 1], [report.items for report in reports])
        self.assertEqual([False, False, True], [report.done for report in reports])
        with self.manager.reader() as db:
            keys = [key for key, _ in ActivityDetailStore.records_after(db, "", 100)]
        self.assertEqual(sorted(keys), keys)
        self.assertEqual(len(IDS), len(keys))

    def test_exact_multiple_of_the_batch_size_needs_an_empty_final_batch(self):
        self.seed(IDS[:4])
        reports = self.run_to_completion(self.make(batch_size=2))
        self.assertEqual([2, 2, 0], [report.items for report in reports])
        self.assertEqual(BatchReport(items=0, done=True), reports[-1])

    def test_batch_size_outside_the_allowed_range_is_rejected(self):
        for batch_size in (0, 101):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                self.make(batch_size=batch_size)
        self.assertEqual(20, DEFAULT_BATCH_SIZE)

    def test_completed_pass_is_a_no_op(self):
        self.seed()
        backfill = self.make()
        self.run_to_completion(backfill)
        before = self.summary(backfill)
        self.assertEqual(BatchReport(items=0, done=True), self.run_batch(backfill))
        self.assertEqual(before, self.summary(backfill))
        self.assertEqual("complete", before["status"])

    def test_failed_batch_rolls_back_and_resumes_from_the_last_commit(self):
        self.seed(IDS[:4])
        # Call 4 is the second record of the second batch, so record 3 of that
        # batch is written and must roll back with the failure.
        failing = self.make(writer=FailingWriter(fail_on_call=4))
        self.run_batch(failing)
        with self.assertRaises(RuntimeError):
            self.run_batch(failing)
        # The rolled-back record 3 leaves no canonical rows behind.
        self.assertEqual(2, self.distinct_detail_ids())
        self.assertEqual(1, self.summary(failing)["batches"])

        backfill = self.make()
        cursor = self.state()["cursor"]
        self.assertNotEqual("", cursor)
        with self.manager.unit_of_work() as db:
            backfill.mark_failed(db)
        self.assertEqual("failed", self.summary(backfill)["status"])
        self.assertEqual(cursor, self.state()["cursor"])

        self.run_to_completion(backfill)
        summary = self.summary(backfill)
        self.assertEqual("complete", summary["status"])
        self.assertEqual(4, summary["counters"]["written"])
        self.assertEqual(4, self.distinct_detail_ids())

    def test_failure_and_state_keys_are_never_read_as_records(self):
        self.seed(IDS[:2])
        self.store.save_failure("9101", SHA, "provider said no", NOW)
        with self.manager.unit_of_work() as db:
            self.key_values.set(
                db, "activityXdetail:decoy", json.dumps(legacy_record("9199"))
            )
        with self.manager.reader() as db:
            keys = [key for key, _ in ActivityDetailStore.records_after(db, "", 100)]
        self.assertEqual(2, len(keys))
        self.assertTrue(all(key.startswith("activity_detail:") for key in keys))
        self.assertNotIn("activityXdetail:decoy", keys)

        backfill = self.make()
        self.run_to_completion(backfill)
        self.assertEqual(2, self.counted(self.summary(backfill)["counters"]))

    def test_changed_mapper_version_starts_the_pass_again(self):
        self.seed(IDS[:3])
        backfill = self.make()
        self.run_to_completion(backfill)
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY))
            state["mapper_version"] = 0
            self.key_values.set(db, STATE_KEY, json.dumps(state))
        self.run_to_completion(backfill)
        summary = self.summary(backfill)
        self.assertEqual("complete", summary["status"])
        self.assertEqual(3, self.counted(summary["counters"]))
        # The batch count restarts with the pass: one full batch, one short batch.
        self.assertEqual(2, summary["batches"])

    def test_malformed_state_restarts_the_pass(self):
        self.seed(IDS[:3])
        backfill = self.make()
        self.run_to_completion(backfill)
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, STATE_KEY, "{not json")
        self.assertEqual("pending", self.summary(backfill)["status"])
        self.run_to_completion(backfill)
        self.assertEqual("complete", self.summary(backfill)["status"])

    def test_stored_detail_records_are_never_changed(self):
        self.seed()
        before = self.detail_rows()
        self.assertEqual(len(IDS), len(before))
        self.run_to_completion(self.make())
        self.assertEqual(before, self.detail_rows())

    def test_summary_carries_no_activity_content(self):
        self.seed(IDS[:2])
        backfill = self.make()
        self.run_to_completion(backfill)
        summary = self.summary(backfill)
        self.assertEqual({"status", "batches", "counters"}, set(summary))
        rendered = json.dumps(summary)
        self.assertNotIn("9101", rendered)
        self.assertNotIn("activity", rendered)

    def test_state_records_versions_and_completion_time(self):
        self.seed(IDS[:2])
        self.run_to_completion(self.make())
        state = self.state()
        self.assertEqual(MAPPER_VERSION, state["mapper_version"])
        self.assertEqual(ACTIVITY_DETAIL_ANALYSIS_VERSION, state["analysis_version"])
        self.assertEqual(NOW, state["completed_at"])
        self.assertEqual("complete", state["status"])

    def test_orphan_detail_is_counted_as_no_record_and_kept(self):
        self.seed(IDS[:1])
        legacy_detail_kv.save(self.manager, "9999", legacy_record("9999"))
        before = self.detail_rows()
        backfill = self.make()
        self.run_to_completion(backfill)
        counters = self.summary(backfill)["counters"]
        self.assertEqual(1, counters["no_record"])
        self.assertEqual(1, counters["written"])
        self.assertEqual(before, self.detail_rows())

    def test_undecodable_detail_is_counted_as_invalid_and_kept(self):
        self.seed(IDS[:1])
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                (legacy_detail_kv.key("9998"), "{not json", NOW),
            )
        before = self.detail_rows()
        backfill = self.make()
        self.run_to_completion(backfill)
        counters = self.summary(backfill)["counters"]
        self.assertEqual(1, counters["invalid"])
        self.assertEqual(1, counters["written"])
        self.assertEqual(before, self.detail_rows())

    def test_one_record_per_batch_matches_a_single_run(self):
        self.seed(IDS[:3])
        small = self.make(batch_size=1)
        self.run_to_completion(small)
        small_summary = self.summary(small)
        small_sets = self.count("activity_detail_sets")

        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM activity_detail_analysis")
            db.execute("DELETE FROM activity_detail_sets")
            db.execute("DELETE FROM kv WHERE key = ?", (STATE_KEY,))
        single = self.make()
        self.run_to_completion(single)
        single_summary = self.summary(single)

        self.assertEqual(small_summary["counters"], single_summary["counters"])
        self.assertEqual(small_sets, self.count("activity_detail_sets"))
        # Three one-record batches, then the empty batch that marks the end.
        self.assertEqual(4, small_summary["batches"])

    def test_backfill_writes_canonical_rows_for_the_seeded_activity(self):
        self.seed(IDS[:2])
        self.run_to_completion(self.make())
        self.assertGreater(
            self.count(
                "activity_detail_sets",
                "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
                (INTERVALS, "9101", "streams"),
            ),
            0,
        )
