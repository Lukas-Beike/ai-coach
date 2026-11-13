"""Garmin gear links resolve to activities through canonical sessions.

A Wahoo ride and the same ride from Garmin are ingested, so the session linker
bundles them. A Garmin gear item listing the Garmin ride then links the bundled
session without ``activity_matches`` or ``external_id``, once, and an explicit
assignment still wins. Temporary database and synthetic rows only.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from support import temp_database
from test_feedback_session_identity import ingest_wahoo, wahoo_row

from backend.activities.activity_summary import activity_summaries
from backend.athlete.equipment import EquipmentService
from backend.db import canonical_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api.athlete_assembly import AthleteDataAssembly
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

ZONE = ZoneInfo("Europe/Berlin")
SYNCED = "2026-09-20T08:00:00+00:00"


def session_of(manager: Any, provider_activity_id: str, provider: str = "wahoo") -> str:
    """The live session id a provider activity belongs to."""
    with manager.reader() as db:
        local = canonical_store.activity_local_ids(
            db, provider, [provider_activity_id]
        )[provider_activity_id]
        return canonical_store.effective_session_ids(db, [local])[local]


def canonical_store_local_id(
    manager: Any, provider_activity_id: str, provider: str = "wahoo"
) -> str:
    """The session id of the record itself, before any merge."""
    with manager.reader() as db:
        return canonical_store.activity_local_ids(db, provider, [provider_activity_id])[
            provider_activity_id
        ]


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
        self.manager = temp_database(self, "gear.db", row_factory=row_factory)
        key_values = KeyValueRepository(lambda: SYNCED)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            ingest_wahoo(db, [wahoo_row("601")])
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

    def equipment_rows(self) -> list[tuple[str, str, str]]:
        with self.manager.reader() as db:
            return [
                (row["key"], row["value"], row["updated_at"])
                for row in db.execute(
                    "SELECT key, value, updated_at FROM kv "
                    "WHERE key LIKE 'equipment:%' ORDER BY key"
                ).fetchall()
            ]

    def synced_later(self, clock: str) -> None:
        service = EquipmentService(
            self.manager,
            lambda: stored_summaries(self.manager),
            lambda: date(2026, 10, 2),
            lambda: clock,
            gear_reader=CanonicalTableReader(),
        )
        with self.manager.reader() as db:
            from backend.db import garmin_store

            service.sync_garmin_snapshot(garmin_store.read_state(db))

    def test_equipment_read_takes_no_writer(self) -> None:
        with patch.object(
            self.manager, "unit_of_work", side_effect=AssertionError("writer taken")
        ):
            (item,) = self.service.read()["items"]
            self.service.read(item["id"])
        self.assertEqual(item["garmin_uuid"], "g1")

    def test_assembled_activity_summaries_take_no_writer(self) -> None:
        # The production read_summaries callback, not the test's stand-in.
        assembly = object.__new__(AthleteDataAssembly)
        assembly._database_manager = lambda: self.manager
        rows = Mock()
        rows.activity_summaries.return_value = ()
        assembly._activity_rows = lambda: rows
        with patch.object(
            self.manager, "unit_of_work", side_effect=AssertionError("writer taken")
        ):
            self.assertEqual(assembly.activity_summaries(), ())
        rows.activity_summaries.assert_called_once()

    def test_repeated_gear_syncs_with_unchanged_values_rewrite_nothing(self) -> None:
        before = self.equipment_rows()
        self.assertEqual(len(before), 1)
        self.assertEqual(json.loads(before[0][1])["lifetime_target_km"], 10000.0)

        self.synced_later("2026-10-03T12:00:00Z")
        self.synced_later("2026-10-04T12:00:00Z")

        self.assertEqual(self.equipment_rows(), before)

    def test_a_changed_garmin_maximum_still_updates_the_row(self) -> None:
        before = self.equipment_rows()
        with self.manager.unit_of_work() as db:
            GarminSnapshotWriter(
                KeyValueRepository(lambda: SYNCED), lambda: ZONE
            ).write(
                db,
                {
                    "synced_at": "2026-09-21T08:00:00+00:00",
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
                            "maximumMeters": 12_000_000,
                        }
                    ],
                },
            )

        self.synced_later("2026-10-05T12:00:00Z")

        (key, value, updated_at) = self.equipment_rows()[0]
        self.assertEqual(key, before[0][0])
        self.assertEqual(json.loads(value)["lifetime_target_km"], 12000.0)
        self.assertEqual(updated_at, "2026-10-05T12:00:00Z")

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

    def test_the_garmin_ride_links_the_bundled_wahoo_session_once(self) -> None:
        links = self.links()
        session = session_of(self.manager, "601")
        self.assertEqual(set(links), {session})
        self.assertEqual(links[session]["source"], "garmin_gear")
        (item,) = self.service.read()["items"]
        self.assertEqual(item["usage"]["assigned_sessions"], 1)

    def test_an_explicit_assignment_still_wins(self) -> None:
        self.service.assign({"activity_id": "601", "equipment_id": None})
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
        self.manager = temp_database(self, "gear.db", row_factory=row_factory)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            ingest_wahoo(db, [wahoo_row("601"), wahoo_row("602")])
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
                    "activity_id": session_of(self.manager, "601"),
                    "equipment_id": by_gear["g1"]["id"],
                    "source": "garmin_gear",
                }
            ],
        )


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
    """Sessions without a Wahoo record count like any other session."""

    def setUp(self) -> None:
        self.manager = temp_database(self, "sessions.db", row_factory=row_factory)
        self.wahoo: list[dict[str, Any]] = [wahoo_summary("w1")]
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            ingest_wahoo(db, [wahoo_row("601")])
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
            if "wahoo" not in summary["record_ids"]
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
        # Both rides are keyed by their session id.
        self.assertEqual(
            set(links), {session_of(self.manager, "601"), self.garmin_only_session()}
        )
        usage = self.usage("Road bike")
        self.assertEqual(usage["assigned_sessions"], 2)
        self.assertEqual(usage["hours"], 1.5)

    def test_a_second_bundled_provider_id_names_the_session_for_assign(self) -> None:
        with self.manager.reader() as db:
            from backend.db import canonical_store

            session = canonical_store.live_session_id(db, "910")
        self.assertIsNotNone(session)
        bike = self.local_bike()
        saved = self.service.assign({"activity_id": "910", "equipment_id": bike["id"]})
        # Stored under the session of the record named, not the survivor.
        self.assertEqual(
            saved["assignment"]["activity_id"],
            canonical_store_local_id(self.manager, "910", "garmin"),
        )

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

    def test_bundled_session_counts_once_under_its_session_id(self) -> None:
        bike = self.local_bike()
        (bundled,) = (
            summary
            for summary in stored_summaries(self.manager)
            if "wahoo" in summary["record_ids"]
        )
        self.assertEqual(set(bundled["record_ids"]), {"wahoo", "garmin"})
        saved = self.service.assign(
            {"activity_id": bundled["id"], "equipment_id": bike["id"]}
        )
        self.assertEqual(saved["assignment"]["activity_id"], bundled["id"])
        usage = self.usage("Local bike")
        self.assertEqual(usage["assigned_sessions"], 1)
        self.assertEqual(usage["hours"], 1)
        self.assertEqual(usage["distance_km"], 20)

    def test_assignment_stored_under_a_provider_id_still_applies(self) -> None:
        bike = self.local_bike()
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                (
                    "equipment_assignment:i1",
                    json.dumps(
                        {
                            "activity_id": "601",
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

    def store_assignment(self, key: str, equipment_id: Any, observed_at: str) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (
                    "equipment_assignment:" + key,
                    json.dumps(
                        {
                            "activity_id": key,
                            "equipment_id": equipment_id,
                            "observed_at": observed_at,
                        }
                    ),
                    observed_at,
                ),
            )

    def test_a_legacy_assignment_is_listed_under_the_session_id(self) -> None:
        bike = self.local_bike()
        session = session_of(self.manager, "601")
        self.store_assignment("601", bike["id"], SYNCED)

        (listed,) = self.service.read(activity_id=session)["assignments"]

        self.assertEqual(
            (listed["activity_id"], listed["equipment_id"]), (session, bike["id"])
        )
        self.assertEqual(self.service.read(activity_id="601")["assignments"], [])

    def test_an_assignment_under_the_session_id_wins_over_a_legacy_one(self) -> None:
        old, new = self.local_bike(name="Old bike"), self.local_bike(name="New bike")
        session = session_of(self.manager, "601")
        self.store_assignment(session, new["id"], "2026-09-19T08:00:00+00:00")
        # The legacy row is the newer one, yet the session-id row still wins.
        self.store_assignment("601", old["id"], "2026-09-21T08:00:00+00:00")

        (listed,) = self.service.read(activity_id=session)["assignments"]

        self.assertEqual(listed["equipment_id"], new["id"])
        self.assertEqual(self.usage("New bike")["assigned_sessions"], 1)
        self.assertEqual(self.usage("Old bike")["assigned_sessions"], 0)

    def test_an_assignment_under_an_alias_session_id_applies_and_newest_wins(
        self,
    ) -> None:
        old, new = self.local_bike(name="Old bike"), self.local_bike(name="New bike")
        session = session_of(self.manager, "601")
        with self.manager.reader() as db:
            local = canonical_store.activity_local_ids(db, "garmin", ["910"])["910"]
        alias = local if local != session else None
        if alias is None:
            with self.manager.reader() as db:
                alias = canonical_store.activity_local_ids(db, "wahoo", ["601"])["601"]
        self.assertNotEqual(alias, session)
        # The record-id row is older, the alias-session row newer: it wins.
        self.store_assignment("601", old["id"], "2026-09-19T08:00:00+00:00")
        self.store_assignment(alias, new["id"], "2026-09-21T08:00:00+00:00")

        (listed,) = self.service.read(activity_id=session)["assignments"]

        self.assertEqual(listed["equipment_id"], new["id"])
        self.assertEqual(self.usage("New bike")["assigned_sessions"], 1)
        self.assertEqual(self.usage("Old bike")["assigned_sessions"], 0)

    def test_an_older_alias_row_loses_to_a_newer_record_id_row(self) -> None:
        old, new = self.local_bike(name="Old bike"), self.local_bike(name="New bike")
        session = session_of(self.manager, "601")
        with self.manager.reader() as db:
            local = canonical_store.activity_local_ids(db, "garmin", ["910"])["910"]
        alias = local if local != session else None
        if alias is None:
            with self.manager.reader() as db:
                alias = canonical_store.activity_local_ids(db, "wahoo", ["601"])["601"]
        # The alias-session id sorts first but is older: the newest still wins.
        self.store_assignment(alias, old["id"], "2026-09-19T08:00:00+00:00")
        self.store_assignment("601", new["id"], "2026-09-21T08:00:00+00:00")

        (listed,) = self.service.read(activity_id=session)["assignments"]

        self.assertEqual(listed["equipment_id"], new["id"])

    def test_an_assignment_is_stored_under_the_session_it_was_made_through(
        self,
    ) -> None:
        bike = self.local_bike()
        own = canonical_store_local_id(self.manager, "601")

        saved = self.service.assign({"activity_id": "601", "equipment_id": bike["id"]})

        self.assertEqual(saved["assignment"]["activity_id"], own)
        (listed,) = self.service.read(activity_id=session_of(self.manager, "601"))[
            "assignments"
        ]
        self.assertEqual(listed["equipment_id"], bike["id"])
        # A later assignment through the other copy replaces it, never doubles it.
        other = self.local_bike(name="Other bike")
        self.service.assign({"activity_id": "910", "equipment_id": other["id"]})
        (listed,) = self.service.read(activity_id=session_of(self.manager, "601"))[
            "assignments"
        ]
        self.assertEqual(listed["equipment_id"], other["id"])

    def test_a_legacy_unassignment_still_overrides_the_garmin_link(self) -> None:
        with self.manager.reader() as db:
            from backend.db import garmin_store

            self.service.sync_garmin_snapshot(garmin_store.read_state(db))
        self.assertEqual(self.usage("Road bike")["assigned_sessions"], 2)
        self.store_assignment("601", None, SYNCED)

        self.assertEqual(self.usage("Road bike")["assigned_sessions"], 1)


if __name__ == "__main__":
    unittest.main()
