import json
import sqlite3
import unittest
from datetime import date

from backend.athlete.checkins import CheckinService
from backend.athlete.equipment import EquipmentService, _garmin_kind, _garmin_sport
from backend.db.repositories import CheckinRepository
from backend.errors import AppError
from backend.nutrition.fueling import FuelingService
from backend.performance.comparisons import recurring_training_comparisons
from backend.performance.tag_impact import tag_impact


class MemoryManager:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )

    def unit_of_work(self):
        manager = self

        class Unit:
            def __enter__(self):
                return manager.connection

            def __exit__(self, kind, value, trace):
                if kind:
                    manager.connection.rollback()
                else:
                    manager.connection.commit()
                return False

        return Unit()


class TrainingRecordFeatureTests(unittest.TestCase):
    def test_garmin_components_and_running_shoes_have_supported_types(self):
        self.assertEqual(
            _garmin_kind({"gearTypeName": "Bike", "gearName": "Shimano chain"}),
            "component",
        )
        self.assertEqual(
            _garmin_sport({"gearTypeName": "Bike", "gearName": "Shimano chain"}),
            "Ride",
        )
        self.assertEqual(
            _garmin_kind({"gearTypeName": "Shoes", "gearName": "Running shoes"}),
            "shoes",
        )
        self.assertEqual(
            _garmin_sport({"gearTypeName": "Shoes", "gearName": "Running shoes"}),
            "Run",
        )
        self.assertEqual(
            _garmin_sport({"gearTypeName": "Shoes", "gearName": "Cycling Shoes"}),
            "Ride",
        )

    def test_garmin_usage_is_authoritative_and_missing_stats_are_not_zero(self):
        service = EquipmentService(
            self.manager,
            lambda: {"recent_activities": [{"id": "one", "distance": 10000}]},
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
        )
        snapshot = {
            "gear": [
                {
                    "gearUUID": "gear-one",
                    "gearName": "Bike",
                    "gearStatusName": "Retired",
                    "maximumMeters": 10000,
                    "stats": {"totalDistance": 2500, "totalActivities": 3},
                },
                {"gearUUID": "gear-two", "gearName": "Shoes", "stats": {}},
            ]
        }
        self.manager.connection.execute(
            "INSERT INTO kv VALUES ('garmin_snapshot', ?, 'now')",
            (json.dumps(snapshot),),
        )
        items = service.read()["garmin_items"]
        self.assertEqual(items[0]["distance_km"], 2.5)
        self.assertEqual(items[0]["usage_percent"], 25)
        self.assertEqual(items[0]["garmin_status"], "Retired")
        self.assertEqual(items[0]["lifetime"]["target_km"], 10)
        self.assertEqual(items[0]["sessions"], 3)
        self.assertIsNone(items[1]["distance_km"])
        snapshot["gear"][0]["stats"]["totalDistance"] = 3000
        self.manager.connection.execute(
            "UPDATE kv SET value=? WHERE key='garmin_snapshot'", (json.dumps(snapshot),)
        )
        self.assertEqual(service.read()["garmin_items"][0]["distance_km"], 3)

    def test_garmin_initial_sync_imports_once_and_later_sync_updates_only_distance(
        self,
    ):
        service = EquipmentService(
            self.manager, dict, lambda: date(2026, 10, 2), lambda: "now"
        )
        first = {
            "source_freshness": {"gear": {"freshness": "current"}},
            "gear": [
                {
                    "gearUUID": "gear-1",
                    "gearName": "Road bike",
                    "gearTypeName": "bike",
                    "gearStatusName": "Active",
                    "maximumMeters": 150000,
                    "stats": {"totalDistance": 120000},
                }
            ],
        }
        service.sync_garmin_snapshot(first)
        imported = service.read()["items"][0]
        self.assertEqual(imported["initial_distance_km"], 120)
        self.assertEqual(imported["garmin_distance_km"], 120)
        self.assertEqual(imported["garmin_maximum_meters"], 150000)
        self.assertEqual(imported["lifetime_target_km"], 150)
        self.assertEqual(imported["lifetime"]["percent"], 80)
        self.assertEqual(imported["status"], "active")
        service.save(
            {
                "id": imported["id"],
                "expected_revision": imported["revision"],
                "name": imported["name"],
                "sport": imported["sport"],
                "kind": imported["kind"],
                "status": "archived",
                "parent_id": None,
                "start_date": imported["start_date"],
                "initial_distance_km": imported["initial_distance_km"],
                "initial_hours": imported["initial_hours"],
                "maintenance_km": None,
                "maintenance_hours": None,
            }
        )
        second = {
            "source_freshness": {"gear": {"freshness": "current"}},
            "gear": [
                {
                    "gearUUID": "gear-1",
                    "gearName": "New Garmin name",
                    "gearTypeName": "bike",
                    "gearStatusName": "Active",
                    "maximumMeters": 250000,
                    "stats": {"totalDistance": 145000},
                },
                {
                    "gearUUID": "gear-2",
                    "gearName": "Later Garmin bike",
                    "gearTypeName": "bike",
                    "stats": {"totalDistance": 1000},
                },
            ],
        }
        service.sync_garmin_snapshot(second)
        self.manager.connection.execute(
            "INSERT INTO kv VALUES ('garmin_snapshot', ?, 'now')",
            (json.dumps(second),),
        )
        item = service.read()["items"][0]
        self.assertEqual(item["status"], "archived")
        self.assertEqual(item["name"], "Road bike")
        self.assertEqual(item["usage"]["distance_km"], 145)
        self.assertEqual(item["garmin_status"], "Active")
        self.assertEqual(item["garmin_maximum_meters"], 250000)
        self.assertEqual(item["lifetime_target_km"], 250)
        self.assertEqual(len(service.read()["items"]), 1)
        self.assertEqual(service.read()["garmin_items"], [])

    def test_empty_initial_gear_snapshot_does_not_finalize_import(self):
        service = EquipmentService(
            self.manager, dict, lambda: date(2026, 10, 2), lambda: "now"
        )
        service.sync_garmin_snapshot(
            {
                "source_freshness": {"gear": {"freshness": "current"}},
                "gear": [],
            }
        )
        self.assertIsNone(
            self.manager.connection.execute(
                "SELECT value FROM kv WHERE key='garmin_equipment_initialized'"
            ).fetchone()
        )
        service.sync_garmin_snapshot(
            {
                "source_freshness": {"gear": {"freshness": "current"}},
                "gear": [{"gearUUID": "gear-1", "gearName": "Bike"}],
            }
        )
        self.assertEqual(len(service.read()["items"]), 1)

    def test_legacy_empty_import_recovers_once_and_preserves_local_equipment(self):
        service = EquipmentService(
            self.manager, dict, lambda: date(2026, 10, 2), lambda: "now"
        )
        local = {
            "id": "local-item",
            "name": "Local shoes",
            "sport": "Run",
            "kind": "shoes",
            "status": "active",
            "parent_id": None,
            "start_date": "2026-09-01",
            "initial_distance_km": 0,
            "initial_hours": 0,
            "revision": 1,
        }
        self.manager.connection.executemany(
            "INSERT INTO kv VALUES (?, ?, 'now')",
            [
                ("garmin_equipment_initialized", "1"),
                ("equipment:local-item", json.dumps(local)),
            ],
        )
        current = {
            "source_freshness": {"gear": {"freshness": "current"}},
            "gear": [{"gearUUID": "gear-1", "gearName": "Road bike"}],
        }
        service.sync_garmin_snapshot(current)
        service.sync_garmin_snapshot(current)
        items = service.read()["items"]
        self.assertEqual({item["name"] for item in items}, {"Local shoes", "Road bike"})
        self.assertEqual(len([item for item in items if item.get("garmin_uuid")]), 1)

    def test_legacy_marker_with_archived_garmin_item_never_imports_new_gear(self):
        service = EquipmentService(
            self.manager, dict, lambda: date(2026, 10, 2), lambda: "now"
        )
        existing = {
            "id": "garmin-linked",
            "name": "Archived bike",
            "sport": "Ride",
            "kind": "bike",
            "status": "archived",
            "parent_id": None,
            "start_date": "2026-09-01",
            "initial_distance_km": 10,
            "initial_hours": 0,
            "garmin_uuid": "gear-1",
            "garmin_distance_km": 10,
            "revision": 1,
        }
        self.manager.connection.executemany(
            "INSERT INTO kv VALUES (?, ?, 'now')",
            [
                ("garmin_equipment_initialized", "1"),
                ("equipment:garmin-linked", json.dumps(existing)),
            ],
        )
        current = {
            "source_freshness": {"gear": {"freshness": "current"}},
            "gear": [
                {
                    "gearUUID": "gear-1",
                    "gearName": "Renamed remotely",
                    "stats": {"totalDistance": 25000},
                },
                {
                    "gearUUID": "gear-2",
                    "gearName": "New bike",
                    "stats": {"totalDistance": 1000},
                },
            ],
        }
        service.sync_garmin_snapshot(current)
        service.sync_garmin_snapshot(current)
        items = service.read()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "archived")
        self.assertEqual(items[0]["name"], "Archived bike")
        self.assertEqual(items[0]["garmin_distance_km"], 25)

    def test_recurring_comparison_keeps_historical_targets_and_device_provenance_separate(
        self,
    ):
        base = {
            "sport": "Ride",
            "device": "Wahoo",
            "target_snapshot": {
                "steps": [{"duration": 300, "target": "90%"}],
                "basis": {"icu_ftp": 250},
            },
            "interval_quality": {"status": "ok"},
            "date": "2026-08-01",
        }
        rows = [
            base,
            {**base, "date": "2026-08-08"},
            {**base, "device": "Garmin"},
            {
                **base,
                "target_snapshot": {
                    **base["target_snapshot"],
                    "basis": {"icu_ftp": 280},
                },
            },
            {**base, "interval_quality": {"status": "partial"}},
        ]
        result = recurring_training_comparisons(rows)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(len(result["groups"][0]["observations"]), 2)

    def setUp(self):
        self.manager = MemoryManager()

    def tearDown(self):
        self.manager.connection.close()

    def test_fueling_plan_is_local_bound_to_current_unit_and_not_consumption(self):
        unit = {
            "id": "ride-1",
            "type": "Ride",
            "date": "2026-09-20",
            "duration_minutes": 120,
        }
        service = FuelingService(
            self.manager,
            lambda: [unit],
            lambda: [{"id": "meal-1", "name": "Oats", "carbs_g": 60}],
            dict,
            lambda: "2026-09-01T00:00:00Z",
        )
        preview = service.read("ride-1")
        saved = service.save(
            {
                "planned_unit_id": "ride-1",
                "unit_sha256": preview["unit_sha256"],
                "carbs_g_per_hour": 45,
                "fluid_ml_per_hour": 600,
                "template_id": "meal-1",
            }
        )
        self.assertTrue(saved["stored_locally"])
        self.assertFalse(saved["consumption_logged"])
        self.assertEqual(saved["fueling_plan"]["suggested_portions_during"], 1.5)
        unit["duration_minutes"] = 150
        self.assertTrue(service.read("ride-1")["saved_stale"])
        with self.assertRaises(AppError):
            service.save(
                {
                    "planned_unit_id": "ride-1",
                    "unit_sha256": preview["unit_sha256"],
                    "carbs_g_per_hour": 45,
                    "fluid_ml_per_hour": 600,
                }
            )

    def test_checkin_tag_omission_preserves_and_empty_object_clears(self):
        connection = self.manager.connection
        connection.execute(
            "CREATE TABLE athlete_checkins (checkin_date TEXT PRIMARY KEY, soreness INTEGER, stress INTEGER, motivation INTEGER, session_rpe INTEGER, day_form TEXT, illness TEXT, pain TEXT, available_minutes INTEGER, availability_notes TEXT, notes TEXT, created_at TEXT, updated_at TEXT)"
        )
        repository = CheckinRepository(lambda: "2026-09-01T00:00:00Z")
        service = CheckinService(self.manager, repository, lambda: date(2026, 9, 1))
        service.save({"checkin_date": "2026-08-31", "tag_answers": {"travel": True}})
        service.save({"checkin_date": "2026-08-31", "notes": "edit"})
        self.assertEqual(service.list()[0]["tag_answers"], {"travel": True})
        service.save({"checkin_date": "2026-08-31", "tag_answers": {}})
        self.assertEqual(service.list()[0].get("tag_answers"), {})

    def test_checkin_rejects_non_boolean_and_unknown_tag_answers(self):
        repository = CheckinRepository(lambda: "2026-09-01T00:00:00Z")
        service = CheckinService(self.manager, repository, lambda: date(2026, 9, 1))
        for answers in ({"travel": 1}, {"unknown": True}):
            with self.assertRaises(AppError):
                service.save({"tag_answers": answers})

    def test_equipment_assignment_is_explicit_and_unassignable(self):
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "ride-1",
                        "type": "Ride",
                        "start_date_local": "2026-08-30",
                        "distance": 20000,
                        "moving_time": 3600,
                    }
                ]
            }
        }
        service = EquipmentService(
            self.manager,
            lambda: snapshot,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
        )
        equipment = service.save(
            {
                "name": "Road bike",
                "sport": "Ride",
                "kind": "bike",
                "start_date": "2026-08-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
            }
        )["equipment"]
        service.assign({"activity_id": "ride-1", "equipment_id": equipment["id"]})
        read = service.read()
        self.assertEqual(read["items"][0]["usage"]["distance_km"], 20)
        service.assign({"activity_id": "ride-1", "equipment_id": None})
        self.assertIsNone(service.read()["assignments"][0]["equipment_id"])
        with self.assertRaises(AppError):
            service.assign({"activity_id": "missing", "equipment_id": equipment["id"]})
        stored = json.loads(
            self.manager.connection.execute(
                "SELECT value FROM kv WHERE key=?", ("equipment:" + equipment["id"],)
            ).fetchone()[0]
        )
        stored["sport_pending"] = True
        self.manager.connection.execute(
            "UPDATE kv SET value=? WHERE key=?",
            (json.dumps(stored), "equipment:" + equipment["id"]),
        )
        with self.assertRaises(AppError):
            service.assign({"activity_id": "ride-1", "equipment_id": equipment["id"]})

    def test_tag_impact_requires_ten_measured_days_in_each_explicit_group(self):
        checkins = []
        nights = {}
        for day in range(1, 21):
            date_text = f"2026-08-{day:02d}"
            checkins.append(
                {
                    "checkin_date": date_text,
                    "tag_answers": {"travel": day <= 10},
                }
            )
            nights[f"2026-08-{day + 1:02d}"] = float(day)
        result = tag_impact(
            checkins,
            {
                "baselines": [
                    {
                        "metric": "sleep",
                        "source": "Intervals.icu",
                        "measurement": "sleepSecs",
                        "unit": "hours",
                        "history": [
                            {"date": key, "value": value}
                            for key, value in nights.items()
                        ],
                    }
                ]
            },
            {"raw_provider_data": {"activities": []}},
            date(2026, 9, 1),
        )
        report = next(row for row in result["reports"] if row["tag"] == "travel")
        self.assertEqual(report["status"], "observed_association")
        self.assertEqual(report["groups"]["with"]["days"], 10)
        self.assertEqual(report["groups"]["without"]["days"], 10)
        self.assertEqual(report["groups"]["with"]["median"], 5.5)

    def test_equipment_requires_initial_values_and_prevents_component_cycles(self):
        service = EquipmentService(
            self.manager,
            dict,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
        )
        payload = {
            "name": "Bike",
            "sport": "Ride",
            "kind": "bike",
            "start_date": "2026-08-01",
            "initial_distance_km": 0,
            "initial_hours": 0,
        }
        with self.assertRaises(AppError):
            service.save(
                {key: value for key, value in payload.items() if key != "initial_hours"}
            )
        bike = service.save(payload)["equipment"]
        component = service.save(
            {**payload, "name": "Chain", "kind": "component", "parent_id": bike["id"]}
        )["equipment"]
        with self.assertRaises(AppError):
            service.save(
                {
                    **payload,
                    "kind": "component",
                    "parent_id": bike["id"],
                    "sport": "Run",
                }
            )
        with self.assertRaises(AppError):
            service.save(
                {
                    **payload,
                    "id": bike["id"],
                    "expected_revision": 1,
                    "kind": "component",
                    "parent_id": component["id"],
                }
            )
        self.assertEqual(len(service.read()["items"]), 2)

    def test_local_lifetime_target_must_be_positive_and_is_projected(self):
        service = EquipmentService(
            self.manager,
            dict,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
        )
        payload = {
            "name": "Bike",
            "sport": "Ride",
            "kind": "bike",
            "start_date": "2026-08-01",
            "initial_distance_km": 125,
            "initial_hours": 0,
            "lifetime_target_km": 100,
        }
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(AppError):
                service.save({**payload, "lifetime_target_km": value})
        item = service.save(payload)["equipment"]
        self.assertEqual(item["lifetime_target_km"], 100)
        self.assertEqual(service.read()["items"][0]["lifetime"]["percent"], 125)

    def test_backdated_garmin_maintenance_keeps_distance_baseline_unknown(self):
        service = EquipmentService(
            self.manager, dict, lambda: date(2026, 10, 2), lambda: "now"
        )
        service.sync_garmin_snapshot(
            {
                "source_freshness": {"gear": {"freshness": "current"}},
                "gear": [
                    {
                        "gearUUID": "gear-backdated",
                        "gearName": "Road bike",
                        "gearTypeName": "bike",
                        "stats": {"totalDistance": 100000},
                    }
                ],
            }
        )
        item = service.read()["items"][0]
        saved = service.save(
            {
                "id": item["id"],
                "expected_revision": item["revision"],
                "name": item["name"],
                "sport": item["sport"],
                "kind": item["kind"],
                "status": "active",
                "parent_id": None,
                "start_date": "2026-09-01",
                "initial_distance_km": item["initial_distance_km"],
                "initial_hours": 0,
                "maintenance_km": 50,
            }
        )["equipment"]
        service.maintain({"equipment_id": saved["id"], "date": "2026-10-01"})
        latest = service.read()["items"][0]["usage"]
        self.assertIsNone(latest["maintenance_distance_km"])
        self.assertIsNone(latest["maintenance_due"])

    def test_maintenance_does_not_claim_complete_usage_for_same_day_activity(self):
        activity = {
            "id": "ride-1",
            "type": "Ride",
            "start_date_local": "2026-08-30",
            "distance": 20000,
            "moving_time": 3600,
        }
        service = EquipmentService(
            self.manager,
            lambda: {"recent_activities": [activity]},
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
        )
        bike = service.save(
            {
                "name": "Bike",
                "sport": "Ride",
                "kind": "bike",
                "start_date": "2026-08-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
                "maintenance_km": 10,
            }
        )["equipment"]
        service.assign({"activity_id": "ride-1", "equipment_id": bike["id"]})
        self.assertTrue(service.read()["items"][0]["usage"]["maintenance_due"])
        service.maintain({"equipment_id": bike["id"], "date": "2026-08-30"})
        item = service.read()["items"][0]
        self.assertEqual(item["usage"]["distance_km"], 20)
        self.assertIsNone(item["usage"]["maintenance_due"])
        self.assertEqual(item["usage"]["maintenance_same_day_sessions"], 1)


if __name__ == "__main__":
    unittest.main()
