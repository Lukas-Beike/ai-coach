import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.sync.garmin import GarminPayloadService
from backend.sync.state import SyncStateRepository


class GarminPayloadServiceTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.database = DatabaseManager(
            Path(temporary_directory.name) / "test.sqlite3",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.database.close)
        self.key_values = KeyValueRepository(lambda: "2026-09-20T12:00:00")
        self.snapshots = SnapshotRepository()
        self.sync_state = SyncStateRepository(
            self.database,
            self.key_values,
            self.snapshots,
            lambda: "2026-09-20T12:00:00",
        )
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.service = GarminPayloadService(
            self.database,
            self.key_values,
            self.sync_state,
            lambda: date(2026, 9, 20),
        )

    def store_garmin_snapshot(self, payload):
        serialized = payload if isinstance(payload, str) else json.dumps(payload)
        with self.database.unit_of_work() as db:
            self.key_values.set(db, "garmin_snapshot", serialized)

    def store_intervals_snapshot(self, activities):
        self.sync_state.save_snapshot(
            {"synced_at": "2026-09-20T11:00:00", "recent_activities": activities}
        )

    def test_snapshot_returns_empty_for_missing_invalid_and_non_object_json(self):
        self.assertEqual(self.service.snapshot(), {})
        self.store_garmin_snapshot("not-json")
        self.assertEqual(self.service.snapshot(), {})
        self.store_garmin_snapshot("[]")
        self.assertEqual(self.service.snapshot(), {})

    def test_fixture_merges_partial_history_and_preserves_raw_records(self):
        intervals = {
            "id": "intervals-canonical",
            "start_date_local": "2026-09-19T08:00:00",
            "type": "Ride",
            "moving_time": 3600,
            "distance": 30000,
        }
        self.store_intervals_snapshot([intervals])
        previous = {
            "start": "2026-09-10",
            "sleep": [{"calendarDate": "2026-09-18", "sleepingSeconds": 19000}],
            "source_freshness": {
                "sleep": {
                    "freshness": "current",
                    "fetched_at": "2026-09-18T10:00:00",
                    "observed_at": "2026-09-18",
                }
            },
            "sport_max_hr": {"running": 196},
            "morning_body_battery": {"status": "ready", "attempts": 2},
            "performance_history": [{"date": "2026-09-14", "metrics": {"ftp": 300}}],
        }
        self.store_garmin_snapshot(previous)
        first_activity = {
            "activityId": 101,
            "external_id": "shared-external-id",
            "startTimeLocal": "2026-09-19 08:00:00",
            "activityType": {"typeKey": "cycling"},
            "duration": 3600,
            "distance": 30000,
            "maxHR": 190,
            "garmin_specific": {"sample": "preserved-a"},
        }
        second_activity = {
            **first_activity,
            "activityId": 102,
            "maxHR": 205,
            "garmin_specific": {"sample": "preserved-b"},
        }
        payload = {
            "synced_at": "2026-09-20T10:00:00",
            "start": "2026-09-15",
            "end": "2026-09-20",
            "errors": [{"source": "sleep", "message": "synthetic partial read"}],
            "sleep": [{"calendarDate": "2026-09-20", "sleepingSeconds": 20000}],
            "activities": [first_activity, second_activity],
            "performance_history": [{"date": "2026-09-15", "metrics": {"ftp": 310}}],
        }

        result = self.service.prepare_fixture(payload)

        self.assertIs(result, payload)
        self.assertEqual(payload["start"], "2026-09-10")
        self.assertEqual(payload["source_freshness"]["sleep"]["freshness"], "partial")
        self.assertEqual(
            [record["calendarDate"] for record in payload["sleep"]],
            ["2026-09-20", "2026-09-18"],
        )
        self.assertEqual(payload["activities"], [first_activity, second_activity])
        self.assertEqual(
            payload["activities"][1]["garmin_specific"], {"sample": "preserved-b"}
        )
        self.assertEqual(
            payload["activity_matches"],
            [
                {
                    "garmin_activity_id": 101,
                    "intervals_activity_id": "intervals-canonical",
                },
                {
                    "garmin_activity_id": 102,
                    "intervals_activity_id": "intervals-canonical",
                },
            ],
        )
        self.assertEqual(payload["sport_max_hr"], {"cycling": 205, "running": 196})
        self.assertEqual(
            payload["morning_body_battery"], {"status": "ready", "attempts": 2}
        )
        self.assertEqual(
            payload["performance_history"],
            [
                {"date": "2026-09-14", "metrics": {"ftp": 300}},
                {"date": "2026-09-15", "metrics": {"ftp": 310}},
                {"date": "2026-09-19", "metrics": {"cycling_max_hr_bpm": 205}},
            ],
        )
        self.assertEqual(
            payload["provider_sync"],
            {"pagination": {"fixture": {"windows": 1, "records": 2, "complete": True}}},
        )

    def test_remote_deduplicates_external_ids_before_max_hr_and_keeps_match_ids(self):
        intervals = {
            "id": "intervals-run",
            "start_date_local": "2026-09-19T08:00:00",
            "type": "Run",
            "moving_time": 1800,
            "distance": 8000,
        }
        self.store_intervals_snapshot([intervals])
        self.store_garmin_snapshot({"sport_max_hr": {"cycling": 188}})
        first_activity = {
            "external_id": "same-api-id",
            "startTimeLocal": "2026-09-18 08:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 1800,
            "distance": 8000,
            "maxHR": 190,
            "garmin_specific": {"sample": "first"},
        }
        second_activity = {
            **first_activity,
            "maxHR": 210,
            "garmin_specific": {"sample": "second"},
        }
        matching_activity = {
            "activityId": 203,
            "startTimeLocal": "2026-09-19 08:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 1800,
            "distance": 8000,
        }
        matching_without_id = {
            "startTimeLocal": "2026-09-19 08:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 1800,
            "distance": 8000,
        }
        payload = {
            "synced_at": "2026-09-20T10:00:00",
            "errors": [],
            "provider_sync": {"pagination": {"activities": {"complete": True}}},
            "activities": [
                first_activity,
                second_activity,
                matching_activity,
                matching_without_id,
            ],
        }

        result = self.service.prepare_remote(payload)

        self.assertIs(result, payload)
        self.assertEqual(
            payload["activities"],
            [first_activity, matching_activity, matching_without_id],
        )
        self.assertEqual(
            payload["activity_matches"],
            [
                {
                    "garmin_activity_id": 203,
                    "intervals_activity_id": "intervals-run",
                },
                {"garmin_activity_id": None, "intervals_activity_id": "intervals-run"},
            ],
        )
        self.assertEqual(payload["sport_max_hr"], {"cycling": 188, "running": 190})
        self.assertEqual(
            self.sync_state.latest_snapshot()["recent_activities"], [intervals]
        )

    def test_activity_matches_preserve_pairs_when_either_id_is_missing(self):
        interval_activities = [
            {
                "start_date_local": "2026-09-17T08:00:00",
                "type": "Run",
                "moving_time": 1800,
                "distance": 8000,
            },
            {
                "id": "intervals-id",
                "start_date_local": "2026-09-18T08:00:00",
                "type": "Run",
                "moving_time": 1800,
                "distance": 8000,
            },
            {
                "start_date_local": "2026-09-19T08:00:00",
                "type": "Run",
                "moving_time": 1800,
                "distance": 8000,
            },
        ]
        self.store_intervals_snapshot(interval_activities)
        payload = {
            "synced_at": "2026-09-20T10:00:00",
            "errors": [],
            "provider_sync": {"pagination": {"activities": {"complete": True}}},
            "activities": [
                {
                    "startTimeLocal": "2026-09-17 08:00:00",
                    "activityType": {"typeKey": "running"},
                    "duration": 1800,
                    "distance": 8000,
                },
                {
                    "startTimeLocal": "2026-09-18 08:00:00",
                    "activityType": {"typeKey": "running"},
                    "duration": 1800,
                    "distance": 8000,
                },
                {
                    "activityId": 301,
                    "startTimeLocal": "2026-09-19 08:00:00",
                    "activityType": {"typeKey": "running"},
                    "duration": 1800,
                    "distance": 8000,
                },
            ],
        }

        self.service.prepare_remote(payload)

        self.assertEqual(
            payload["activity_matches"],
            [
                {"garmin_activity_id": None, "intervals_activity_id": None},
                {"garmin_activity_id": None, "intervals_activity_id": "intervals-id"},
                {"garmin_activity_id": 301, "intervals_activity_id": None},
            ],
        )


if __name__ == "__main__":
    unittest.main()
