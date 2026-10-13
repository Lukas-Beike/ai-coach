"""Populated databases of every released schema upgrade to canonical sports.

Each frozen released schema is opened by the current build on temporary SQLCipher
storage; equipment, competitions, library entries and planned units are read and
edited through the real services, the process restarts, and the Intervals.icu
payloads must equal the ones the legacy stored tokens produced.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from server_test_support import ServerTestCase, server

from backend.db.manager import DATABASE_MANAGER_CACHE
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
)
from backend.planning.competitions import competition_event_payload
from backend.planning.workouts import (
    library_workout_event_payload,
    library_workout_payload,
    workout_event_payload,
)

FIXTURES = Path(__file__).with_name("fixtures")
RELEASED_SCHEMAS = (
    "schema_1_12_19",
    "schema_v2",
    "schema_1_12_26",
    "schema_v4",
    "schema_v5",
    "schema_v6",
    "schema_v7",
    "schema_v8",
)
STAMP = "2026-10-01T08:00:00+00:00"
TODAY = date(2026, 10, 1)
PLAN_DATE = "2026-11-02"
STEP_TEXT = "- 30m Z2"

# legacy stored token -> (wire type the legacy build produced, canonical sport)
WORKOUT_CASES = {
    "VirtualRide": ("VirtualRide", "ride", "virtual"),
    "WeightTraining": ("WeightTraining", "strength", "unknown"),
    "Basket weaving": ("Other", "other", "unknown"),
}
COMPETITION_CASES = {
    "VirtualRide": ("VirtualRide", "ride", "virtual"),
    "Obstacle course": ("Obstacle course", "other", "unknown"),
}
EQUIPMENT_CASES = {
    "VirtualRide": ("ride", "virtual", False),
    "Cross-country skiing": ("other", "unknown", True),
    "": ("other", "unknown", True),
}


def _equipment_id(index: int) -> str:
    return f"30000000-0000-4000-8000-00000000000{index}"


def _local_id(table: str, index: int) -> str:
    prefix = "1" if table == "workout_library" else "2"
    return f"{prefix}0000000-0000-4000-8000-00000000000{index}"


def _workout_payload(token: str, index: int, *, dated: bool) -> dict[str, Any]:
    payload = {
        "name": f"w{index}",
        "type": token,
        "description": STEP_TEXT,
        "duration_minutes": 30,
        "moving_time": 1800,
        "target": "AUTO",
    }
    if dated:
        payload["date"] = PLAN_DATE
    return payload


@unittest.skipUnless(
    server.SQLCIPHER_AVAILABLE, "SQLCipher requires the Docker runtime on Windows"
)
class CanonicalSportsUpgradeEndToEndTests(ServerTestCase):
    def _seed(self, path: Path, config: Any, schema: str) -> None:
        connection = server.sqlite_backend.connect(path)
        try:
            configure_cipher(connection, config.app_password)
            text = (FIXTURES / f"{schema}.sql.txt").read_text(encoding="utf-8")
            connection.executescript(text)
            for index, token in enumerate(EQUIPMENT_CASES):
                item = {
                    "id": _equipment_id(index),
                    "name": f"Bike {index}",
                    "sport": token,
                    "kind": "bike",
                    "status": "active",
                    "parent_id": None,
                    "start_date": "2026-01-01",
                    "initial_distance_km": 0,
                    "initial_hours": 0,
                    "maintenance_km": None,
                    "maintenance_hours": None,
                    "lifetime_target_km": None,
                    "revision": 1,
                }
                connection.execute(
                    "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                    (f"equipment:{_equipment_id(index)}", json.dumps(item), STAMP),
                )
            for index, token in enumerate(COMPETITION_CASES):
                connection.execute(
                    "INSERT INTO competitions(id, name, event_date, sport, priority, "
                    "distance, target, course_profile, notes, created_at, updated_at) "
                    "VALUES (?, ?, '2026-12-01', ?, 'B', '', '', '', '', ?, ?)",
                    (f"c{index}", f"c{index}", token, STAMP, STAMP),
                )
            for index, token in enumerate(WORKOUT_CASES):
                for table in ("workout_library", "planned_units"):
                    payload = json.dumps(
                        _workout_payload(token, index, dated=table == "planned_units")
                    )
                    columns = "id, local_id, payload, "
                    columns += (
                        "updated_at"
                        if table == "workout_library"
                        else ("created_at, updated_at")
                    )
                    marks = "?, ?, ?, ?" + ("" if table == "workout_library" else ", ?")
                    local_id = _local_id(table, index)
                    values = [local_id, local_id, payload, STAMP]
                    if table == "planned_units":
                        values.append(STAMP)
                    connection.execute(
                        f"INSERT INTO {table}({columns}) VALUES ({marks})", values
                    )
            connection.commit()
        finally:
            connection.close()

    def _restart(self) -> None:
        DATABASE_MANAGER_CACHE.reset()
        server.initialise_database()

    def _assert_reads(self) -> None:
        equipment = server.ATHLETE_DATA.equipment().read()["items"]
        by_id = {item["id"]: item for item in equipment}
        for index, expected in enumerate(EQUIPMENT_CASES.values()):
            item = by_id[_equipment_id(index)]
            self.assertEqual(
                (item["sport"], item["environment"], item["sport_pending"]), expected
            )
        listed = {c["name"]: c for c in server.PLANNING_DATA.competition().list()}
        for index, (wire, sport, environment) in enumerate(COMPETITION_CASES.values()):
            competition = listed[f"c{index}"]
            self.assertEqual(competition["sport"], sport)
            self.assertEqual(competition["environment"], environment)
            self.assertEqual(competition_event_payload(competition)["type"], wire)
        library = {w["name"]: w for w in server.PLANNING_DATA.workout_library().list()}
        planned = {w["name"]: w for w in server.PLANNING_DATA.planned_unit().list(500)}
        for index, (token, (wire, sport, _)) in enumerate(WORKOUT_CASES.items()):
            for source in (library, planned):
                record = source[f"w{index}"]
                self.assertEqual(record["sport"], sport, token)
                self.assertEqual(record["type"], wire, token)
            self.assertEqual(
                library_workout_payload(library[f"w{index}"])["type"], wire
            )
            event = workout_event_payload(
                f"planned-{index}", planned[f"w{index}"], today=TODAY
            )
            library_event = library_workout_event_payload(
                f"w{index}", library[f"w{index}"], PLAN_DATE, today=TODAY
            )
            self.assertEqual(event["type"], wire)
            self.assertEqual(library_event["type"], wire)

    def _edit_records(self) -> None:
        competition = server.PLANNING_DATA.competition()
        saved = competition.save(
            {"id": "c1", "name": "c1", "event_date": "2026-12-01", "sport": "Cycling"}
        )
        self.assertEqual(saved["competition"]["sport"], "ride")
        saved = competition.save(
            {"id": "c0", "name": "c0", "event_date": "2026-12-01", "sport": "run"}
        )
        self.assertEqual(saved["competition"]["sport"], "run")
        library = server.PLANNING_DATA.workout_library()
        library.update(_local_id("workout_library", 0), {"name": "w0", "sport": "Run"})
        self.assertEqual(
            library_workout_payload(
                next(w for w in library.list() if w["name"] == "w0")
            )["type"],
            "Run",
        )
        server.PLANNING_DATA.planned_unit().update(
            _local_id("planned_units", 1), {"name": "w1", "sport": "ride"}
        )
        equipment = server.ATHLETE_DATA.equipment()
        item = equipment.save(
            {
                "id": _equipment_id(2),
                "name": "Bike 2",
                "kind": "bike",
                "start_date": "2026-01-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
                "expected_revision": 1,
                "sport": "run",
                "environment": "outdoor",
            }
        )["equipment"]
        self.assertEqual(item["sport"], "run")

    def test_every_released_schema_upgrades_reads_edits_and_exports(self) -> None:
        for schema in RELEASED_SCHEMAS:
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "intervals-coach.db"
                config = replace(
                    server.CONFIG,
                    app_password="synthetic-upgrade-password",
                    data_retention_days=-1,
                )
                self._seed(path, config, schema)
                try:
                    with (
                        patch.object(server, "DATA_DIR", Path(root)),
                        patch.object(server, "DB_PATH", path),
                        patch.object(server, "CONFIG", config),
                    ):
                        DATABASE_MANAGER_CACHE.reset()
                        server.initialise_database()
                        with server.database_manager().reader() as db:
                            self.assertTrue(database_schema_is_current(db))
                            self.assertEqual(
                                db.execute("PRAGMA user_version").fetchone()[
                                    "user_version"
                                ],
                                CURRENT_SCHEMA_VERSION,
                            )
                        self._assert_reads()
                        self._restart()
                        self._assert_reads()
                        self._edit_records()
                        self._restart()
                        competitions = {
                            c["name"]: c
                            for c in server.PLANNING_DATA.competition().list()
                        }
                        self.assertEqual(competitions["c1"]["sport"], "ride")
                        self.assertEqual(competitions["c0"]["sport"], "run")
                finally:
                    DATABASE_MANAGER_CACHE.reset()


if __name__ == "__main__":
    unittest.main()
