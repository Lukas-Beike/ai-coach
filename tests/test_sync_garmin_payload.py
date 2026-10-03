import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.providers.garmin import _gear_inventory
from backend.sync.garmin import GarminPayloadService
from backend.sync.state import SyncStateRepository


class GarminPayloadServiceTests(unittest.TestCase):
    def collection_payload(self, start, end, *, failed=None):
        sources = ("activities", "sleep", "hrv", "daily_stats", "resting_hr")
        return {
            "start": start, "end": end, "synced_at": f"{end}T12:00:00",
            "errors": [{"source": failed}] if failed else [],
            "provider_sync": {"pagination": {
                source: {"complete": source != failed} for source in sources
            }},
            **{source: [] for source in sources},
        }

    def test_initial_recent_import_then_regular_two_day_refresh(self):
        self.assertEqual(self.service.automatic_sync_days(2), 60)
        seed = self.service.prepare_remote(self.collection_payload("2026-07-23", "2026-09-20"))
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 2)
        self.assertEqual(seed["source_freshness"]["sleep"]["synced_start"], "2026-07-23")

    def test_partial_success_does_not_advance_failed_collection(self):
        seed = self.service.prepare_remote(self.collection_payload("2026-07-13", "2026-09-10"))
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 11)
        partial = self.service.prepare_remote(self.collection_payload("2026-09-09", "2026-09-20", failed="sleep"))
        self.store_garmin_snapshot(partial)
        self.assertEqual(partial["source_freshness"]["hrv"]["synced_end"], "2026-09-20")
        self.assertEqual(partial["source_freshness"]["sleep"]["synced_end"], "2026-09-10")
        self.assertEqual(self.service.automatic_sync_days(2), 11)
        completed = self.service.prepare_remote(self.collection_payload("2026-09-09", "2026-09-20"))
        self.store_garmin_snapshot(completed)
        self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_next_calendar_day_still_needs_only_two_days(self):
        seed = self.service.prepare_remote(self.collection_payload("2026-07-22", "2026-09-19"))
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_unavailable_optional_collection_does_not_force_repeated_initial_import(self):
        payload = self.collection_payload("2026-07-23", "2026-09-20")
        for source in ("daily_stats", "resting_hr"):
            del payload[source]
            del payload["provider_sync"]["pagination"][source]
        self.store_garmin_snapshot(self.service.prepare_remote(payload))
        self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_failed_initial_recovery_is_retried_despite_activity_backfill(self):
        seed = self.service.prepare_remote(self.collection_payload("2026-07-23", "2026-09-20", failed="hrv"))
        self.store_garmin_snapshot(seed)
        historical = self.service.prepare_remote({
            "start": "2026-01-01", "end": "2026-03-31", "synced_at": "2026-09-20T13:00:00",
            "activities": [], "provider_sync": {"pagination": {"activities": {"complete": True}}},
        })
        self.store_garmin_snapshot(historical)
        self.assertEqual(self.service.automatic_sync_days(2), 60)
        self.assertEqual(historical["source_freshness"]["activities"]["synced_end"], "2026-09-20")

    def test_long_outage_is_bounded_and_disjoint_windows_are_not_called_continuous(self):
        seed = self.service.prepare_remote(self.collection_payload("2025-01-01", "2025-03-01"))
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 90)
        self.assertEqual(
            self.service.automatic_sync_window(2), (90, date(2025, 5, 29))
        )

    def test_long_outage_catches_up_in_contiguous_bounded_windows(self):
        seed = self.service.prepare_remote(
            self.collection_payload("2025-01-01", "2025-03-01")
        )
        self.store_garmin_snapshot(seed)
        windows = []
        while True:
            days, end_date = self.service.automatic_sync_window(2)
            window_end = end_date or date(2026, 9, 20)
            window_start = window_end - timedelta(days=days - 1)
            if windows:
                self.assertLessEqual(window_start, windows[-1][1] + timedelta(days=1))
            windows.append((window_start, window_end))
            result = self.service.prepare_remote(
                self.collection_payload(window_start.isoformat(), window_end.isoformat())
            )
            self.store_garmin_snapshot(result)
            if end_date is None:
                break
        self.assertEqual(windows[-1][1], date(2026, 9, 20))
        self.assertEqual(self.service.automatic_sync_window(2), (2, None))

    def test_gear_collection_uses_reported_stats_and_does_not_publish_partial_inventory(self):
        client = SimpleNamespace(
            get_user_profile=lambda: {"id": 123, "userData": {}},
            get_gear=lambda profile: [{"gearUUID": "one", "gearName": "Bike"}, {"gearUUID": "two", "gearName": "Shoes"}],
            get_gear_stats=lambda identity: {"totalDistance": 2000 if identity == "one" else 3000},
        )
        call = lambda service, operation, fetch, details: fetch()
        result = _gear_inventory(client, call)
        self.assertEqual([row["stats"]["totalDistance"] for row in result], [2000, 3000])
        def fail_stats(identity):
            raise RuntimeError("Synthetic unavailable")
        client.get_gear_stats = fail_stats
        with self.assertRaises(RuntimeError):
            _gear_inventory(client, call)

    def test_gear_collection_uses_top_level_profile_id(self):
        client = SimpleNamespace(
            get_user_profile=lambda: {"id": 123, "userData": {"displayName": "Athlete"}},
            get_gear=Mock(return_value=[{"gearUUID": "one", "gearName": "Bike"}]),
            get_gear_stats=lambda identity: {"totalDistance": 2000},
        )
        call = lambda service, operation, fetch, details: fetch()
        self.assertEqual(_gear_inventory(client, call)[0]["gearUUID"], "one")
        client.get_gear.assert_called_once_with(123)
        client.get_user_profile = lambda: {"userData": {}}
        with self.assertRaisesRegex(ValueError, "gear profile is unavailable"):
            _gear_inventory(client, call)
        client.get_gear.assert_called_once_with(123)

    def test_garmin_gear_empty_inventory_replaces_old_and_failed_read_preserves_it(self):
        self.store_garmin_snapshot({"gear": [{"gearUUID": "one", "stats": {"totalDistance": 2000}}]})
        failed = self.service.prepare_remote({"synced_at": "2026-09-20T10:00:00", "errors": [{"source": "gear", "message": "Synthetic failure"}]})
        self.assertEqual(failed["gear"][0]["gearUUID"], "one")
        self.assertEqual(failed["source_freshness"]["gear"]["freshness"], "stale")
        empty = self.service.prepare_remote({"synced_at": "2026-09-20T11:00:00", "gear": [], "errors": []})
        self.assertEqual(empty["gear"], [])
        self.assertEqual(empty["source_freshness"]["gear"]["freshness"], "current")

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
