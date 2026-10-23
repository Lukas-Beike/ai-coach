"""Compact activity analyses read canonically equal the legacy kv reads."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from activity_row_support import FixedActivityRows
from canonical_detail_support import INTERVALS, NOW, ZONE, open_manager

from backend.activities.detail_analysis_reads import (
    analysis_summaries,
    calendar_profiles,
)
from backend.activities.detail_store import ActivityDetailStore
from backend.providers.canonical_plans import intervals_snapshot_ingest_plan
from backend.sync import activity_details
from backend.sync.activity_detail_canonical import (
    ACTIVITY_DETAIL_ANALYSIS_VERSION,
    CanonicalDetailWriter,
)
from backend.sync.activity_details import ActivityDetailRefreshService
from backend.sync.canonical_ingest import ingest_plan

COUNT = 120
LIMIT = 100
BASE = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
NO_AEROBIC = "aerobic-none"


def _activity_id(index: int) -> str:
    return f"i{index:03d}"


def _observed(index: int) -> str:
    # Distinct instants that do not follow the activity order.
    return (BASE + timedelta(minutes=(index * 37) % COUNT)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _streams(index: int) -> list[dict]:
    time = list(range(120))
    if index % 4 == 1:  # Analysis only: no sensor stream, so no calendar profile.
        return [{"type": "time", "data": time}]
    kind = "watts" if index % 3 else "heartrate"
    return [
        {"type": "time", "data": time},
        {"type": kind, "data": [100 + index + step % 7 for step in time]},
    ]


class AnalysisReadsTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = open_manager(self.directory.name)
        self.addCleanup(self.manager.close)
        self.store = ActivityDetailStore(self.manager)
        self.ids = [_activity_id(index) for index in range(COUNT)]
        self.seed()
        self.refresh_all()

    def seed(self):
        activities = [
            {
                "id": activity_id,
                "name": f"Ride {activity_id}",
                "start_date_local": f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}T07:00:00",
                "type": "Ride",
            }
            for index, activity_id in enumerate(self.ids)
        ]
        snapshot = {
            "synced_at": NOW,
            "upcoming_calendar": [],
            "provider_sync": {
                "calendar_window": {"start": "2026-09-21", "end": "2026-09-30"},
                "pagination": {},
            },
            "raw_provider_data": {"activities": activities},
        }
        with self.manager.unit_of_work() as db:
            ingest_plan(
                db,
                intervals_snapshot_ingest_plan(snapshot, zone=ZONE),
                retrieved_at=datetime.fromisoformat(NOW),
                deletion_window=None,
                zone=ZONE,
            )

    def refresh_all(self):
        by_path = {}
        for index, activity_id in enumerate(self.ids):
            by_path[f"/activity/{activity_id}"] = {
                "id": activity_id,
                "type": "Ride",
                "moving_time": 600,
            }
            by_path[f"/activity/{activity_id}/streams.json"] = _streams(index)
        api = Mock()
        api.get.side_effect = lambda path, params=None: by_path[path]
        clock = {"now": "", "index": 0}
        service = ActivityDetailRefreshService(
            api_client=api,
            database_manager=self.manager,
            row_reader=FixedActivityRows([{"id": item} for item in self.ids]),
            store=self.store,
            utc_now=lambda: clock["now"],
            configured=True,
            canonical=CanonicalDetailWriter(),
        )
        real = activity_details.aerobic_analysis

        def aerobic(activity, **kwargs):
            return None if clock["index"] % 5 == 2 else real(activity, **kwargs)

        with patch.object(activity_details, "aerobic_analysis", aerobic):
            for index, activity_id in enumerate(self.ids):
                clock.update(now=_observed(index), index=index)
                service.refresh(activity_id)

    def old_reads(self):
        return self.store.calendar_profiles(), self.store.analysis_summaries()

    def new_reads(self):
        return calendar_profiles(self.manager), analysis_summaries(self.manager)

    def assert_matches_kv(self, expected=None):
        old_profiles, old_summaries = expected or self.old_reads()
        profiles, summaries = self.new_reads()
        self.assertEqual(list(old_profiles), list(profiles))
        self.assertEqual(old_profiles, profiles)
        self.assertEqual(
            [row["activity_id"] for row in old_summaries],
            [row["activity_id"] for row in summaries],
        )
        for old, new in zip(old_summaries, summaries, strict=True):
            self.assertEqual(old, new)
        return old_profiles, old_summaries


class CanonicalAnalysisReadTests(AnalysisReadsTestCase):
    def test_reads_equal_the_kv_reads(self):
        profiles, summaries = self.assert_matches_kv()
        # The fixture covers the filters and the limit.
        self.assertGreater(len(profiles), 10)
        self.assertGreater(len(summaries), 10)
        with self.manager.reader() as db:
            count = db.execute(
                "SELECT COUNT(*) AS n FROM activity_detail_analysis"
            ).fetchone()["n"]
        self.assertEqual(COUNT, count)
        self.assertLess(len(summaries), LIMIT)
        self.assertLess(len(profiles), len(summaries))

    def test_payload_keeps_summary_hash_and_observation_time(self):
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT a.analysis_version, a.payload FROM activity_detail_analysis a "
                "JOIN activity_records r ON r.activity_id = a.activity_id "
                "WHERE r.provider = ? AND r.provider_activity_id = ?",
                (INTERVALS, self.ids[5]),
            ).fetchone()
        payload = json.loads(row["payload"])
        self.assertEqual(ACTIVITY_DETAIL_ANALYSIS_VERSION, row["analysis_version"])
        self.assertEqual(_observed(5), payload["observed_at"])
        self.assertEqual(
            self.store.get(self.ids[5])["summary_sha256"], payload["summary_sha256"]
        )

    def test_legacy_copy_stores_the_same_metadata(self):
        record = self.store.get(self.ids[7])
        with self.manager.unit_of_work() as db:
            db.execute(
                "DELETE FROM activity_detail_analysis WHERE activity_id = "
                "(SELECT activity_id FROM activity_records WHERE provider_activity_id = ?)",
                (self.ids[7],),
            )
            db.execute(
                "DELETE FROM activity_detail_sets WHERE provider_activity_id = ?",
                (self.ids[7],),
            )
            CanonicalDetailWriter().write_legacy(db, record=record, now=NOW)
            payload = json.loads(
                db.execute(
                    "SELECT payload FROM activity_detail_analysis a JOIN activity_records r "
                    "ON r.activity_id = a.activity_id WHERE r.provider_activity_id = ?",
                    (self.ids[7],),
                ).fetchone()["payload"]
            )
        self.assertEqual(record["observed_at"], payload["observed_at"])
        self.assertEqual(record["summary_sha256"], payload["summary_sha256"])

    def test_rows_without_the_metadata_fall_back_to_the_stored_sets(self):
        expected = self.old_reads()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_detail_analysis SET payload = "
                "json_remove(payload, '$.observed_at', '$.summary_sha256')"
            )
        profiles, summaries = self.new_reads()
        # Hash and ordering come from the detail sets; the time is the fetch time.
        self.assertEqual(list(expected[0]), list(profiles))
        with self.manager.reader() as db:
            with_sets = {
                row["provider_activity_id"]
                for row in db.execute(
                    "SELECT DISTINCT provider_activity_id FROM activity_detail_sets"
                )
            }
        self.assertTrue(with_sets)
        for old, new in zip(expected[1], summaries, strict=True):
            self.assertEqual(old["activity_id"], new["activity_id"])
            if old["activity_id"] in with_sets:
                self.assertEqual(old["summary_sha256"], new["summary_sha256"])

    def test_offsets_order_by_instant_not_by_text(self):
        # 11:00:30+02:00 is 09:00:30Z, but sorts after every "10:..Z" as text.
        target = next(_activity_id(index) for index in range(COUNT) if index % 5 != 2)
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_detail_analysis SET payload = "
                "json_set(payload, '$.observed_at', ?) WHERE activity_id = "
                "(SELECT activity_id FROM activity_records WHERE provider_activity_id = ?)",
                ("2026-10-02T11:00:30+02:00", target),
            )
        rows = analysis_summaries(self.manager)
        instants = [datetime.fromisoformat(row["observed_at"]) for row in rows]
        self.assertEqual(sorted(instants, reverse=True), instants)

    def test_unlinked_kv_records_no_longer_use_limit_slots(self):
        expected_ids = [row["activity_id"] for row in self.old_reads()[1]]
        ghost = json.loads(json.dumps(self.store.get(self.ids[0])))
        ghost["activity_id"] = "ghost"
        ghost["observed_at"] = "2026-10-03T00:00:00Z"
        self.store.save("ghost", ghost)
        old_ids = [row["activity_id"] for row in self.store.analysis_summaries()]
        self.assertIn("ghost", old_ids)
        new_ids = [row["activity_id"] for row in analysis_summaries(self.manager)]
        self.assertNotIn("ghost", new_ids)
        self.assertEqual(expected_ids, new_ids)


class KvFallbackReadTests(AnalysisReadsTestCase):
    def test_activities_without_a_canonical_analysis_come_from_kv(self):
        expected = self.old_reads()
        missing = {self.ids[3], self.ids[40], self.ids[118]}
        with self.manager.unit_of_work() as db:
            for activity_id in missing:
                db.execute(
                    "DELETE FROM activity_detail_analysis WHERE activity_id = "
                    "(SELECT activity_id FROM activity_records "
                    "WHERE provider_activity_id = ?)",
                    (activity_id,),
                )
        self.assert_matches_kv(expected)

    def test_every_analysis_missing_equals_the_kv_reads(self):
        expected = self.old_reads()
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM activity_detail_analysis")
        self.assert_matches_kv(expected)

    def test_canonical_rows_alone_equal_the_kv_reads(self):
        expected = self.old_reads()
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM kv WHERE key LIKE 'activity_detail:%'")
        self.assertIsNone(self.store.get(self.ids[0]))
        self.assert_matches_kv(expected)


if __name__ == "__main__":
    unittest.main()
