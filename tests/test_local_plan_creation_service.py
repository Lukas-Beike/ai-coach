"""Focused tests for local plan creation orchestration."""

from __future__ import annotations

import ast
import inspect
import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from backend.db import row_factory
from backend.db.repositories import PlanningStateRepository, TrainingPlanRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.local_plan_creation_service import (
    LocalTrainingPlanCreationService,
)
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService

NOW = "2026-09-20T09:00:00+00:00"
TODAY = date(2026, 9, 20)
PLAN_ID = "00000000-0000-0000-0000-000000000001"
TEMPLATE_ID = "00000000-0000-0000-0000-000000000002"


class SQLiteUnitOfWork:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.calls = 0

    @contextmanager
    def unit_of_work(self):
        self.calls += 1
        self.db.execute("BEGIN")
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class RevisionSpy:
    def __init__(self) -> None:
        self.service = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        self.calls = 0

    def bump(self, db: sqlite3.Connection) -> None:
        self.calls += 1
        self.service.bump(db)


class LocalPlanCreationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        initialize_schema(self.db)
        self.db.execute(
            "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
            (NOW,),
        )
        self.db.commit()
        self.database_manager = SQLiteUnitOfWork(self.db)
        self.revisions = RevisionSpy()
        self.calendar_conflicts = Mock()
        self.calendar_conflicts.conflicts.return_value = []
        self.library_service = WorkoutLibraryService(
            self.database_manager, lambda: NOW, lambda: TEMPLATE_ID, Mock()
        )
        self.planned_unit_service = PlannedUnitService(
            self.database_manager,
            self.revisions,
            lambda: NOW,
            lambda: TODAY,
            self._next_unit_id,
            lambda text: text,
            self.calendar_conflicts,
            Mock(),
        )
        self.service = LocalTrainingPlanCreationService(
            self.database_manager,
            TrainingPlanRepository(),
            self.planned_unit_service,
            self.library_service,
            self.calendar_conflicts,
            self.revisions,
            lambda: TODAY,
            lambda: NOW,
            lambda: PLAN_ID,
            Mock(),
        )
        self._unit_number = 10

    def tearDown(self) -> None:
        self.db.close()

    def _next_unit_id(self) -> str:
        value = f"00000000-0000-0000-0000-{self._unit_number:012d}"
        self._unit_number += 1
        return value

    @staticmethod
    def workout(
        workout_date: str = "2026-09-22",
        *,
        name: str = "Easy ride",
        description: str = "- 30m Z2",
        duration: int | str = 30,
        sport: str = "Ride",
        target: str = "POWER",
    ) -> dict[str, object]:
        return {
            "date": workout_date,
            "sport": sport,
            "name": name,
            "description": description,
            "duration_minutes": duration,
            "target": target,
            "rationale": "Build steadily",
        }

    def test_empty_input_keeps_existing_validation_contract(self) -> None:
        for workouts in ([], None, {}):
            with self.subTest(workouts=workouts):
                with self.assertRaises(AppError) as raised:
                    self.service.save(workouts)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(
                    raised.exception.message,
                    "Mindestens eine Einheit ist erforderlich.",
                )
        self.assertEqual(self.database_manager.calls, 0)

    def test_save_normalizes_workout_and_projects_timestamps(self) -> None:
        created = self.service.save(
            [
                {
                    **self.workout(sport="cycling", duration="30", target="bad"),
                    "description": "- 30m Zone 2",
                }
            ]
        )

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["sport"], "Ride")
        self.assertEqual(created[0]["duration_minutes"], 30)
        self.assertEqual(created[0]["moving_time"], 1800)
        self.assertEqual(created[0]["target"], "AUTO")
        self.assertEqual(created[0]["description"], "- 30m Z2")
        self.assertEqual(created[0]["source"], "coach")
        self.assertEqual(created[0]["created_at"], NOW)
        self.assertEqual(created[0]["updated_at"], NOW)

    def test_validate_calendar_rejects_duplicate_date_with_exact_contract(self) -> None:
        same_date = self.workout()

        with self.assertRaises(AppError) as raised:
            self.service.validate_calendar([same_date, same_date])

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "plan_date_conflict")
        self.assertEqual(
            raised.exception.message,
            "Der Plan enthält mehrere Einheiten für den 2026-09-22; pro Tag ist eine Einheit möglich.",
        )
        self.calendar_conflicts.conflicts.assert_called_once_with(
            {"date": "2026-09-22"}
        )

    def test_validate_calendar_rejects_existing_conflict_with_exact_contract(
        self,
    ) -> None:
        self.calendar_conflicts.conflicts.return_value = [{"source": "local_library"}]

        with self.assertRaises(AppError) as raised:
            self.service.validate_calendar([self.workout()])

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "plan_date_conflict")
        self.assertEqual(
            raised.exception.message,
            "Für den 2026-09-22 existiert bereits eine lokale Kalendereinheit. Berücksichtige diesen Termin und plane zusätzliche Einheiten an freien Tagen.",
        )

    def test_matching_template_is_reused_with_library_mapping(self) -> None:
        self.db.execute(
            "INSERT INTO workout_library(id, local_id, payload, updated_at) VALUES (?, ?, ?, ?)",
            (
                TEMPLATE_ID,
                TEMPLATE_ID,
                json.dumps(
                    {
                        "id": TEMPLATE_ID,
                        "type": "Ride",
                        "name": "Easy ride",
                        "description": "- 35m Z2 HR",
                        "duration_minutes": 35,
                        "moving_time": 2100,
                        "target": "HR",
                    }
                ),
                NOW,
            ),
        )
        self.db.commit()

        created = self.service.save(
            [self.workout(description="- 35m Z2 HR", duration=35, target="HR")]
        )

        self.assertEqual(created[0]["source"], "library")
        self.assertEqual(created[0]["name"], "Easy ride")
        self.assertEqual(created[0]["duration_minutes"], 35)
        self.assertEqual(created[0]["target"], "HR")
        self.assertTrue(self.service._logger.info.called)

    def test_no_template_match_keeps_coach_payload(self) -> None:
        created = self.service.save(
            [self.workout(name="Different workout", description="- 30m Z1")]
        )

        self.assertEqual(created[0]["source"], "coach")
        self.assertEqual(created[0]["name"], "Different workout")
        self.assertEqual(created[0]["target"], "POWER")
        self.assertNotIn("plan_id", created[0])

    def test_plan_metadata_history_bounds_and_single_revision_bump(self) -> None:
        created = self.service.save(
            [
                self.workout("2026-09-25"),
                self.workout("2026-09-22", name="Second", description="- 30m Z1"),
            ],
            f"  {'P' * 205}  ",
            f" {'G' * 2005} ",
        )

        plan = self.db.execute(
            "SELECT * FROM training_plans WHERE id=?", (PLAN_ID,)
        ).fetchone()
        self.assertEqual(plan["name"], "P" * 200)
        self.assertEqual(plan["goal"], "G" * 2000)
        self.assertEqual(plan["start_date"], "2026-09-22")
        self.assertEqual(plan["end_date"], "2026-09-25")
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["created_at"], NOW)
        self.assertEqual(plan["updated_at"], NOW)
        history = self.db.execute(
            "SELECT entity_type, entity_id, action, diff FROM change_history "
            "WHERE entity_type='training_plan'"
        ).fetchone()
        self.assertEqual(history["entity_id"], PLAN_ID)
        self.assertEqual(history["action"], "create")
        self.assertEqual(
            json.loads(history["diff"])["fields"]["name"]["after"], "P" * 200
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(self.revisions.calls, 1)
        self.assertEqual(self.revisions.service.read(self.db), 1)

    def test_caller_owned_connection_is_not_committed_or_wrapped(self) -> None:
        self.db.execute("BEGIN")
        calls_before = self.database_manager.calls

        created = self.service.save([self.workout()], db=self.db)

        self.assertEqual(len(created), 1)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.database_manager.calls, calls_before)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) AS count FROM planned_units").fetchone()[
                "count"
            ],
            1,
        )
        self.db.rollback()
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) AS count FROM planned_units").fetchone()[
                "count"
            ],
            0,
        )

    def test_owned_transaction_rolls_back_every_write_after_mid_plan_failure(
        self,
    ) -> None:
        real_service = self.planned_unit_service

        class FailingAfterFirstCreate:
            def __init__(self) -> None:
                self.calls = 0

            def create(self, workout, db=None, *, bump_planning_revision=True):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("synthetic planned-unit failure")
                return real_service.create(
                    workout,
                    db=db,
                    bump_planning_revision=bump_planning_revision,
                )

        self.service._planned_unit_service = FailingAfterFirstCreate()

        with self.assertRaisesRegex(RuntimeError, "synthetic planned-unit failure"):
            self.service.save(
                [self.workout(), self.workout("2026-09-23", name="Second")],
                plan_name="Rollback plan",
            )

        for table in ("training_plans", "planned_units", "change_history"):
            with self.subTest(table=table):
                count = self.db.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                self.assertEqual(count, 0)
        self.assertEqual(self.revisions.service.read(self.db), 0)

    def test_ast_forbids_server_imports_and_callback_bundles(self) -> None:
        source = Path(inspect.getfile(LocalTrainingPlanCreationService))
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name == "server" for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "server")

        service_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "LocalTrainingPlanCreationService"
        )
        initializer = next(
            node
            for node in service_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        self.assertEqual(
            [argument.arg for argument in initializer.args.args],
            [
                "self",
                "database_manager",
                "training_plan_repository",
                "planned_unit_service",
                "workout_library_service",
                "calendar_conflict_service",
                "planning_revision_service",
                "today",
                "now",
                "id_factory",
                "logger",
            ],
        )
        self.assertFalse(
            {argument.arg for argument in initializer.args.args}
            & {"callbacks", "dependencies", "service_bundle"}
        )


if __name__ == "__main__":
    unittest.main()
