import sqlite3
import unittest
from contextlib import nullcontext
from datetime import UTC, date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from activity_row_support import StoredCoverage

from backend.activities.read_service import ActivityReadService
from backend.db.schema import initialize_schema
from backend.sync.analysis_sessions import AnalysisSessionsRefreshService
from backend.sync.canonical_ingest import ingest_intervals_snapshot
from backend.sync.canonical_table_reader import CanonicalTableReader


class AnalysisSessionsRefreshTests(unittest.TestCase):
    def test_complete_window_merge_does_not_truncate_older_retained_rows(self):
        older = [{"id": str(index)} for index in range(600)]

        merged = AnalysisSessionsRefreshService._merge_activity_rows(
            [],
            older,
            date(2026, 9, 9),
            date(2026, 10, 20),
            "2026-10-20T12:00:00+00:00",
            UTC,
            truncated=False,
        )

        self.assertEqual(600, len(merged))
        self.assertEqual([row["id"] for row in older], [row["id"] for row in merged])

    def test_fetch_is_bounded_and_partial_ingest_preserves_other_snapshot_sections(
        self,
    ):
        activity = {
            "id": "intervals-1",
            "start_date_local": "2026-10-19T08:00:00",
            "type": "Ride",
            "moving_time": 3600,
            "icu_training_load": 42,
        }
        provider = Mock()
        provider.get.return_value = [activity]
        previous = {
            "synced_at": "2026-10-18T12:00:00+00:00",
            "recent_activities": [
                {"id": "stale-in-window", "start_date_local": "2026-10-10T08:00:00"},
                {"id": "older", "start_date_local": "2026-09-01T08:00:00"},
            ],
            "recent_wellness": [{"id": "wellness"}],
            "upcoming_calendar": [{"id": "event"}],
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "stale-in-window",
                        "start_date_local": "2026-10-10T08:00:00",
                    },
                    {"id": "older", "start_date_local": "2026-09-01T08:00:00"},
                ],
                "wellness": [{"id": "raw-wellness"}],
                "upcoming_calendar": [{"id": "raw-event"}],
            },
        }
        storage = Mock()
        manager = MagicMock()
        db = Mock()
        manager.unit_of_work.return_value.__enter__.return_value = db
        latest = {**previous, "concurrent_performance_refresh": "committed"}
        storage.merge_base.return_value = latest
        observer_scope = SimpleNamespace(result=None)
        observer = Mock()
        observer.observe.return_value = nullcontext(observer_scope)
        service = AnalysisSessionsRefreshService(
            config=SimpleNamespace(
                intervals_api_key="configured",
                intervals_athlete_id="athlete",
            ),
            database_manager=manager,
            provider_client=provider,
            event_publisher=Mock(),
            observer=observer,
            resync_gate=SimpleNamespace(operation=nullcontext),
            zone_provider=lambda: UTC,
            utc_now=lambda: "2026-10-20T12:00:00+00:00",
            all_sync_days=365,
            earliest_date=date(2020, 1, 1),
            snapshot_storage=storage,
        )

        with (
            patch("backend.sync.analysis_sessions.ingest_intervals_snapshot") as ingest,
            patch(
                "backend.sync.canonical_coverage_store.CanonicalCoverageStore.persist"
            ) as coverage_persist,
        ):
            result = service.refresh()

        self.assertEqual(
            (
                "/athlete/athlete/activities",
                {
                    "oldest": "2026-09-09",
                    "newest": "2026-10-20",
                    "limit": 500,
                    "offset": 0,
                },
            ),
            provider.get.call_args.args,
        )
        self.assertEqual("partial", result["status"])
        storage.merge_base.assert_called_once_with(db)
        self.assertEqual(42, result["window_days"])
        self.assertEqual(500, result["limit"])
        self.assertFalse(result["truncated"])
        ingest.assert_called_once()
        ingested = ingest.call_args.args[1]
        self.assertEqual([activity], ingested["raw_provider_data"]["activities"])
        self.assertEqual(42, ingest.call_args.kwargs["activity_days"])
        saved = storage.save.call_args.args[1]
        self.assertEqual(previous["synced_at"], saved["synced_at"])
        self.assertEqual(previous["synced_at"], saved["activities_synced_at"])
        self.assertEqual(
            ["intervals-1", "older"], [row["id"] for row in saved["recent_activities"]]
        )
        self.assertEqual(
            ["intervals-1", "older"],
            [row["id"] for row in saved["raw_provider_data"]["activities"]],
        )
        self.assertEqual(previous["recent_wellness"], saved["recent_wellness"])
        self.assertEqual("committed", saved["concurrent_performance_refresh"])
        self.assertEqual(previous["upcoming_calendar"], saved["upcoming_calendar"])
        self.assertIsNone(storage.save.call_args.kwargs["update_full_sync"])
        coverage_persist.assert_not_called()

    def test_empty_complete_window_replaces_recent_summaries_without_canonical_deletes(
        self,
    ):
        provider = Mock()
        provider.get.return_value = []
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        initialize_schema(db)
        initial = {
            "synced_at": "2026-10-18T12:00:00+00:00",
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "stale-in-window",
                        "type": "Ride",
                        "start_date_local": "2026-10-10T08:00:00",
                    },
                    {
                        "id": "first-edge",
                        "type": "Ride",
                        "start_date_local": "2026-09-09T08:00:00",
                    },
                    {
                        "id": "last-edge",
                        "type": "Ride",
                        "start_date_local": "2026-10-20T08:00:00",
                    },
                ]
            },
        }
        ingest_intervals_snapshot(
            db,
            initial,
            zone=UTC,
            activity_days=365,
            all_sync_days=365,
            earliest_date=date(2020, 1, 1),
        )
        db.commit()

        class Database:
            def unit_of_work(self):
                return nullcontext(db)

            def read_snapshot(self):
                return nullcontext(db)

        storage = Mock()
        storage.merge_base.return_value = initial
        service = AnalysisSessionsRefreshService(
            config=SimpleNamespace(
                intervals_api_key="configured", intervals_athlete_id="athlete"
            ),
            database_manager=Database(),
            provider_client=provider,
            event_publisher=Mock(),
            observer=Mock(
                observe=Mock(return_value=nullcontext(SimpleNamespace(result=None)))
            ),
            resync_gate=SimpleNamespace(operation=nullcontext),
            zone_provider=lambda: UTC,
            utc_now=lambda: "2026-10-20T12:00:00+00:00",
            all_sync_days=365,
            earliest_date=date(2020, 1, 1),
            snapshot_storage=storage,
        )

        result = service.refresh()

        saved = storage.save.call_args.args[1]
        self.assertEqual("partial", result["status"])
        self.assertEqual("2026-10-18T12:00:00+00:00", saved["activities_synced_at"])
        self.assertEqual([], saved["recent_activities"])

        class Feedback:
            def attach_to_activities(self, rows):
                return rows

        saved_reader = Mock(latest_snapshot=Mock(return_value=saved))
        read_service = ActivityReadService(
            Database(),
            saved_reader,
            CanonicalTableReader(),
            Feedback(),
            coverage=lambda: StoredCoverage(saved["activities_synced_at"]),
        )
        listed = read_service.page(today=date(2026, 10, 20), days=42)
        self.assertEqual(
            ["last-edge", "first-edge"], [row["id"] for row in listed["activities"]]
        )
        self.assertEqual("2026-10-18T12:00:00+00:00", listed["snapshot_synced_at"])

    def test_truncated_window_keeps_prior_freshness_and_never_tombstones(self):
        provider = Mock()
        provider.get.return_value = [{"id": str(index)} for index in range(500)]
        storage = Mock()
        storage.merge_base.return_value = {
            "synced_at": "2026-10-18T12:00:00+00:00",
            "activities_synced_at": "2026-10-18T12:00:00+00:00",
            "recent_activities": [],
            "raw_provider_data": {"activities": []},
        }
        manager = MagicMock()
        manager.unit_of_work.return_value.__enter__.return_value = Mock()
        service = AnalysisSessionsRefreshService(
            config=SimpleNamespace(
                intervals_api_key="configured", intervals_athlete_id="athlete"
            ),
            database_manager=manager,
            provider_client=provider,
            event_publisher=Mock(),
            observer=Mock(
                observe=Mock(return_value=nullcontext(SimpleNamespace(result=None)))
            ),
            resync_gate=SimpleNamespace(operation=nullcontext),
            zone_provider=lambda: UTC,
            utc_now=lambda: "2026-10-20T12:00:00+00:00",
            all_sync_days=365,
            earliest_date=date(2020, 1, 1),
            snapshot_storage=storage,
        )

        with (
            patch(
                "backend.sync.analysis_sessions.ingest_intervals_partial_snapshot"
            ) as partial_ingest,
            patch(
                "backend.sync.analysis_sessions.ingest_intervals_snapshot"
            ) as full_ingest,
        ):
            result = service.refresh()

        saved = storage.save.call_args.args[1]
        self.assertEqual("partial", result["status"])
        self.assertTrue(result["truncated"])
        self.assertEqual("2026-10-18T12:00:00+00:00", saved["activities_synced_at"])
        partial_ingest.assert_called_once()
        full_ingest.assert_not_called()

    def test_rejects_invalid_provider_payload_without_persisting(self):
        provider = Mock()
        provider.get.return_value = {"activities": []}
        storage = Mock()
        service = AnalysisSessionsRefreshService(
            config=SimpleNamespace(
                intervals_api_key="configured",
                intervals_athlete_id="athlete",
            ),
            database_manager=Mock(),
            provider_client=provider,
            event_publisher=Mock(),
            observer=SimpleNamespace(observe=lambda *_: nullcontext(SimpleNamespace())),
            resync_gate=SimpleNamespace(operation=nullcontext),
            zone_provider=lambda: UTC,
            utc_now=lambda: "2026-10-20T12:00:00+00:00",
            all_sync_days=365,
            earliest_date=date(2020, 1, 1),
            snapshot_storage=storage,
        )

        from backend.errors import AppError

        with self.assertRaises(AppError):
            service.refresh()

        storage.merge_base.assert_not_called()
        storage.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
