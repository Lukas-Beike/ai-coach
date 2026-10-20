"""Canonical writes of Intervals activity details: fresh loads and legacy backfill."""

import tempfile
import unittest

from canonical_detail_support import (
    INTERVALS,
    NOW,
    open_manager,
    seed_intervals_activity,
)

from backend.canonical.vocabulary import ActivityDetailOrigin, RecordingOrigin
from backend.db.activity_detail_store import detail_origins
from backend.sync.activity_detail_canonical import (
    CanonicalDetailWriter,
    DetailWriteOutcome,
)
from backend.sync.activity_details import normalize_streams

SHA = "a" * 64
STREAMS = normalize_streams(
    [
        {"type": "time", "data": [0, 1, 2]},
        {"type": "watts", "data": [200, 210, 220]},
    ]
)


def fresh_record(**extra):
    return {
        "observed_at": NOW,
        "summary_sha256": SHA,
        "session_analysis": {"aerobic": {"score": 1}},
        **extra,
    }


def legacy_record(activity_id="9001", **extra):
    return {
        "activity_id": activity_id,
        "observed_at": NOW,
        "summary_sha256": SHA,
        "full_resolution": True,
        "activity": {"streams": {"time": [0, 1, 2], "watts": [200, 210, 220]}},
        **extra,
    }


class CanonicalDetailWriterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        seed_intervals_activity(self.manager, "9001")
        self.writer = CanonicalDetailWriter()

    def fetch(self, activity_id="9001", record=None, detail=None, streams=None):
        with self.manager.unit_of_work() as db:
            return self.writer.write_fetch(
                db,
                activity_id=activity_id,
                detail=(
                    {"id": activity_id, "moving_time": 1000}
                    if detail is None
                    else detail
                ),
                streams=STREAMS if streams is None else streams,
                record=fresh_record() if record is None else record,
                now=NOW,
            )

    def legacy(self, record=None):
        with self.manager.unit_of_work() as db:
            return self.writer.write_legacy(
                db,
                record=legacy_record() if record is None else record,
                now=NOW,
            )

    def count(self, table, where="", params=()):
        with self.manager.reader() as db:
            row = db.execute(
                f"SELECT COUNT(*) AS n FROM {table} {where}", params
            ).fetchone()
        return row["n"]

    def kinds(self):
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT detail_kind AS kind FROM activity_detail_sets "
                "WHERE provider = ? AND provider_activity_id = ? ORDER BY detail_kind",
                (INTERVALS, "9001"),
            ).fetchall()
        return [row["kind"] for row in rows]

    def origins(self):
        with self.manager.reader() as db:
            return detail_origins(db, INTERVALS, "9001")

    def test_fresh_load_writes_stream_set_and_analysis(self):
        self.assertEqual(DetailWriteOutcome.WRITTEN, self.fetch().outcome)
        self.assertIn("streams", self.kinds())
        self.assertEqual({ActivityDetailOrigin.FETCH.value}, self.origins())
        self.assertEqual(1, self.count("activity_detail_analysis"))

    def test_fresh_load_without_active_record_writes_nothing(self):
        result = self.fetch(activity_id="no-such-activity")
        self.assertEqual(DetailWriteOutcome.NO_RECORD, result.outcome)
        self.assertEqual(0, self.count("activity_detail_sets"))
        self.assertEqual(0, self.count("activity_detail_analysis"))

    def test_fresh_load_without_any_payload_is_invalid(self):
        result = self.fetch(
            detail={"id": "9001"},
            streams={},
            record={"observed_at": NOW, "summary_sha256": SHA},
        )
        self.assertEqual(DetailWriteOutcome.INVALID, result.outcome)
        self.assertEqual(0, self.count("activity_detail_sets"))
        self.assertEqual(0, self.count("activity_detail_analysis"))

    def test_legacy_record_is_written_with_legacy_origin(self):
        self.assertEqual(DetailWriteOutcome.WRITTEN, self.legacy().outcome)
        self.assertEqual({ActivityDetailOrigin.LEGACY_BACKFILL.value}, self.origins())

    def test_legacy_record_is_unchanged_when_a_fresh_load_exists(self):
        self.fetch()
        self.assertEqual(DetailWriteOutcome.UNCHANGED, self.legacy().outcome)
        self.assertEqual({ActivityDetailOrigin.FETCH.value}, self.origins())

    def test_malformed_legacy_records_are_invalid(self):
        self.assertEqual(
            DetailWriteOutcome.INVALID,
            self.legacy(record=["not", "a", "dict"]).outcome,
        )
        self.assertEqual(
            DetailWriteOutcome.INVALID,
            self.legacy(record={"observed_at": NOW}).outcome,
        )
        self.assertEqual(0, self.count("activity_detail_sets"))

    def test_deleted_record_writes_nothing(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET state = 'deleted' "
                "WHERE provider = ? AND provider_activity_id = ?",
                (INTERVALS, "9001"),
            )
        self.assertEqual(DetailWriteOutcome.NO_RECORD, self.fetch().outcome)
        self.assertEqual([], self.kinds())

    def test_rewriting_the_same_fresh_load_is_unchanged(self):
        self.assertEqual(DetailWriteOutcome.WRITTEN, self.fetch().outcome)
        self.assertEqual(DetailWriteOutcome.UNCHANGED, self.fetch().outcome)
        self.assertEqual(1, self.count("activity_detail_analysis"))

    def test_refetch_without_laps_removes_the_stale_lap_set(self):
        self.fetch(
            detail={
                "id": "9001",
                "icu_intervals": [{"start_time": 0, "end_time": 60}],
            }
        )
        self.assertIn("laps", self.kinds())
        self.fetch(detail={"id": "9001", "moving_time": 1000})
        self.assertNotIn("laps", self.kinds())
        self.assertIn("streams", self.kinds())

    def test_invalid_fresh_load_keeps_the_stored_sets(self):
        self.fetch()
        before = self.kinds()
        result = self.fetch(
            detail={"id": "9001"},
            streams={},
            record={"observed_at": NOW, "summary_sha256": SHA},
        )
        self.assertEqual(DetailWriteOutcome.INVALID, result.outcome)
        self.assertEqual(before, self.kinds())

    def test_session_without_local_id_writes_sets_but_no_analysis(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET activity_id = NULL "
                "WHERE provider = ? AND provider_activity_id = ?",
                (INTERVALS, "9001"),
            )
        self.assertEqual(DetailWriteOutcome.WRITTEN, self.fetch().outcome)
        self.assertIn("streams", self.kinds())
        self.assertEqual(0, self.count("activity_detail_analysis"))

    def test_unknown_recorded_by_is_stored_as_unknown(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET recorded_by = 'mystery' "
                "WHERE provider = ? AND provider_activity_id = ?",
                (INTERVALS, "9001"),
            )
        self.fetch()
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT DISTINCT recorded_by FROM activity_detail_sets "
                "WHERE provider = ? AND provider_activity_id = ?",
                (INTERVALS, "9001"),
            ).fetchall()
        self.assertEqual(
            [RecordingOrigin.UNKNOWN.value], [row["recorded_by"] for row in rows]
        )

    def test_legacy_write_keeps_the_other_kinds(self):
        self.legacy(
            record=legacy_record(activity={"laps": [{"start_time": 0, "end_time": 60}]})
        )
        self.legacy(record=legacy_record())
        self.assertEqual(["laps", "streams"], self.kinds())

    def test_naive_observed_at_is_rejected(self):
        with self.assertRaises(ValueError):
            self.fetch(record=fresh_record(observed_at="2026-10-18T08:00:00"))
        self.assertEqual(0, self.count("activity_detail_sets"))
