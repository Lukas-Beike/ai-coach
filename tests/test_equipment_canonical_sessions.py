"""Garmin gear links resolve to activities through canonical sessions.

An Intervals.icu activity and the same ride from Garmin are ingested, so the
session linker bundles them. A Garmin gear item listing the Garmin ride then links
the Intervals.icu row without ``activity_matches`` or ``external_id``, once, and an
explicit assignment still wins. Temporary database and synthetic rows only.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import activity_summaries
from backend.activities.session_linking import garmin_activity_matches
from backend.athlete.equipment import EquipmentService
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.sync import canonical_ingest
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

ZONE = ZoneInfo("Europe/Berlin")
SYNCED = "2026-09-20T08:00:00+00:00"


def intervals_row(identifier: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "start_date_local": "2026-09-10T07:00:00",
        "type": "Ride",
        "distance": 20000.0,
        "moving_time": 3600,
        "elapsed_time": 3600,
    }


def stored_summaries(manager: Any) -> Any:
    with manager.reader() as db:
        return activity_summaries(CanonicalTableReader().activity_sessions(db), ZONE)


def garmin_activity(identifier: int) -> dict[str, Any]:
    return {
        "activityId": identifier,
        "activityName": "Synthetic ride",
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-09-10 07:00:00",
        "distance": 20000.0,
        "duration": 3600.0,
    }


class EquipmentSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "gear.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        key_values = KeyValueRepository(lambda: SYNCED)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": SYNCED,
                    "raw_provider_data": {"activities": [intervals_row("i1")]},
                },
                zone=ZONE,
            )
            GarminSnapshotWriter(key_values, lambda: ZONE).write(
                db,
                {
                    "synced_at": SYNCED,
                    "activities": [garmin_activity(910)],
                    "source_freshness": {"gear": {"freshness": "current"}},
                    "gear": [
                        {
                            "gearUUID": "g1",
                            "gearName": "Road bike",
                            "gearTypeName": "Bike",
                            "stats": {"totalDistance": 50000},
                            "activity_ids": ["910"],
                            "activity_ids_truncated": True,
                            "maximumMeters": 10_000_000,
                        }
                    ],
                },
            )
        self.rows = [intervals_row("i1")]
        self.service = EquipmentService(
            self.manager,
            lambda: stored_summaries(self.manager),
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            gear_reader=CanonicalTableReader(),
        )
        with self.manager.reader() as db:
            from backend.db import garmin_store

            # The sync passes its payload; equipment reads only its gear freshness.
            self.service.sync_garmin_snapshot(garmin_store.read_state(db))

    def test_canonical_gear_keeps_the_partial_activity_list(self) -> None:
        (item,) = self.service.read()["items"]
        self.assertTrue(item["usage"]["assigned_sessions"])
        with self.manager.reader() as db:
            (gear,) = CanonicalTableReader().gear_items(db)
        self.assertIs(gear.activity_list_partial, True)

    def test_gear_removed_in_garmin_leaves_the_canonical_reads(self) -> None:
        with self.manager.unit_of_work() as db:
            GarminSnapshotWriter(
                KeyValueRepository(lambda: SYNCED), lambda: ZONE
            ).write(
                db,
                {
                    "synced_at": "2026-09-21T08:00:00+00:00",
                    "source_freshness": {"gear": {"freshness": "current"}},
                    "gear": [],
                },
            )
        with self.manager.reader() as db:
            reader = CanonicalTableReader()
            self.assertEqual(
                (reader.gear_items(db), reader.gear_activity_links(db)), ((), ())
            )
            states = {
                row["state"]
                for row in db.execute("SELECT state FROM gear_items").fetchall()
            }
        self.assertEqual(states, {"retired"})

    def links(self) -> dict[str, Any]:
        return {row["activity_id"]: row for row in self.service.read()["assignments"]}

    def test_the_garmin_ride_links_the_bundled_intervals_row_once(self) -> None:
        links = self.links()
        self.assertEqual(set(links), {"i1"})
        self.assertEqual(links["i1"]["source"], "garmin_gear")
        (item,) = self.service.read()["items"]
        self.assertEqual(item["usage"]["assigned_sessions"], 1)

    def test_an_explicit_assignment_still_wins(self) -> None:
        self.service.assign({"activity_id": "i1", "equipment_id": None})
        (item,) = self.service.read()["items"]
        self.assertEqual(item["usage"]["assigned_sessions"], 0)


PARITY_GEAR = [
    {
        "gearUUID": "g1",
        "gearName": "Road bike",
        "gearTypeName": "Bike",
        "gearStatusName": "Active",
        "stats": {"totalDistance": 50000, "totalActivities": 4},
        "activity_ids": ["910"],
        "activity_ids_truncated": True,
        "maximumMeters": 10_000_000,
    },
    {
        "gearUUID": "g2",
        "gearName": "Old running shoes",
        "gearTypeName": "Shoes",
        "gearStatusName": "Retired",
        "stats": {},
    },
    {
        "gearUUID": "g3",
        "gearName": "Chain",
        "gearTypeName": "Bike",
        "activityTypeName": "Cycling",
        "stats": {"totalDistance": 1234.5},
        "activity_ids": [],
    },
]
# The Garmin items the deleted raw-view reader listed for PARITY_GEAR (#1416).
PARITY_GARMIN_ITEMS = [
    {
        "id": "g1",
        "name": "Road bike",
        "kind": "Bike",
        "status": "active",
        "garmin_status": "Active",
        "distance_km": 50.0,
        "goal_km": 10000.0,
        "usage_percent": 0.5,
        "lifetime": {
            "usage_km": 50.0,
            "target_km": 10000.0,
            "percent": 0.5,
            "progress_percent": 0.5,
        },
        "sessions": 4.0,
        "source": "Garmin Connect",
    },
    {
        "id": "g2",
        "name": "Old running shoes",
        "kind": "Shoes",
        "status": "archived",
        "garmin_status": "Retired",
        "distance_km": None,
        "goal_km": None,
        "usage_percent": None,
        "lifetime": None,
        "sessions": None,
        "source": "Garmin Connect",
    },
    {
        "id": "g3",
        "name": "Chain",
        "kind": "Bike",
        "status": "active",
        "garmin_status": "",
        "distance_km": 1.23,
        "goal_km": None,
        "usage_percent": None,
        "lifetime": None,
        "sessions": None,
        "source": "Garmin Connect",
    },
]


class CanonicalGearParityTests(unittest.TestCase):
    """The canonical gear read gives what the deleted raw-view reader gave.

    The pinned values were produced by the raw ``gear`` and ``activity_matches``
    reader on the same payload before #1416 removed it.
    """

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "gear.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        self.rows = [intervals_row("i1"), intervals_row("i2")]
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {"synced_at": SYNCED, "raw_provider_data": {"activities": self.rows}},
                zone=ZONE,
            )
            GarminSnapshotWriter(
                KeyValueRepository(lambda: SYNCED), lambda: ZONE
            ).write(
                db,
                {
                    "synced_at": SYNCED,
                    "activities": [garmin_activity(910)],
                    "source_freshness": {"gear": {"freshness": "current"}},
                    "gear": PARITY_GEAR,
                },
            )
        self.service = EquipmentService(
            self.manager,
            lambda: stored_summaries(self.manager),
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            gear_reader=CanonicalTableReader(),
        )

    def test_garmin_items_before_the_import_match_the_raw_view(self) -> None:
        read = self.service.read()
        self.assertEqual(read["garmin_items"], PARITY_GARMIN_ITEMS)
        self.assertEqual(read["garmin_synced_at"], SYNCED)
        self.assertEqual(read["garmin_freshness"], "current")

    def test_imported_items_and_links_match_the_raw_view(self) -> None:
        with self.manager.reader() as db:
            from backend.db import garmin_store

            self.service.sync_garmin_snapshot(garmin_store.read_state(db))
        read = self.service.read()
        self.assertEqual(read["garmin_items"], [])
        by_gear = {item["garmin_uuid"]: item for item in read["items"]}
        self.assertEqual(
            {
                gear: (
                    item["kind"],
                    item["sport"],
                    item["status"],
                    item["garmin_distance_km"],
                    item["lifetime_target_km"],
                    item["parent_pending"],
                    item["usage"]["assigned_sessions"],
                )
                for gear, item in by_gear.items()
            },
            {
                "g1": ("bike", "ride", "active", 50.0, 10000.0, False, 1),
                "g2": ("shoes", "run", "archived", None, None, False, 0),
                "g3": ("component", "ride", "active", 1.23, None, True, 0),
            },
        )
        self.assertEqual(
            read["assignments"],
            [
                {
                    "activity_id": "i1",
                    "equipment_id": by_gear["g1"]["id"],
                    "source": "garmin_gear",
                }
            ],
        )


class CanonicalDuplicatePairTests(unittest.TestCase):
    """A Garmin gear ride links every Intervals.icu ride the duplicate rule pairs.

    Two Intervals.icu recordings match the Garmin ride; bundling gives the Garmin
    record to one of them, the pairwise rule still pairs both, as the stored
    matches of the raw view did.
    """

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "pairs.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        self.rows = [intervals_row("i1"), intervals_row("i2")]
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {"synced_at": SYNCED, "raw_provider_data": {"activities": self.rows}},
                zone=ZONE,
            )
            GarminSnapshotWriter(
                KeyValueRepository(lambda: SYNCED), lambda: ZONE
            ).write(
                db,
                {
                    "synced_at": SYNCED,
                    "activities": [garmin_activity(910)],
                    "source_freshness": {"gear": {"freshness": "current"}},
                    "gear": [
                        {
                            "gearUUID": "g1",
                            "gearName": "Road bike",
                            "gearTypeName": "Bike",
                            "stats": {"totalDistance": 50000},
                            "activity_ids": ["910"],
                        }
                    ],
                },
            )

    def service(self, matcher: Any) -> EquipmentService:
        return EquipmentService(
            self.manager,
            lambda: stored_summaries(self.manager),
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            gear_reader=CanonicalTableReader(),
            match_activities=matcher,
        )

    def links(self, service: EquipmentService) -> set[str]:
        with self.manager.reader() as db:
            from backend.db import garmin_store

            service.sync_garmin_snapshot(garmin_store.read_state(db))
        return {row["activity_id"] for row in service.read()["assignments"]}

    def test_the_pairwise_rule_pairs_both_recordings(self) -> None:
        with self.manager.reader() as db:
            matches = garmin_activity_matches(db, ["910"], ["i1", "i2"], zone=ZONE)
            sessions = canonical_store.provider_activity_sessions(
                db, "intervals", ["i1", "i2"]
            )
        self.assertEqual(matches, {"910": {"i1", "i2"}})
        # Bundling kept the two recordings in separate sessions.
        self.assertNotEqual(sessions["i1"], sessions["i2"])

    def test_gear_links_every_paired_recording(self) -> None:
        def matcher(db: Any, garmin_ids: Any, intervals_ids: Any) -> Any:
            return garmin_activity_matches(db, garmin_ids, intervals_ids, zone=ZONE)

        self.assertEqual(self.links(self.service(matcher)), {"i1", "i2"})

    def test_without_the_pairs_only_the_bundled_session_links(self) -> None:
        self.assertEqual(len(self.links(self.service(None))), 1)


def wahoo_summary(identifier: str, day: str = "2026-09-10") -> dict[str, Any]:
    """A session summary that holds only a Wahoo record."""
    return {
        "id": "act_" + identifier,
        "started_at": day + "T07:00:00+00:00",
        "started_at_local": day + "T07:00:00",
        "sport": "ride",
        "environment": "unknown",
        "record_ids": {"wahoo": identifier},
        "distance_m": 30000.0,
        "moving_duration_s": 5400.0,
    }


class SessionOnlyEquipmentTests(unittest.TestCase):
    """Sessions without an Intervals.icu record count like any other session."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "sessions.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        self.wahoo: list[dict[str, Any]] = [wahoo_summary("w1")]
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": SYNCED,
                    "raw_provider_data": {"activities": [intervals_row("i1")]},
                },
                zone=ZONE,
            )
            GarminSnapshotWriter(
                KeyValueRepository(lambda: SYNCED), lambda: ZONE
            ).write(
                db,
                {
                    "synced_at": SYNCED,
                    "activities": [
                        garmin_activity(910),
                        {
                            **garmin_activity(911),
                            "startTimeLocal": "2026-09-12 07:00:00",
                            "distance": 10000.0,
                            "duration": 1800.0,
                        },
                    ],
                    "source_freshness": {"gear": {"freshness": "current"}},
                    "gear": [
                        {
                            "gearUUID": "g1",
                            "gearName": "Road bike",
                            "gearTypeName": "Bike",
                            "stats": {"totalDistance": 50000},
                            "activity_ids": ["910", "911"],
                        }
                    ],
                },
            )
        self.service = EquipmentService(
            self.manager,
            lambda: (*stored_summaries(self.manager), *self.wahoo),
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            gear_reader=CanonicalTableReader(),
        )

    def garmin_only_session(self) -> str:
        (session,) = (
            summary["id"]
            for summary in stored_summaries(self.manager)
            if "intervals" not in summary["record_ids"]
        )
        return str(session)

    def local_bike(self, **extra: Any) -> dict[str, Any]:
        return self.service.save(
            {
                "name": "Local bike",
                "sport": "ride",
                "kind": "bike",
                "start_date": "2026-08-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
                **extra,
            }
        )["equipment"]

    def usage(self, name: str) -> dict[str, Any]:
        items = {item["name"]: item for item in self.service.read()["items"]}
        return items[name]["usage"]

    def test_garmin_gear_links_the_garmin_only_session_and_the_bundled_one(
        self,
    ) -> None:
        with self.manager.reader() as db:
            from backend.db import garmin_store

            self.service.sync_garmin_snapshot(garmin_store.read_state(db))
        links = {row["activity_id"]: row for row in self.service.read()["assignments"]}
        # The bundled ride keeps its Intervals.icu key, the Garmin-only one its session id.
        self.assertEqual(set(links), {"i1", self.garmin_only_session()})
        usage = self.usage("Road bike")
        self.assertEqual(usage["assigned_sessions"], 2)
        self.assertEqual(usage["hours"], 1.5)

    def test_wahoo_only_session_counts_in_usage_hours_distance_and_maintenance(
        self,
    ) -> None:
        bike = self.local_bike(maintenance_km=25, maintenance_hours=1)
        self.service.assign({"activity_id": "act_w1", "equipment_id": bike["id"]})
        usage = self.usage("Local bike")
        self.assertEqual(usage["assigned_sessions"], 1)
        self.assertEqual(usage["distance_km"], 30)
        self.assertEqual(usage["hours"], 1.5)
        self.assertEqual(usage["maintenance_distance_km"], 30)
        self.assertEqual(usage["maintenance_hours"], 1.5)
        self.assertIs(usage["maintenance_due"], True)

    def test_garmin_only_session_can_be_assigned_and_counts_in_usage(self) -> None:
        session = self.garmin_only_session()
        bike = self.local_bike()
        saved = self.service.assign(
            {"activity_id": session, "equipment_id": bike["id"]}
        )
        self.assertEqual(saved["assignment"]["activity_id"], session)
        usage = self.usage("Local bike")
        self.assertEqual(usage["assigned_sessions"], 1)
        self.assertEqual(usage["distance_km"], 10)
        self.assertEqual(usage["hours"], 0.5)

    def test_a_provider_id_names_the_session(self) -> None:
        bike = self.local_bike()
        saved = self.service.assign({"activity_id": "w1", "equipment_id": bike["id"]})
        self.assertEqual(saved["assignment"]["activity_id"], "act_w1")

    def test_unknown_session_keeps_the_not_found_answer(self) -> None:
        bike = self.local_bike()
        with self.assertRaises(AppError) as raised:
            self.service.assign({"activity_id": "act_nope", "equipment_id": bike["id"]})
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(str(raised.exception), "Kanonische Aktivität nicht gefunden.")

    def test_bundled_session_counts_once_under_its_intervals_key(self) -> None:
        bike = self.local_bike()
        (bundled,) = (
            summary
            for summary in stored_summaries(self.manager)
            if "intervals" in summary["record_ids"]
        )
        self.assertEqual(set(bundled["record_ids"]), {"intervals", "garmin"})
        saved = self.service.assign(
            {"activity_id": bundled["id"], "equipment_id": bike["id"]}
        )
        self.assertEqual(saved["assignment"]["activity_id"], "i1")
        usage = self.usage("Local bike")
        self.assertEqual(usage["assigned_sessions"], 1)
        self.assertEqual(usage["hours"], 1)
        self.assertEqual(usage["distance_km"], 20)

    def test_assignment_stored_under_an_intervals_id_still_applies(self) -> None:
        bike = self.local_bike()
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                (
                    "equipment_assignment:i1",
                    json.dumps(
                        {
                            "activity_id": "i1",
                            "equipment_id": bike["id"],
                            "observed_at": SYNCED,
                        }
                    ),
                    SYNCED,
                ),
            )
        usage = self.usage("Local bike")
        self.assertEqual(usage["assigned_sessions"], 1)
        self.assertEqual(usage["distance_km"], 20)


if __name__ == "__main__":
    unittest.main()
