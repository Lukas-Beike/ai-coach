import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.providers.garmin import _collect_optional_metric, _gear_inventory
from backend.sync.garmin import GarminPayloadService
from backend.sync.state import SyncStateRepository


class GarminPayloadServiceTests(unittest.TestCase):
    def collection_payload(self, start, end, *, failed=None):
        sources = (
            "activities",
            "sleep",
            "hrv",
            "daily_stats",
            "resting_hr",
            "training_load_activities",
        )
        return {
            "start": start,
            "end": end,
            "synced_at": f"{end}T12:00:00",
            "errors": [{"source": failed}] if failed else [],
            "provider_sync": {
                "pagination": {
                    source: {"complete": source != failed} for source in sources
                }
            },
            **{source: [] for source in sources},
        }

    def test_automatic_window_fetches_only_coverage_metadata(self):
        seed = self.service.prepare_remote(
            self.collection_payload("2026-06-29", "2026-09-20")
        )
        seed["large_unrelated_data"] = "synthetic-unused" * 100000
        self.store_garmin_snapshot(seed)
        repository = self.service._key_value_repository
        with patch.object(
            repository, "get", side_effect=AssertionError("full snapshot read")
        ):
            self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_initial_recent_import_then_regular_two_day_refresh(self):
        self.assertEqual(self.service.automatic_sync_days(2), 84)
        seed = self.service.prepare_remote(
            self.collection_payload("2026-06-29", "2026-09-20")
        )
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 2)
        self.assertEqual(
            seed["source_freshness"]["sleep"]["synced_start"], "2026-06-29"
        )

    def test_partial_success_does_not_advance_failed_collection(self):
        seed = self.service.prepare_remote(
            self.collection_payload("2026-06-19", "2026-09-10")
        )
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 11)
        partial = self.service.prepare_remote(
            self.collection_payload("2026-09-09", "2026-09-20", failed="sleep")
        )
        self.store_garmin_snapshot(partial)
        self.assertEqual(partial["source_freshness"]["hrv"]["synced_end"], "2026-09-20")
        self.assertEqual(
            partial["source_freshness"]["sleep"]["synced_end"], "2026-09-10"
        )
        self.assertEqual(self.service.automatic_sync_days(2), 11)
        completed = self.service.prepare_remote(
            self.collection_payload("2026-09-09", "2026-09-20")
        )
        self.store_garmin_snapshot(completed)
        self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_next_calendar_day_still_needs_only_two_days(self):
        seed = self.service.prepare_remote(
            self.collection_payload("2026-06-28", "2026-09-19")
        )
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_unavailable_optional_collection_does_not_force_repeated_initial_import(
        self,
    ):
        payload = self.collection_payload("2026-06-29", "2026-09-20")
        for source in ("daily_stats", "resting_hr"):
            del payload[source]
            del payload["provider_sync"]["pagination"][source]
        self.store_garmin_snapshot(self.service.prepare_remote(payload))
        self.assertEqual(self.service.automatic_sync_days(2), 2)

    def test_training_load_coverage_is_recorded_without_driving_recovery_backfill(self):
        required = self.collection_payload("2026-06-27", "2026-09-18")
        del required["training_load_activities"]
        del required["provider_sync"]["pagination"]["training_load_activities"]
        self.store_garmin_snapshot(self.service.prepare_remote(required))

        load_refresh = {
            "start": "2026-09-19",
            "end": "2026-09-20",
            "synced_at": "2026-09-20T13:00:00",
            "errors": [],
            "training_load_activities": [
                {"activityId": 21, "activityTrainingLoad": 45}
            ],
            "provider_sync": {
                "pagination": {
                    "training_load_activities": {"complete": True, "records": 1}
                }
            },
        }

        refreshed = self.service.prepare_remote(load_refresh)

        self.assertEqual(
            refreshed["source_freshness"]["training_load_activities"]["synced_start"],
            "2026-09-19",
        )
        self.assertEqual(
            refreshed["source_freshness"]["training_load_activities"]["synced_end"],
            "2026-09-20",
        )
        self.assertEqual(
            refreshed["source_freshness"]["activities"]["synced_end"],
            "2026-09-18",
        )
        self.assertEqual(
            refreshed["source_freshness"]["sleep"]["synced_end"],
            "2026-09-18",
        )
        self.assertEqual(self.service.automatic_sync_days(2), 3)

    def test_load_source_failures_keep_last_good_values_stale_and_do_not_advance_coverage(
        self,
    ):
        previous = self.collection_payload("2026-06-27", "2026-09-18")
        previous["training_load_activities"] = [
            {"activityId": 21, "activityTrainingLoad": 45}
        ]
        previous["training_load_balance"] = {"load": 210}
        previous["daily_training_status"] = {"acuteLoad": 68}
        previous["source_freshness"] = {
            "training_load_balance": {
                "freshness": "current",
                "fetched_at": "2026-09-18T12:00:00",
                "observed_at": "2026-09-18",
            },
            "daily_training_status": {
                "freshness": "current",
                "fetched_at": "2026-09-18T12:00:00",
                "observed_at": "2026-09-18",
            },
        }
        self.store_garmin_snapshot(self.service.prepare_remote(previous))

        failed = {
            "start": "2026-09-19",
            "end": "2026-09-20",
            "synced_at": "2026-09-20T13:00:00",
            "errors": [
                {"source": "training_load_activities", "message": "synthetic timeout"},
                {"source": "training_load_balance", "message": "synthetic timeout"},
                {"source": "daily_training_status", "message": "synthetic timeout"},
            ],
            "training_load_activities": [
                {"activityId": 22, "activityTrainingLoad": 48}
            ],
            "provider_sync": {
                "pagination": {
                    "training_load_activities": {"complete": False, "records": 0}
                }
            },
        }
        refreshed = self.service.prepare_remote(failed)

        self.assertEqual(
            refreshed["training_load_activities"],
            [
                {"activityId": 22, "activityTrainingLoad": 48},
                {"activityId": 21, "activityTrainingLoad": 45},
            ],
        )
        self.assertEqual(
            refreshed["training_load_balance"], previous["training_load_balance"]
        )
        self.assertEqual(
            refreshed["daily_training_status"], previous["daily_training_status"]
        )
        self.assertEqual(
            refreshed["source_freshness"]["training_load_activities"]["freshness"],
            "partial",
        )
        self.assertEqual(
            refreshed["source_freshness"]["training_load_activities"]["synced_end"],
            "2026-09-18",
        )
        for source in ("training_load_balance", "daily_training_status"):
            self.assertEqual(
                refreshed["source_freshness"][source]["freshness"], "stale"
            )
        self.assertEqual(self.service.automatic_sync_days(2), 3)

    def test_empty_current_load_metrics_do_not_mark_retained_values_fresh(self):
        previous = {
            "synced_at": "2026-09-18T12:00:00",
            "training_load_balance": {"load": 210},
            "daily_training_status": {"acuteLoad": 68},
            "source_freshness": {
                source: {
                    "freshness": "current",
                    "fetched_at": "2026-09-18T12:00:00",
                    "observed_at": "2026-09-18",
                }
                for source in ("training_load_balance", "daily_training_status")
            },
        }
        self.store_garmin_snapshot(previous)
        payload = {
            "synced_at": "2026-09-20T12:00:00",
            "errors": [],
            "training_load_balance": {},
            "daily_training_status": {},
        }

        refreshed = self.service.prepare_remote(payload)

        for source, expected in (
            ("training_load_balance", {"load": 210}),
            ("daily_training_status", {"acuteLoad": 68}),
        ):
            self.assertEqual(refreshed[source], expected)
            self.assertEqual(
                refreshed["source_freshness"][source]["freshness"], "stale"
            )

    def test_failed_initial_recovery_is_retried_despite_activity_backfill(self):
        seed = self.service.prepare_remote(
            self.collection_payload("2026-06-29", "2026-09-20", failed="hrv")
        )
        self.store_garmin_snapshot(seed)
        historical = self.service.prepare_remote(
            {
                "start": "2026-01-01",
                "end": "2026-03-31",
                "synced_at": "2026-09-20T13:00:00",
                "activities": [],
                "provider_sync": {"pagination": {"activities": {"complete": True}}},
            }
        )
        self.store_garmin_snapshot(historical)
        self.assertEqual(self.service.automatic_sync_days(2), 84)
        self.assertEqual(
            historical["source_freshness"]["activities"]["synced_end"], "2026-09-20"
        )

    def test_long_outage_is_bounded_and_disjoint_windows_are_not_called_continuous(
        self,
    ):
        seed = self.service.prepare_remote(
            self.collection_payload("2024-12-08", "2025-03-01")
        )
        self.store_garmin_snapshot(seed)
        self.assertEqual(self.service.automatic_sync_days(2), 90)
        self.assertEqual(self.service.automatic_sync_window(2), (90, date(2025, 5, 29)))

    def test_long_outage_catches_up_in_contiguous_bounded_windows(self):
        seed = self.service.prepare_remote(
            self.collection_payload("2024-12-08", "2025-03-01")
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
                self.collection_payload(
                    window_start.isoformat(), window_end.isoformat()
                )
            )
            self.store_garmin_snapshot(result)
            if end_date is None:
                break
        self.assertEqual(windows[-1][1], date(2026, 9, 20))
        self.assertEqual(self.service.automatic_sync_window(2), (2, None))

    def test_awaited_run_status_requires_the_latest_complete_read_of_the_window(
        self,
    ):
        synced_at = "2026-09-20T12:00:00"
        status = self.service.awaited_run_status
        self.store_garmin_snapshot(
            self.service.prepare_remote(
                self.collection_payload("2026-09-18", "2026-09-20")
            )
        )
        self.assertEqual(status(3, None, synced_at), "ok")
        self.assertEqual(status(2, date(2026, 9, 19), synced_at), "ok")
        self.assertIsNone(status(4, None, synced_at))
        self.assertIsNone(status(3, None, "2026-09-19T12:00:00"))
        self.assertIsNone(status(3, None, None))
        self.store_garmin_snapshot(
            self.service.prepare_remote(
                self.collection_payload("2026-09-18", "2026-09-20", failed="sleep")
            )
        )
        self.assertIsNone(status(3, None, synced_at))
        self.store_garmin_snapshot(
            self.service.prepare_remote(
                self.collection_payload("2026-09-18", "2026-09-20", failed="resting_hr")
            )
        )
        self.assertEqual(status(3, None, synced_at), "partial")

    def test_awaited_run_status_ignores_start_merged_from_an_older_run(self):
        self.store_garmin_snapshot(
            self.service.prepare_remote(
                self.collection_payload("2026-06-29", "2026-09-19")
            )
        )
        short = self.service.prepare_remote(
            self.collection_payload("2026-09-19", "2026-09-20")
        )
        self.store_garmin_snapshot(short)

        self.assertEqual(short["start"], "2026-06-29")
        self.assertEqual(
            short["provider_sync"]["read_window"],
            {"start": "2026-09-19", "end": "2026-09-20"},
        )
        self.assertEqual(
            self.service.awaited_run_status(2, None, "2026-09-20T12:00:00"), "ok"
        )
        self.assertIsNone(
            self.service.awaited_run_status(84, None, "2026-09-20T12:00:00")
        )

    def test_gear_collection_uses_reported_stats_and_does_not_publish_partial_inventory(
        self,
    ):
        client = SimpleNamespace(
            get_user_profile=lambda: {"id": 123, "userData": {}},
            get_gear=lambda profile: [
                {"gearUUID": "one", "gearName": "Bike"},
                {"gearUUID": "two", "gearName": "Shoes"},
            ],
            get_gear_stats=lambda identity: {
                "totalDistance": 2000 if identity == "one" else 3000
            },
        )
        call = lambda service, operation, fetch, details: fetch()
        result = _gear_inventory(client, call)
        self.assertEqual(
            [row["stats"]["totalDistance"] for row in result], [2000, 3000]
        )

        def fail_stats(identity):
            raise RuntimeError("Synthetic unavailable")

        client.get_gear_stats = fail_stats
        result = _gear_inventory(client, call)
        self.assertEqual([row["gearUUID"] for row in result], ["one", "two"])
        self.assertEqual([row["stats"] for row in result], [{}, {}])

    @staticmethod
    def _gear_client(**extra):
        return SimpleNamespace(
            get_user_profile=lambda: {"id": 123},
            get_gear=lambda profile: [
                {"gearUUID": "one", "gearName": "Bike"},
                {"gearUUID": "two", "gearName": "Shoes"},
            ],
            get_gear_stats=lambda identity: {"totalDistance": 2000},
            **extra,
        )

    def test_gear_collection_stores_unique_activity_ids_read_only(self):
        calls = []

        def activities(identity, limit):
            calls.append((identity, limit))
            return [
                {"activityId": 11, "activityType": {"typeKey": "running"}},
                {"activityId": "12"},
                {"activityId": 11},
                {"noId": True},
                "malformed",
            ]

        writers = {
            name: Mock()
            for name in ("add_gear_to_activity", "remove_gear_from_activity")
        }
        client = self._gear_client(get_gear_activities=activities, **writers)
        client.set_gear_default = Mock()
        call = lambda service, operation, fetch, details: fetch()
        result = _gear_inventory(client, call)
        self.assertEqual([row["activity_ids"] for row in result], [["11", "12"]] * 2)
        self.assertNotIn("activity_ids_truncated", result[0])
        self.assertEqual(calls, [("one", 1000), ("two", 1000)])
        for writer in (*writers.values(), client.set_gear_default):
            writer.assert_not_called()

    def test_gear_collection_omits_activity_ids_when_unknown(self):
        call = lambda service, operation, fetch, details: fetch()
        result = _gear_inventory(self._gear_client(), call)
        self.assertTrue(all("activity_ids" not in row for row in result))

        def fail(identity, limit):
            raise RuntimeError("Synthetic gear activities unavailable")

        result = _gear_inventory(self._gear_client(get_gear_activities=fail), call)
        self.assertEqual([row["gearUUID"] for row in result], ["one", "two"])
        self.assertTrue(all("activity_ids" not in row for row in result))
        self.assertEqual([row["stats"]["totalDistance"] for row in result], [2000] * 2)
        invalid = self._gear_client(get_gear_activities=lambda identity, limit: {})
        self.assertTrue(
            all("activity_ids" not in row for row in _gear_inventory(invalid, call))
        )
        # An empty list is a real answer, unlike a missing one.
        empty = self._gear_client(get_gear_activities=lambda identity, limit: [])
        self.assertEqual(
            [row["activity_ids"] for row in _gear_inventory(empty, call)], [[], []]
        )

    def test_sdk_empty_gear_result_requires_http_confirmation(self):
        call = lambda service, operation, fetch, details: fetch()
        client = self._gear_client(get_gear_activities=lambda identity, limit: [])
        client.garmin_connect_activities_baseurl = (
            "https://synthetic.invalid/activities/"
        )
        client.connectapi = Mock(side_effect=RuntimeError("synthetic 404"))
        unknown = _gear_inventory(client, call)
        self.assertTrue(all("activity_ids" not in row for row in unknown))
        client.connectapi = Mock(return_value=[])
        empty = _gear_inventory(client, call)
        self.assertEqual([row["activity_ids"] for row in empty], [[], []])

    def test_gear_collection_flags_truncated_activity_lists(self):
        call = lambda service, operation, fetch, details: fetch()
        full = self._gear_client(
            get_gear_activities=lambda identity, limit: [
                {"activityId": number} for number in range(limit)
            ]
        )
        result = _gear_inventory(full, call)
        self.assertTrue(all(row["activity_ids_truncated"] for row in result))
        self.assertEqual(len(result[0]["activity_ids"]), 1000)

    def test_stored_gear_snapshot_keeps_activity_ids_through_merge(self):
        gear = [{"gearUUID": "one", "activity_ids": ["11"], "stats": {}}]
        merged = self.service.prepare_remote(
            {"synced_at": "2026-09-20T10:00:00", "gear": gear, "errors": []}
        )
        self.assertEqual(merged["gear"][0]["activity_ids"], ["11"])
        self.store_garmin_snapshot(merged)
        failed = self.service.prepare_remote(
            {
                "synced_at": "2026-09-20T11:00:00",
                "errors": [{"source": "gear", "message": "Synthetic failure"}],
            }
        )
        self.assertEqual(failed["gear"][0]["activity_ids"], ["11"])
        self.assertEqual(failed["source_freshness"]["gear"]["freshness"], "stale")

    def test_failed_gear_activity_read_keeps_the_last_known_list(self):
        stored = [
            {"gearUUID": "one", "activity_ids": ["11"], "stats": {}},
            {
                "gearUUID": "two",
                "activity_ids": ["21"],
                "activity_ids_truncated": True,
                "stats": {},
            },
            {"gearUUID": "three", "activity_ids": ["31"], "stats": {}},
        ]
        self.store_garmin_snapshot(
            self.service.prepare_remote(
                {"synced_at": "2026-09-20T10:00:00", "gear": stored, "errors": []}
            )
        )
        merged = self.service.prepare_remote(
            {
                "synced_at": "2026-09-20T11:00:00",
                "gear": [
                    {"gearUUID": "one", "stats": {}},
                    {"gearUUID": "two", "stats": {}},
                    {"gearUUID": "three", "activity_ids": [], "stats": {}},
                    {"gearUUID": "four", "stats": {}},
                ],
                "errors": [],
            }
        )
        rows = {row["gearUUID"]: row for row in merged["gear"]}
        self.assertEqual(rows["one"]["activity_ids"], ["11"])
        self.assertTrue(rows["two"]["activity_ids_truncated"])
        self.assertTrue(rows["one"]["activity_ids_stale"])
        self.assertTrue(rows["two"]["activity_ids_stale"])
        self.assertEqual(rows["three"]["activity_ids"], [])
        self.assertNotIn("activity_ids_stale", rows["three"])
        self.assertNotIn("activity_ids", rows["four"])
        self.assertEqual(merged["source_freshness"]["gear"]["freshness"], "current")

    def test_top_level_gear_profile_failure_is_reported(self):
        payload = {"errors": []}

        def fail(*args):
            raise RuntimeError("Synthetic profile unavailable")

        _collect_optional_metric(
            payload,
            "gear",
            fail,
            None,
            lambda service, operation, fetch, details: fetch(),
            str,
            None,
        )
        self.assertEqual(payload["errors"][0]["source"], "gear")
        self.assertIn("Synthetic profile unavailable", payload["errors"][0]["message"])

    def test_gear_collection_skips_malformed_inventory_rows(self):
        client = SimpleNamespace(
            get_user_profile=lambda: {"id": 123},
            get_gear=lambda profile: [
                {"gearUUID": "one", "gearName": "Bike"},
                {"gearName": "Garmin placeholder"},
                None,
                {"gearUUID": "two", "gearName": "Shoes"},
            ],
            get_gear_stats=lambda identity: {"totalDistance": 2000},
        )
        call = lambda service, operation, fetch, details: fetch()
        result = _gear_inventory(client, call)
        self.assertEqual([row["gearUUID"] for row in result], ["one", "two"])

    def test_gear_collection_uses_top_level_profile_id(self):
        client = SimpleNamespace(
            get_user_profile=lambda: {
                "id": 123,
                "userData": {"displayName": "Athlete"},
            },
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

    def test_gear_collection_normalizes_actual_garmin_uuid_and_display_fields(self):
        raw = {
            "uuid": "gear-uuid",
            "displayName": "Race bike",
            "gearMakeName": "Example",
            "gearModelName": "Road 1",
            "customMakeModel": "My race bike",
            "gearTypeName": "Bike",
            "gearStatusName": "Active",
            "dateBegin": "2025-01-01",
            "dateEnd": None,
            "maximumMeters": 100000,
        }
        client = SimpleNamespace(
            get_user_profile=lambda: {"id": 123},
            get_gear=lambda profile: [raw],
            get_gear_stats=lambda identity: {
                "totalDistance": 25000,
                "totalActivities": 4,
            },
        )
        result = _gear_inventory(
            client, lambda service, operation, fetch, details: fetch()
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["uuid"], "gear-uuid")
        self.assertEqual(result[0]["gearUUID"], "gear-uuid")
        self.assertEqual(result[0]["displayName"], "Race bike")
        self.assertEqual(result[0]["gearName"], "Race bike")
        self.assertEqual(result[0]["stats"]["totalDistance"], 25000)

    def test_garmin_gear_empty_inventory_replaces_old_and_failed_read_preserves_it(
        self,
    ):
        self.store_garmin_snapshot(
            {"gear": [{"gearUUID": "one", "stats": {"totalDistance": 2000}}]}
        )
        failed = self.service.prepare_remote(
            {
                "synced_at": "2026-09-20T10:00:00",
                "errors": [{"source": "gear", "message": "Synthetic failure"}],
            }
        )
        self.assertEqual(failed["gear"][0]["gearUUID"], "one")
        self.assertEqual(failed["source_freshness"]["gear"]["freshness"], "stale")
        empty = self.service.prepare_remote(
            {"synced_at": "2026-09-20T11:00:00", "gear": [], "errors": []}
        )
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
        self.store_garmin_snapshot("[" * 100_000 + "]" * 100_000)
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
            {
                "read_window": {"start": "2026-09-15", "end": "2026-09-20"},
                "pagination": {
                    "fixture": {"windows": 1, "records": 2, "complete": True}
                },
            },
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
