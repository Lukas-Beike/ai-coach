import json
import sqlite3
import unittest
from datetime import date

from backend.athlete.checkins import CheckinService
from backend.athlete.equipment import EquipmentService, _garmin_kind, _garmin_sport
from backend.db.repositories import CheckinRepository
from backend.errors import AppError
from backend.performance.comparisons import recurring_training_comparisons
from backend.performance.tag_impact import tag_impact
from backend.performance.training_report import deduplicated_rows


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

    def reader(self):
        return self.unit_of_work()

    def read_snapshot(self):
        return self.unit_of_work()


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
            lambda: [{"id": "one", "distance": 10000}],
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            deduplicated_rows,
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
            self.manager,
            tuple,
            lambda: date(2026, 10, 2),
            lambda: "now",
            deduplicated_rows,
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
            self.manager,
            tuple,
            lambda: date(2026, 10, 2),
            lambda: "now",
            deduplicated_rows,
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
            self.manager,
            tuple,
            lambda: date(2026, 10, 2),
            lambda: "now",
            deduplicated_rows,
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
            self.manager,
            tuple,
            lambda: date(2026, 10, 2),
            lambda: "now",
            deduplicated_rows,
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
            lambda: snapshot["raw_provider_data"]["activities"],
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
            deduplicated_rows,
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

    def _gear_service(self, rows):
        return EquipmentService(
            self.manager,
            lambda: rows,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
            deduplicated_rows,
        )

    @staticmethod
    def _bike(**extra):
        return {
            "name": "Road bike",
            "sport": "Ride",
            "kind": "bike",
            "start_date": "2026-08-01",
            "initial_distance_km": 0,
            "initial_hours": 0,
            **extra,
        }

    @staticmethod
    def _ride(activity_id, day="2026-08-30", **extra):
        return {
            "id": activity_id,
            "type": "Ride",
            "start_date_local": day,
            "distance": 10000,
            "moving_time": 1800,
            **extra,
        }

    @staticmethod
    def _gear_row(uuid, type_name="Bike", **extra):
        return {
            "gearUUID": uuid,
            "gearName": "Gear " + uuid,
            "gearTypeName": type_name,
            "stats": {"totalDistance": 50000},
            **extra,
        }

    @staticmethod
    def _matches(rows):
        return [
            {"garmin_activity_id": "a" + row["id"], "intervals_activity_id": row["id"]}
            for row in rows
        ]

    @staticmethod
    def _snapshot(gear, matches=()):
        return {
            "source_freshness": {"gear": {"freshness": "current"}},
            "gear": gear,
            "activity_matches": list(matches),
        }

    def _garmin_gear(self, service, gear, matches=()):
        """Import Garmin gear as local items and store the snapshot read() uses."""
        snapshot = self._snapshot(gear, matches)
        service.sync_garmin_snapshot(snapshot)
        self.manager.connection.execute(
            "INSERT OR REPLACE INTO kv VALUES ('garmin_snapshot', ?, 'now')",
            (json.dumps(snapshot),),
        )
        return {item["garmin_uuid"]: item for item in service.read()["items"]}

    def test_garmin_gear_activities_link_through_matches_and_external_id(self):
        rows = [
            self._ride("i1"),
            self._ride("i2", external_id="222"),
            self._ride("i3", external_id="999"),
            self._ride("i4", day="2026-08-31", type="Walk", external_id="333"),
            self._ride("i5", external_id=""),
        ]
        service = self._gear_service(rows)
        items = self._garmin_gear(
            service,
            [self._gear_row("g1", activity_ids=["111", "222", "333"])],
            [{"garmin_activity_id": "111", "intervals_activity_id": "i1"}],
        )
        item = items["g1"]
        # i1 via the match, i2 and i4 via external_id (no sport check), not i3/i5,
        # even though the import date (2026-09-01) is after every linked session.
        self.assertEqual(item["usage"]["assigned_sessions"], 3)
        self.assertEqual(item["usage"]["hours"], 1.5)
        self.assertEqual(item["usage"]["distance_km"], 50)
        links = {row["activity_id"]: row for row in service.read()["assignments"]}
        self.assertEqual(set(links), {"i1", "i2", "i4"})
        self.assertEqual({row["source"] for row in links.values()}, {"garmin_gear"})

    def test_explicit_assignment_and_unassignment_beat_the_garmin_link(self):
        rows = [self._ride("i1"), self._ride("i2")]
        service = self._gear_service(rows)
        items = self._garmin_gear(
            service,
            [self._gear_row("g1", activity_ids=["ai1", "ai2"])],
            self._matches(rows),
        )
        other = service.save(self._bike(name="Other"))["equipment"]
        self.assertEqual(items["g1"]["usage"]["assigned_sessions"], 2)
        service.assign({"activity_id": "i1", "equipment_id": None})
        service.assign({"activity_id": "i2", "equipment_id": other["id"]})
        read = {item["name"]: item for item in service.read()["items"]}
        self.assertEqual(read["Gear g1"]["usage"]["assigned_sessions"], 0)
        self.assertEqual(read["Other"]["usage"]["assigned_sessions"], 1)
        sources = {
            row["activity_id"]: row.get("source")
            for row in service.read()["assignments"]
        }
        self.assertEqual(sources, {"i1": None, "i2": None})

    def test_activity_listed_for_two_main_items_links_nothing(self):
        rows = [self._ride("i1"), self._ride("i2")]
        service = self._gear_service(rows)
        items = self._garmin_gear(
            service,
            [
                self._gear_row("g1", activity_ids=["ai1", "ai2"]),
                self._gear_row("g2", activity_ids=["ai1"]),
            ],
            self._matches(rows),
        )
        self.assertEqual(items["g1"]["usage"]["assigned_sessions"], 1)
        self.assertEqual(items["g2"]["usage"]["assigned_sessions"], 0)
        self.assertEqual(
            {row["activity_id"] for row in service.read()["assignments"]}, {"i2"}
        )

    def test_missing_activity_ids_mean_unknown_and_link_nothing(self):
        service = self._gear_service([self._ride("i1", external_id="a1")])
        items = self._garmin_gear(
            service,
            [self._gear_row("g1"), self._gear_row("g2", activity_ids=[])],
            [{"garmin_activity_id": "a1", "intervals_activity_id": "i1"}],
        )
        self.assertEqual(items["g1"]["usage"]["assigned_sessions"], 0)
        self.assertEqual(items["g2"]["usage"]["assigned_sessions"], 0)
        self.assertEqual(service.read()["assignments"], [])

    def test_duplicate_recordings_of_one_session_count_once(self):
        base = {
            "type": "Ride",
            "start_date_local": "2026-08-30T08:00:00",
            "distance": 20000,
            "moving_time": 3600,
        }
        rows = [
            {**base, "id": "i1", "device_name": "Wahoo ELEMNT", "external_id": "w1"},
            {**base, "id": "i2", "device_name": "Garmin Edge 840", "external_id": "a1"},
        ]
        service = self._gear_service(rows)
        items = self._garmin_gear(
            service,
            [self._gear_row("g1", activity_ids=["a1"])],
            [
                {"garmin_activity_id": "a1", "intervals_activity_id": "i1"},
                {"garmin_activity_id": "a1", "intervals_activity_id": "i2"},
            ],
        )
        self.assertEqual(items["g1"]["usage"]["assigned_sessions"], 1)
        self.assertEqual(items["g1"]["usage"]["hours"], 1)

    def test_garmin_linked_sessions_feed_maintenance_usage(self):
        rows = [self._ride("i1"), self._ride("i2", day="2026-08-31")]
        service = self._gear_service(rows)
        item = self._garmin_gear(
            service,
            [self._gear_row("g1", activity_ids=["ai1", "ai2"])],
            self._matches(rows),
        )["g1"]
        service.save(
            self._bike(
                id=item["id"],
                expected_revision=item["revision"],
                name=item["name"],
                maintenance_hours=0.5,
            )
        )
        usage = service.read()["items"][0]["usage"]
        self.assertEqual(usage["maintenance_hours"], 1)
        self.assertTrue(usage["maintenance_due"])

    def test_component_counts_garmin_linked_sessions_from_its_own_start(self):
        rows = [self._ride("i1"), self._ride("i2", day="2026-08-31")]
        service = self._gear_service(rows)
        item = self._garmin_gear(
            service,
            [self._gear_row("g1", activity_ids=["ai1", "ai2"])],
            self._matches(rows),
        )["g1"]
        service.save(
            self._bike(
                name="Chain",
                kind="component",
                parent_id=item["id"],
                sport=item["sport"],
                start_date="2026-08-31",
            )
        )
        usage = {i["name"]: i["usage"] for i in service.read()["items"]}
        self.assertEqual(usage["Gear g1"]["assigned_sessions"], 2)
        self.assertEqual(usage["Chain"]["assigned_sessions"], 1)

    def test_explicit_unassignment_is_left_out_of_the_derived_sport(self):
        rows = [self._ride(f"r{n}") for n in range(4)]
        service = self._gear_service(rows)
        gear = [
            self._gear_row("g1", "Gadget", activity_ids=["a" + r["id"] for r in rows])
        ]
        matches = self._matches(rows)
        self._garmin_gear(service, gear, matches)
        service.assign({"activity_id": "r0", "equipment_id": None})
        service.assign({"activity_id": "r1", "equipment_id": None})
        service.sync_garmin_snapshot(self._snapshot(gear, matches))
        self.assertTrue(service.read()["items"][0]["sport_pending"])

    def _newer_assignments(self, count):
        """Store many newer explicit assignments of other activities."""
        self.manager.connection.executemany(
            "INSERT INTO kv VALUES (?, ?, '2026-09-02T00:00:00Z')",
            [
                (
                    f"equipment_assignment:n{n}",
                    json.dumps({"activity_id": f"n{n}", "equipment_id": None}),
                )
                for n in range(count)
            ],
        )

    def test_old_unassignment_still_beats_the_garmin_link(self):
        rows = [self._ride(f"r{n}") for n in range(4)]
        service = self._gear_service(rows)
        gear = [
            self._gear_row("g1", "Gadget", activity_ids=["a" + r["id"] for r in rows])
        ]
        matches = self._matches(rows)
        self._garmin_gear(service, gear, matches)
        service.assign({"activity_id": "r0", "equipment_id": None})
        service.assign({"activity_id": "r1", "equipment_id": None})
        self._newer_assignments(2001)
        usage = service.read()["items"][0]["usage"]
        self.assertEqual(usage["assigned_sessions"], 2)
        service.sync_garmin_snapshot(self._snapshot(gear, matches))
        self.assertTrue(service.read()["items"][0]["sport_pending"])

    def test_sport_other_saved_by_the_athlete_is_not_derived(self):
        rows = [self._ride(f"r{n}") for n in range(4)]
        service = self._gear_service(rows)
        gear = [
            self._gear_row("g1", "Gadget", activity_ids=["a" + r["id"] for r in rows])
        ]
        matches = self._matches(rows)
        item = self._garmin_gear(service, gear, matches)["g1"]
        service.save(
            self._bike(
                id=item["id"],
                expected_revision=item["revision"],
                name=item["name"],
                sport="other",
            )
        )
        service.sync_garmin_snapshot(self._snapshot(gear, matches))
        saved = service.read()["items"][0]
        self.assertEqual(saved["sport"], "other")
        self.assertTrue(saved["sport_pending"])

    def test_garmin_sync_without_gear_activity_lists_reads_no_activities(self):
        def unexpected_read():
            raise AssertionError("activity rows read without gear activity lists")

        service = self._gear_service([])
        service._read_activity_rows = unexpected_read
        service.sync_garmin_snapshot(self._snapshot([self._gear_row("g1")]))
        service.sync_garmin_snapshot(self._snapshot([self._gear_row("g1")]))
        imported = self.manager.connection.execute(
            "SELECT COUNT(*) FROM kv WHERE key LIKE 'equipment:%'"
        ).fetchone()[0]
        self.assertEqual(imported, 1)

    def _derived_item(self, rows):
        service = self._gear_service(rows)
        gear = [
            self._gear_row("g1", "Gadget", activity_ids=["a" + r["id"] for r in rows])
        ]
        matches = self._matches(rows)
        # The import step opens the sport; a second sync derives it from activities.
        self._garmin_gear(service, gear, matches)
        service.sync_garmin_snapshot(self._snapshot(gear, matches))
        return service, service.read()["items"][0]

    def test_open_sport_is_derived_at_three_quarters_with_three_activities(self):
        rows = [self._ride(f"r{n}") for n in range(3)]
        rows.append(self._ride("w1", type="Walk"))
        _, item = self._derived_item(rows)
        self.assertFalse(item["sport_pending"])
        self.assertEqual(item["sport"], "ride")

    def test_open_sport_stays_open_below_threshold_minimum_or_unknown(self):
        mixed = [self._ride(f"r{n}") for n in range(2)]
        mixed += [self._ride(f"u{n}", type="Run") for n in range(2)]
        few = [self._ride("r0"), self._ride("r1")]
        unknown = [self._ride(f"x{n}", type="Gadget") for n in range(4)]
        # Unknown types count toward the share: 3 of 5 linked activities is 60 %.
        diluted = [self._ride(f"r{n}") for n in range(3)]
        diluted += [self._ride(f"x{n}", type="Gadget") for n in range(2)]
        for rows in (mixed, few, unknown, diluted):
            with self.subTest(count=len(rows)):
                self.assertTrue(self._derived_item(rows)[1]["sport_pending"])
                self.manager.connection.execute("DELETE FROM kv")

    def test_open_sport_with_components_stays_open_and_set_sport_is_kept(self):
        rows = [self._ride(f"r{n}") for n in range(4)]
        service = self._gear_service(rows)
        gear = [
            self._gear_row("g1", "Gadget", activity_ids=["a" + r["id"] for r in rows])
        ]
        snapshot = self._snapshot(gear, self._matches(rows))
        item = self._garmin_gear(service, gear, snapshot["activity_matches"])["g1"]
        child_id = "00000000-0000-4000-8000-000000000002"
        self.manager.connection.execute(
            "INSERT INTO kv VALUES (?, ?, 'now')",
            (
                "equipment:" + child_id,
                json.dumps(
                    {
                        **item,
                        "id": child_id,
                        "kind": "component",
                        "garmin_uuid": None,
                        "parent_id": item["id"],
                    }
                ),
            ),
        )
        service.sync_garmin_snapshot(snapshot)
        self.assertTrue(service.read(item["id"])["items"][0]["sport_pending"])
        self.manager.connection.execute(
            "DELETE FROM kv WHERE key=?", ("equipment:" + child_id,)
        )
        service.sync_garmin_snapshot(snapshot)
        self.assertEqual(service.read()["items"][0]["sport"], "ride")
        # A sport that is already set is never replaced, even by a clear majority.
        runs = [self._ride(f"n{n}", type="Run") for n in range(4)]
        service._read_activity_rows = lambda: runs
        run_gear = [
            self._gear_row("g1", "Gadget", activity_ids=["a" + r["id"] for r in runs])
        ]
        service.sync_garmin_snapshot(self._snapshot(run_gear, self._matches(runs)))
        self.assertEqual(service.read()["items"][0]["sport"], "ride")

    def test_equipment_environment_matches_what_activity_types_express(self):
        activities = [
            {"id": "run-1", "type": "Run", "start_date_local": "2026-08-30"},
            {"id": "ride-1", "type": "Ride", "start_date_local": "2026-08-30"},
            {
                "id": "virtual-1",
                "type": "VirtualRide",
                "start_date_local": "2026-08-30",
            },
        ]
        service = EquipmentService(
            self.manager,
            lambda: activities,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
            deduplicated_rows,
        )

        def saved(name, sport, environment, kind):
            return service.save(
                {
                    "name": name,
                    "sport": sport,
                    "environment": environment,
                    "kind": kind,
                    "start_date": "2026-08-01",
                    "initial_distance_km": 0,
                    "initial_hours": 0,
                }
            )["equipment"]["id"]

        shoe = saved("Trail shoe", "run", "outdoor", "shoes")
        trainer = saved("Trainer bike", "ride", "indoor", "bike")
        service.assign({"activity_id": "run-1", "equipment_id": shoe})
        service.assign({"activity_id": "virtual-1", "equipment_id": trainer})
        with self.assertRaises(AppError):
            service.assign({"activity_id": "ride-1", "equipment_id": trainer})

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
            tuple,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
            deduplicated_rows,
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
            tuple,
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
            deduplicated_rows,
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
            self.manager,
            tuple,
            lambda: date(2026, 10, 2),
            lambda: "now",
            deduplicated_rows,
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
            lambda: [activity],
            lambda: date(2026, 9, 1),
            lambda: "2026-09-01T00:00:00Z",
            deduplicated_rows,
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
