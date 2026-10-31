"""Garmin gear links resolve to activities through canonical sessions.

An Intervals.icu activity and the same ride from Garmin are ingested, so the
session linker bundles them. A Garmin gear item listing the Garmin ride then links
the Intervals.icu row without ``activity_matches`` or ``external_id``, once, and an
explicit assignment still wins. Temporary database and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.athlete.equipment import EquipmentService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.sync import canonical_ingest
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_activity_duplicates import deduplicated_rows
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
            lambda: self.rows,
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            deduplicated_rows,
        )
        with self.manager.reader() as db:
            from backend.db import garmin_store

            self.service.sync_garmin_snapshot(
                garmin_store.read_view(db, ("gear", "activity_matches"))
            )

    def test_canonical_gear_reads_equal_the_gear_view(self) -> None:
        canonical = EquipmentService(
            self.manager,
            lambda: self.rows,
            lambda: date(2026, 10, 2),
            lambda: "2026-10-02T12:00:00Z",
            deduplicated_rows,
            gear_reader=CanonicalTableReader(),
        )
        read = canonical.read()
        self.assertEqual(read, self.service.read())
        (item,) = read["items"]
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


if __name__ == "__main__":
    unittest.main()
