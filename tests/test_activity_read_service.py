import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date

from activity_row_support import SnapshotActivityRows
from canonical_detail_support import add_session_record, open_manager

from backend.activities.activity_reference import ActivityReferences
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.http_api.compact_activity_rows import CompactActivityRows
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.snapshot_reader import SnapshotRepositoryReader

INTERVALS = ProviderId.INTERVALS
LEGACY_KEYS = {
    "activity",
    "session_analysis",
    "activity_id",
    "local_activity_id",
    "snapshot_synced_at",
}


class _Manager:
    @contextmanager
    def unit_of_work(self):
        yield object()

    def reader(self):
        return self.unit_of_work()

    read_snapshot = reader


class _Snapshots:
    def __init__(self, snapshot):
        self.payload = json.dumps(snapshot)

    def latest_payload(self, _db):
        return self.payload

    def latest_snapshot(self, _db):
        return json.loads(self.payload)


class _Feedback:
    def __init__(self):
        self.rows = [{"activity_id": "new", "notes": "good"}]

    def list(self, _limit=100):
        return self.rows

    def attach_to_activities(self, activities):
        by_id = {row["activity_id"]: row for row in self.rows}
        return [
            {
                **item,
                **(
                    {"activity_feedback": by_id[str(item["id"])]}
                    if str(item.get("id")) in by_id
                    else {}
                ),
            }
            for item in activities
        ]


class _NoObservations:
    def observations(self, _db, _kind, *, start=None, end=None, sport=None):
        return ()


class _DatedRows:
    """Raw activity rows that honour the start bound and record each read."""

    def __init__(self, rows):
        self.rows = rows
        self.starts = []
        self.units = []

    def activity_rows(self, db, *, start=None, end=None, limit=None):
        self.starts.append(start)
        self.units.append(db)
        return tuple(
            row
            for row in self.rows
            if start is None or row["start_date_local"][:10] >= start.isoformat()
        )


class _FailedDetails:
    def failures(self, activity_ids):
        ids = set(activity_ids)
        return {"old": {"message": "Detaildaten fehlerhaft."}} if "old" in ids else {}


class ActivityReadServiceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        add_session_record(
            self.manager, INTERVALS, "new", "act_new", sport="run", name="Morning run"
        )
        add_session_record(
            self.manager, INTERVALS, "old", "act_old", sport="run", name="Winter run"
        )

    def detail_service(self, snapshot, **kwargs):
        """Serve details from the canonical sessions stored in ``setUp``."""
        return ActivityAnalysisReadService(
            self.manager,
            _Snapshots(snapshot),
            CompactActivityRows(SnapshotActivityRows(_Snapshots(snapshot))),
            _Feedback(),
            references=ActivityReferences(self.manager),
            session_records=CanonicalTableReader().session_activities,
            **kwargs,
        )

    def service(self, detail_store=None):
        snapshot = {
            "synced_at": "2026-09-20T08:00:00+00:00",
            "athlete": {},
            "recent_wellness": [],
            "recent_activities": [
                {"id": "old", "start_date_local": "2026-09-18T08:00:00", "type": "Run"},
                {"id": "new", "start_date_local": "2026-09-20T08:00:00", "type": "Run"},
                "invalid",
            ],
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "old",
                        "type": "Run",
                        "start_date_local": "2026-09-18T08:00:00",
                    },
                    {
                        "id": "new",
                        "name": "Morning run",
                        "type": "Run",
                        "start_date_local": "2026-09-20T08:00:00",
                    },
                ]
            },
        }
        return ActivityAnalysisReadService(
            _Manager(),
            _Snapshots(snapshot),
            CompactActivityRows(SnapshotActivityRows(_Snapshots(snapshot))),
            _Feedback(),
            detail_store,
        )

    def test_page_keeps_activities_with_failed_details_and_names_the_error(self):
        page = self.service(_FailedDetails()).page(today=date(2026, 9, 20))
        self.assertEqual(
            {"new": None, "old": "Detaildaten fehlerhaft."},
            {item["id"]: item["detail_error"] for item in page["activities"]},
        )

    def test_page_filters_orders_attaches_feedback_and_uses_cursor(self):
        service = self.service()
        page = service.page(limit=1, days=3, today=date(2026, 9, 20))
        self.assertEqual(["new"], [item["id"] for item in page["activities"]])
        self.assertEqual("good", page["activities"][0]["activity_feedback"]["notes"])
        second = service.page(page["next_cursor"], 1, 3, today=date(2026, 9, 20))
        self.assertEqual(["old"], [item["id"] for item in second["activities"]])
        self.assertIsNone(second["next_cursor"])

    def test_recent_filters_by_explicit_today_without_mutating_snapshot(self):
        service = self.service()
        before = service._snapshot()
        result = service.recent(days=1, today=date(2026, 9, 20))
        self.assertEqual(["new"], [item["id"] for item in result["activities"]])
        self.assertEqual(before, service._snapshot())

    def test_detail_is_bounded_and_includes_feedback(self):
        snapshot = self.service()._snapshot()
        result = self.detail_service(snapshot).detail(
            "new", garmin_snapshot={}, profile={}, today=date(2026, 9, 20)
        )
        self.assertTrue(result["ok"])
        self.assertEqual("activity_detail.v1", result["contract"])
        self.assertEqual("act_new", result["session"]["activity_id"])
        self.assertEqual("Morning run", result["session"]["name"])
        self.assertEqual("good", result["activity_feedback"]["notes"])
        self.assertEqual(
            "bounded sanitized activity_detail.v1 document of exactly one local "
            "session; providers: Intervals.icu; recorded by: garmin",
            result["data_scope"],
        )
        self.assertFalse(LEGACY_KEYS & set(result))
        self.assertEqual(result, self.detail_service(snapshot).detail(
            "act_new", garmin_snapshot={}, profile={}, today=date(2026, 9, 20)
        ))

    def test_detail_reads_an_activity_older_than_the_performance_window(self):
        snapshot = {"synced_at": "2026-09-20T08:00:00+00:00", "athlete": {}}
        rows = _DatedRows(
            [
                {"id": "new", "type": "Run", "start_date_local": "2026-09-20T08:00:00"},
                {
                    "id": "old",
                    "name": "Winter run",
                    "type": "Run",
                    "start_date_local": "2024-01-10T08:00:00",
                    "average_speed": 3.1,
                },
            ]
        )
        service = self.detail_service(
            snapshot,
            canonical=CanonicalPerformanceSource(
                database_manager=_Manager,
                observation_reader=_NoObservations,
                activity_rows=lambda: rows,
            ),
        )
        today = date(2026, 9, 20)
        recent = service.detail("new", garmin_snapshot={}, profile={}, today=today)
        self.assertEqual("act_new", recent["session"]["activity_id"])
        self.assertEqual([date(2025, 9, 21)], rows.starts)
        old = service.detail("old", garmin_snapshot={}, profile={}, today=today)
        # The current summary row of the old activity fills its summary scalars.
        self.assertEqual(3.1, old["metrics"]["avg_speed_mps"]["value"])
        self.assertTrue(old["activity_validation"]["available"])
        self.assertEqual([date(2025, 9, 21), date(2025, 9, 21), None], rows.starts)
        # The full-history lookup shares the read snapshot of the windowed read.
        self.assertIs(rows.units[1], rows.units[2])
        with self.assertRaises(AppError) as missing:
            service.detail("missing", garmin_snapshot={}, profile={}, today=today)
        self.assertEqual("activity_details_not_found", missing.exception.reason)
        # An unknown session is rejected before any summary row is read.
        self.assertEqual(3, len(rows.starts))

    def test_detail_rejects_invalid_or_missing_activity(self):
        service = self.detail_service(self.service()._snapshot())
        with self.assertRaises(AppError) as invalid:
            service.detail("", garmin_snapshot={}, profile={}, today=date(2026, 9, 20))
        self.assertEqual("invalid_activity_request", invalid.exception.reason)
        self.assertEqual(400, invalid.exception.status)
        for missing_id in ("missing", "act_missing"):
            with self.assertRaises(AppError) as missing:
                service.detail(
                    missing_id, garmin_snapshot={}, profile={}, today=date(2026, 9, 20)
                )
            self.assertEqual("activity_details_not_found", missing.exception.reason)
            self.assertEqual(404, missing.exception.status)
            self.assertEqual(
                "Diese Aktivität ist lokal nicht vorhanden.", str(missing.exception)
            )

    def test_snapshot_reader_preserves_provider_provenance_and_freshness(self):
        snapshot = {
            "synced_at": "2026-09-20T08:00:00+00:00",
            "source_freshness": {"intervals": {"freshness": "current"}},
            "provider_sync": {"source": "intervals", "cursor": "synthetic"},
            "recent_activities": [],
        }
        service = ActivityAnalysisReadService(
            _Manager(),
            SnapshotRepositoryReader(_Snapshots(snapshot)),
            CompactActivityRows(SnapshotActivityRows(_Snapshots(snapshot))),
            _Feedback(),
        )
        self.assertEqual(service._snapshot(), snapshot)

    def test_activity_refresh_timestamp_is_independent_of_performance_refresh(self):
        snapshot = {
            "synced_at": "2026-10-20T12:00:00+00:00",
            "activities_synced_at": "2026-10-19T12:00:00+00:00",
            "recent_activities": [],
        }
        service = ActivityAnalysisReadService(
            _Manager(),
            SnapshotRepositoryReader(_Snapshots(snapshot)),
            CompactActivityRows(SnapshotActivityRows(_Snapshots(snapshot))),
            _Feedback(),
        )

        synced_at, _activities = service._read()

        self.assertEqual("2026-10-19T12:00:00+00:00", synced_at)


if __name__ == "__main__":
    unittest.main()
