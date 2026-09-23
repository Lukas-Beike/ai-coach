"""Tests for atomic local workout-library planning."""

from __future__ import annotations

import ast
import inspect
import itertools
import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.db.manager import DatabaseManager
from backend.db.repositories import PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import (
    CORRUPT_LIBRARY_ERROR,
    INVALID_LIBRARY_ID_ERROR,
    INVALID_PLANNING_DATE_ERROR,
    AppError,
)
from backend.planning import library_plan_service
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService

NOW = "2026-09-20T08:00:00+00:00"
TODAY = "2026-09-20"


class CalendarConflictFake:
    def __init__(self, database_manager):
        self.database_manager = database_manager
        self.calls = []
        self.results = {}
        self.timeline = []

    def conflicts(self, workout, exclude_library_ids):
        self.calls.append((workout, exclude_library_ids))
        self.timeline.append("conflict")
        current = self.database_manager._unit_of_work.get()
        if current is None:
            raise AssertionError("calendar check left the owning transaction")
        with self.database_manager.unit_of_work() as db:
            if db is not current:
                raise AssertionError("calendar check opened another transaction")
        return list(self.results.get(workout["date"], []))


class LibraryPlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library-plan.db",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.calendar = CalendarConflictFake(self.manager)
        self.events = []
        self.id_counter = itertools.count(1)
        self.planned_service = PlannedUnitService(
            self.manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: date.fromisoformat(TODAY),
            lambda: uuid.UUID(int=next(self.id_counter)),
            lambda value: value,
            self.calendar,
            lambda: None,
        )

        def publish_change():
            with self.manager.reader() as db:
                count = db.execute("SELECT COUNT(*) FROM planned_units").fetchone()[0]
            self.events.append(count)

        self.service = WorkoutLibraryPlanService(
            self.manager, self.planned_service, self.calendar, publish_change
        )

    def tearDown(self):
        self.manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def template(*, date_value=None, source="coach", name="Easy ride", **overrides):
        result = {
            "type": "Ride",
            "name": name,
            "description": "- 30m 60% easy",
            "duration_minutes": 30,
            "target": "AUTO",
            **overrides,
        }
        if date_value is not None:
            result["date"] = date_value
            result["source"] = source
        return result

    def add_template(self, local_id, payload):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (local_id, local_id, json.dumps(payload), NOW),
            )

    def state(self):
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT local_id, payload FROM planned_units ORDER BY local_id"
            ).fetchall()
            history = db.execute(
                "SELECT entity_type, entity_id, action, source FROM change_history "
                "WHERE entity_type='planned_unit' ORDER BY id"
            ).fetchall()
            revision = db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()[0]
        return rows, history, revision

    def test_input_bounds_and_item_validation_keep_existing_errors(self):
        cases = [
            (None, 400, "Mindestens eine Bibliothekseinheit ist erforderlich."),
            ([], 400, "Mindestens eine Bibliothekseinheit ist erforderlich."),
            ((), 400, "Mindestens eine Bibliothekseinheit ist erforderlich."),
            (
                [{}] * 15,
                400,
                "Es können höchstens 14 Bibliothekseinheiten gleichzeitig eingeplant werden.",
            ),
            ([None], 400, "Jede Planung muss ein Objekt sein."),
            (
                [{"library_workout_id": "bad", "date": TODAY}],
                400,
                INVALID_LIBRARY_ID_ERROR,
            ),
            (
                [{"library_workout_id": str(uuid.uuid4()), "date": "yesterday"}],
                400,
                INVALID_PLANNING_DATE_ERROR,
            ),
        ]
        for entries, status, message in cases:
            with self.subTest(entries=entries):
                with self.assertRaises(AppError) as raised:
                    self.service.apply(entries)
                self.assertEqual(
                    (raised.exception.status, raised.exception.message),
                    (status, message),
                )
        self.assertEqual(self.events, [])

    def test_missing_and_corrupt_templates_keep_existing_errors(self):
        missing_id = str(uuid.uuid4())
        with self.assertRaises(AppError) as raised:
            self.service.apply([{"library_workout_id": missing_id, "date": TODAY}])
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(
            raised.exception.message,
            "Bibliothekseinheit nicht gefunden. Bitte zuerst synchronisieren.",
        )

        corrupt_id = str(uuid.uuid4())
        not_object_id = str(uuid.uuid4())
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (corrupt_id, corrupt_id, "{", NOW),
            )
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (not_object_id, not_object_id, "[]", NOW),
            )
        for local_id in (corrupt_id, not_object_id):
            with self.subTest(local_id=local_id), self.assertRaises(AppError) as raised:
                self.service.apply([{"library_workout_id": local_id, "date": TODAY}])
            self.assertEqual(raised.exception.status, 500)
            self.assertEqual(raised.exception.message, CORRUPT_LIBRARY_ERROR)
        self.assertEqual(self.events, [])

    def test_duplicate_conflicts_are_complete_and_limited_to_eight_descriptions(self):
        ids = [str(uuid.uuid4()) for _ in range(10)]
        for index, local_id in enumerate(ids):
            self.add_template(local_id, self.template(name=f"Ride {index}"))
        entries = [
            {"library_workout_id": local_id, "date": "2026-09-21"} for local_id in ids
        ]

        with self.assertRaises(AppError) as raised:
            self.service.apply(entries)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(
            raised.exception.message,
            "Planung wegen bestehender Kalendereinheiten nicht möglich: "
            + ", ".join(f"2026-09-21: {name}" for name in ["Mehrere Einheiten"] * 8)
            + ". Weitere Konflikte wurden nicht aufgelistet.",
        )
        self.assertEqual(len(self.calendar.calls), 10)
        self.assertEqual(self.state(), ([], [], 0))
        self.assertEqual(self.events, [])

    def test_conflict_descriptions_distinguish_same_and_different_template(self):
        local_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        self.add_template(local_id, self.template())
        self.add_template(other_id, self.template(name="Other ride"))
        with self.assertRaises(AppError) as raised:
            self.service.apply(
                [
                    {"library_workout_id": local_id, "date": "2026-09-21"},
                    {"library_workout_id": local_id, "date": "2026-09-21"},
                    {"library_workout_id": other_id, "date": "2026-09-21"},
                ]
            )
        self.assertIn(
            "2026-09-21: Doppelte Bibliothekseinheit", raised.exception.message
        )
        self.assertIn("2026-09-21: Mehrere Einheiten", raised.exception.message)

    def test_success_creates_batch_with_history_revision_and_one_post_commit_event(
        self,
    ):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        sources = [
            self.template(
                name="Tempo ride",
                type="VirtualRide",
                description="- 45m 110%",
                duration_minutes=45,
                target="power",
            ),
            self.template(
                name="Recovery run",
                type=None,
                sport="Run",
                description="- 10m 60%",
                duration_minutes=None,
                moving_time=600,
                target=None,
            ),
        ]
        for local_id, source in zip(ids, sources):
            self.add_template(local_id, source)
        create_inputs = []
        original_create = self.planned_service.create

        def record_create(workout, db=None, **kwargs):
            if db is not self.manager._unit_of_work.get():
                raise AssertionError("create left the owning transaction")
            self.calendar.timeline.append("create")
            create_inputs.append(workout)
            return original_create(workout, db=db, **kwargs)

        with patch.object(self.planned_service, "create", side_effect=record_create):
            result = self.service.apply(
                [
                    {"library_workout_id": ids[0], "date": "2026-09-21"},
                    {"library_workout_id": ids[1], "date": "2026-09-22"},
                ]
            )

        self.assertEqual(result["status"], "local")
        self.assertEqual(result["local_planned"], 2)
        self.assertEqual(
            [item["status"] for item in result["planned"]], ["local", "local"]
        )
        self.assertEqual(
            result["planned"][0]["library_entry"]["description"], "- 45m 110%"
        )
        self.assertEqual(
            create_inputs,
            [
                {
                    "date": "2026-09-21",
                    "sport": "VirtualRide",
                    "name": "Tempo ride",
                    "description": "- 45m 110%",
                    "duration_minutes": 45,
                    "target": "power",
                    "source": "library",
                    "rationale": "Aus der lokalen Trainingsbibliothek übernommen.",
                },
                {
                    "date": "2026-09-22",
                    "sport": "Run",
                    "name": "Recovery run",
                    "description": "- 10m 60%",
                    "duration_minutes": 10,
                    "target": "AUTO",
                    "source": "library",
                    "rationale": "Aus der lokalen Trainingsbibliothek übernommen.",
                },
            ],
        )
        self.assertEqual(
            self.calendar.calls,
            [
                ({"date": "2026-09-21"}, {ids[0]}),
                ({"date": "2026-09-22"}, {ids[1]}),
            ],
        )
        self.assertEqual(
            self.calendar.timeline, ["conflict", "conflict", "create", "create"]
        )
        rows, history, revision = self.state()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(history), 2)
        self.assertEqual([row["source"] for row in history], ["local", "local"])
        self.assertEqual(revision, 2)
        self.assertEqual(self.events, [2])

    def test_already_planned_entry_is_unchanged_and_skips_calendar_check(self):
        local_id = str(uuid.uuid4())
        source = self.template(date_value=TODAY, source="library")
        self.add_template(local_id, source)

        result = self.service.apply([{"library_workout_id": local_id, "date": TODAY}])

        self.assertEqual(
            result,
            {
                "status": "local",
                "planned": [
                    {
                        "library_workout_id": local_id,
                        "date": TODAY,
                        "status": "already_planned",
                        "library_entry": source,
                    }
                ],
                "local_planned": 1,
            },
        )
        self.assertEqual(self.calendar.calls, [])
        self.assertEqual(self.state(), ([], [], 0))
        self.assertEqual(self.events, [0])

    def test_later_create_failure_rolls_back_entire_batch_and_suppresses_event(self):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        for local_id in ids:
            self.add_template(local_id, self.template())
        original_create = self.planned_service.create
        calls = itertools.count()

        def fail_second(workout, db=None, **kwargs):
            if next(calls) == 0:
                return original_create(workout, db=db, **kwargs)
            raise RuntimeError("later create failed")

        with (
            patch.object(self.planned_service, "create", side_effect=fail_second),
            self.assertRaisesRegex(RuntimeError, "later create failed"),
        ):
            self.service.apply(
                [
                    {"library_workout_id": ids[0], "date": "2026-09-21"},
                    {"library_workout_id": ids[1], "date": "2026-09-22"},
                ]
            )

        self.assertEqual(self.state(), ([], [], 0))
        self.assertEqual(self.events, [])
        self.assertEqual(len(self.calendar.calls), 2)

    def test_service_has_no_server_or_remote_provider_import_dependency(self):
        tree = ast.parse(inspect.getsource(library_plan_service))
        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        roots = set()
        for node in imports:
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif node.module:
                roots.add(node.module.split(".", 1)[0])
        self.assertNotIn("server", roots)
        self.assertNotIn("providers", roots)
        self.assertNotIn("requests", roots)
        self.assertNotIn("urllib", roots)


if __name__ == "__main__":
    unittest.main()
