"""Isolated transaction and contract tests for structured plan replacement."""

from __future__ import annotations

import ast
import json
import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from backend.db import row_factory
from backend.db.repositories import (
    KeyValueRepository,
    PlanningStateRepository,
    TrainingPlanRepository,
)
from backend.db.schema import initialize_schema
from backend.errors import STALE_PLANNING_REVISION_ERROR, AppError
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.replacement_service import (
    StructuredTrainingPlanReplacementService,
)
from backend.planning.revision import PlanningRevisionService
from backend.planning.training_plans import COACH_PLAN_CONSTRAINTS_PREFIX

TODAY = date(2030, 1, 1)
NOW = "2030-01-01T12:00:00+00:00"


class SQLiteDatabaseManager:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.unit_of_work_calls = 0

    @contextmanager
    def unit_of_work(self):
        self.unit_of_work_calls += 1
        self.connection.execute("BEGIN")
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


class CalendarConflicts:
    def __init__(self) -> None:
        self.conflicts_by_date: set[str] = set()
        self.calls: list[tuple[dict[str, str], set[str]]] = []
        self.on_call = None

    def conflicts(self, workout, ignored_calendar_ids):
        self.calls.append((workout, set(ignored_calendar_ids)))
        if self.on_call:
            self.on_call(workout)
        return ["conflict"] if workout["date"] in self.conflicts_by_date else []


class RecordingRevisionService:
    def __init__(self, delegate: PlanningRevisionService) -> None:
        self.delegate = delegate
        self.bump_calls = 0
        self.fail_after_bump = False

    def bump(self, db) -> None:
        self.bump_calls += 1
        self.delegate.bump(db)
        if self.fail_after_bump:
            raise RuntimeError("revision failure")

    def read(self, db) -> int:
        return self.delegate.read(db)


class ReplacementServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        connection = sqlite3.connect(":memory:", isolation_level=None)
        connection.row_factory = row_factory
        initialize_schema(connection)
        connection.execute(
            "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 7, ?)",
            (NOW,),
        )
        self.db = connection
        self.manager = SQLiteDatabaseManager(connection)
        self.state_repository = PlanningStateRepository()
        self.revision = RecordingRevisionService(
            PlanningRevisionService(self.state_repository, lambda: NOW)
        )
        self.plans = TrainingPlanRepository()
        self.key_values = KeyValueRepository(lambda: NOW)
        self.calendar = CalendarConflicts()
        self.unit_ids = iter(str(uuid.UUID(int=value)) for value in range(200, 300))
        self.planned_units = PlannedUnitService(
            self.manager,
            self.revision,
            lambda: NOW,
            lambda: TODAY,
            lambda: next(self.unit_ids),
            lambda value: value,
            self.calendar,
            lambda: None,
        )
        self.plan_id = str(uuid.UUID(int=100))
        self.service = self.make_service()

    def tearDown(self) -> None:
        self.db.close()

    def make_service(self, **overrides):
        dependencies = {
            "database_manager": self.manager,
            "planning_state_repository": self.state_repository,
            "revision_service": self.revision,
            "training_plan_repository": self.plans,
            "key_value_repository": self.key_values,
            "calendar_conflict_service": self.calendar,
            "planned_unit_service": self.planned_units,
            "today": lambda: TODAY,
            "now": lambda: NOW,
            "id_factory": lambda: self.plan_id,
        }
        dependencies.update(overrides)
        return StructuredTrainingPlanReplacementService(**dependencies)

    @staticmethod
    def request(revision: int = 7, *, dates: tuple[str, ...] = ("2030-01-03",)):
        return {
            "expected_revision": revision,
            "payload": {
                "plan_name": "Replacement",
                "goal": "Base" * 600,
                "workouts": [
                    {
                        "date": workout_date,
                        "sport": "Ride",
                        "name": f"New {index}",
                        "description": "- 40m 60% easy",
                        "duration_minutes": 40,
                        "target": "AUTO",
                        "rationale": "Base",
                    }
                    for index, workout_date in enumerate(dates, 1)
                ],
            },
        }

    def add_plan(self, plan_id: str, *, status: str = "planned") -> None:
        self.plans.create(
            self.db,
            plan_id,
            f"Old {plan_id}",
            "Old goal",
            "2030-01-01",
            "2030-01-10",
            status,
            NOW,
        )

    def add_unit(
        self,
        local_id: str,
        *,
        plan_id: str | None = None,
        workout_date: str = "2030-01-03",
        source: str = "coach",
        archived: bool = False,
        local_deleted: bool = False,
        external_id: str | None = None,
        payload: str | None = None,
    ) -> None:
        body = payload or json.dumps(
            {
                "id": local_id,
                "date": workout_date,
                "sport": "Ride",
                "name": local_id,
                "description": "- 30m 60% easy",
                "source": source,
                "plan_id": plan_id,
                "archived": archived,
                "local_deleted": local_deleted,
                "sync_status": "synced" if external_id else "local",
            }
        )
        self.db.execute(
            "INSERT INTO planned_units(id, local_id, external_id, payload, sync_dirty, "
            "sync_state, sync_error, sync_conflict, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, 'synced', 'old error', 'old conflict', ?, ?)",
            (local_id, local_id, external_id, body, NOW, NOW),
        )

    def set_constraints(self, plan_id: str, values: list[str]) -> None:
        self.key_values.set(
            self.db,
            COACH_PLAN_CONSTRAINTS_PREFIX + plan_id,
            json.dumps(values),
        )

    def snapshot(self):
        tables = {
            "planned_units": "SELECT local_id, external_id, payload, sync_dirty, sync_state, sync_error, sync_conflict FROM planned_units ORDER BY local_id",
            "training_plans": "SELECT id, name, goal, start_date, end_date, status, created_at, updated_at FROM training_plans ORDER BY id",
            "kv": "SELECT key, value, updated_at FROM kv ORDER BY key",
            "planning_state": "SELECT id, revision, updated_at FROM planning_state",
            "change_history": "SELECT id, entity_type, entity_id, action, source, created_at, before_hash, after_hash, diff FROM change_history ORDER BY id",
        }
        return {
            table: [tuple(row.values()) for row in self.db.execute(query).fetchall()]
            for table, query in tables.items()
        }

    def test_success_archives_records_creates_plan_units_history_and_bumps_once(self):
        plan_a, plan_z = "a-old-plan", "z-old-plan"
        self.add_plan(plan_a)
        self.add_plan(plan_z)
        self.add_unit("old-a", plan_id=plan_a)
        self.add_unit("old-z", plan_id=plan_z, workout_date="2030-01-04")
        self.add_unit(
            "tombstone",
            workout_date="2030-01-20",
            local_deleted=True,
            external_id="remote",
        )
        self.add_unit("archived-local", workout_date="2030-01-20", archived=True)
        self.set_constraints(plan_a, ["bike", "run"])
        self.set_constraints(plan_z, ["run", "swim"])

        result = self.service.replace(self.request(dates=("2030-01-05", "2030-01-06")))

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "replaced",
                "planning_revision": 8,
                "archived_count": 2,
                "created_count": 2,
                "plan_id": self.plan_id,
                "library_entry_ids": [str(uuid.UUID(int=200)), str(uuid.UUID(int=201))],
            },
        )
        self.assertEqual(self.manager.unit_of_work_calls, 1)
        self.assertEqual(self.revision.bump_calls, 1)
        self.assertEqual(
            self.calendar.calls[0][1],
            {"old-a", "old-z", "tombstone", "archived-local"},
        )
        for local_id in ("old-a", "old-z"):
            row = self.db.execute(
                "SELECT payload, sync_dirty, sync_state, sync_error, sync_conflict "
                "FROM planned_units WHERE local_id=?",
                (local_id,),
            ).fetchone()
            payload = json.loads(row["payload"])
            self.assertTrue(payload["archived"])
            self.assertTrue(payload["local_deleted"])
            self.assertEqual((row["sync_dirty"], row["sync_state"]), (1, "local"))
            self.assertIsNone(row["sync_error"])
            self.assertEqual(row["sync_conflict"], "")
        plans = {
            row["id"]: row["status"]
            for row in self.db.execute(
                "SELECT id, status FROM training_plans"
            ).fetchall()
        }
        self.assertEqual(plans[plan_a], "archived")
        self.assertEqual(plans[plan_z], "archived")
        new_plan = self.plans.get(self.db, self.plan_id)
        self.assertEqual(new_plan["name"], "Replacement")
        self.assertEqual(new_plan["goal"], "Base" * 500)
        self.assertEqual(
            (new_plan["start_date"], new_plan["end_date"]), ("2030-01-05", "2030-01-06")
        )
        self.assertEqual(new_plan["status"], "planned")
        constraints = json.loads(
            self.key_values.get(self.db, COACH_PLAN_CONSTRAINTS_PREFIX + self.plan_id)
        )
        self.assertEqual(constraints, ["bike", "run", "swim"])
        history = self.db.execute(
            "SELECT entity_type, entity_id, action, source FROM change_history"
        ).fetchall()
        self.assertEqual(len(history), 7)
        self.assertTrue(all(row["source"] == "coach_replacement" for row in history))
        self.assertEqual(
            {(row["entity_type"], row["action"]) for row in history},
            {
                ("planned_unit", "delete"),
                ("training_plan", "update"),
                ("training_plan", "create"),
                ("planned_unit", "create"),
            },
        )

    def test_explicit_constraints_override_inherited_values_and_empty_inherits(self):
        self.add_plan("old-plan")
        self.add_unit("old", plan_id="old-plan")
        self.set_constraints("old-plan", ["inherited"])

        result = self.service.replace({**self.request(), "constraints": ["explicit"]})
        self.assertEqual(result["plan_id"], self.plan_id)
        self.assertEqual(
            json.loads(
                self.key_values.get(
                    self.db, COACH_PLAN_CONSTRAINTS_PREFIX + self.plan_id
                )
            ),
            ["explicit"],
        )

        next_plan_id = str(uuid.UUID(int=101))
        inherited_service = self.make_service(id_factory=lambda: next_plan_id)
        next_request = self.request(revision=8, dates=("2030-01-07",))
        next_request["constraints"] = []
        second = inherited_service.replace(next_request)
        self.assertEqual(second["plan_id"], next_plan_id)
        self.assertEqual(
            json.loads(
                self.key_values.get(
                    self.db, COACH_PLAN_CONSTRAINTS_PREFIX + next_plan_id
                )
            ),
            ["explicit"],
        )

    def test_selected_plan_period_and_default_source_selection(self):
        self.add_plan("selected")
        self.add_plan("other")
        self.add_unit("selected-coach", plan_id="selected", workout_date="2030-01-03")
        self.add_unit(
            "selected-imported",
            plan_id="selected",
            workout_date="2030-01-04",
            source="intervals",
        )
        self.add_unit("selected-outside", plan_id="selected", workout_date="2030-01-20")
        self.add_unit("other-coach", plan_id="other", workout_date="2030-01-03")

        result = self.service.replace(
            {
                **self.request(dates=("2030-01-04",)),
                "period": {"start": "2030-01-03", "end": "2030-01-04"},
            },
            selected_plan_id="selected",
        )
        self.assertEqual(result["archived_count"], 2)
        self.assertEqual(
            self.db.execute(
                "SELECT status FROM training_plans WHERE id='selected'"
            ).fetchone()["status"],
            "planned",
        )
        self.assertFalse(
            json.loads(
                self.db.execute(
                    "SELECT payload FROM planned_units WHERE local_id='selected-outside'"
                ).fetchone()["payload"]
            )["archived"]
        )
        self.assertFalse(
            json.loads(
                self.db.execute(
                    "SELECT payload FROM planned_units WHERE local_id='other-coach'"
                ).fetchone()["payload"]
            )["archived"]
        )

        for local_id, source in (
            ("broad-coach", "coach"),
            ("broad-library", "library"),
            ("broad-imported", "intervals"),
        ):
            self.add_unit(local_id, workout_date="2030-01-10", source=source)
        broad = self.make_service(id_factory=lambda: str(uuid.UUID(int=102)))
        second = broad.replace(
            {
                **self.request(revision=8, dates=("2030-01-11",)),
                "period": {"start": "2030-01-10", "end": "2030-01-11"},
            }
        )
        self.assertEqual(second["archived_count"], 2)
        imported = json.loads(
            self.db.execute(
                "SELECT payload FROM planned_units WHERE local_id='broad-imported'"
            ).fetchone()["payload"]
        )
        self.assertFalse(imported["archived"])

    def test_calendar_conflict_is_checked_before_plan_or_unit_writes(self):
        self.add_plan("old-plan")
        self.add_unit("old", plan_id="old-plan")
        before = self.snapshot()
        self.calendar.conflicts_by_date.add("2030-01-04")
        observed_states = []

        def inspect_before_write(_workout):
            old_payload = self.db.execute(
                "SELECT payload FROM planned_units WHERE local_id='old'"
            ).fetchone()["payload"]
            observed_states.append(
                (
                    json.loads(old_payload)["archived"],
                    self.db.execute(
                        "SELECT COUNT(*) AS count FROM training_plans WHERE id=?",
                        (self.plan_id,),
                    ).fetchone()["count"],
                )
            )

        self.calendar.on_call = inspect_before_write

        with self.assertRaises(AppError) as caught:
            self.service.replace(self.request(dates=("2030-01-03", "2030-01-04")))

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "plan_date_conflict")
        self.assertEqual(len(self.calendar.calls), 2)
        self.assertEqual(observed_states, [(False, 0), (False, 0)])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.revision.bump_calls, 0)
        self.assertEqual(self.manager.unit_of_work_calls, 1)

    def test_stale_revision_is_rejected_without_writes(self):
        self.add_plan("old-plan")
        self.add_unit("old", plan_id="old-plan")
        before = self.snapshot()

        with self.assertRaises(AppError) as caught:
            self.service.replace(self.request(revision=6))

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.message, STALE_PLANNING_REVISION_ERROR)
        self.assertEqual(caught.exception.reason, "planning_revision_conflict")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.revision.bump_calls, 0)

    def test_corrupt_existing_payload_returns_invalid_plan(self):
        self.add_plan("old-plan")
        self.add_unit("old", plan_id="old-plan")
        original_execute = self.db.execute

        class CorruptRowDatabase:
            def execute(inner_self, sql, params=()):
                if sql.startswith("SELECT local_id, payload FROM planned_units"):
                    return CorruptRows([{"local_id": "broken", "payload": "[]"}])
                return original_execute(sql, params)

        class CorruptRows:
            def __init__(inner_self, rows):
                inner_self.rows = rows

            def fetchall(inner_self):
                return inner_self.rows

        manager = self.manager

        class CorruptingDatabaseManager:
            @contextmanager
            def unit_of_work(inner_self):
                manager.unit_of_work_calls += 1
                manager.connection.execute("BEGIN")
                try:
                    yield CorruptRowDatabase()
                    manager.connection.commit()
                except Exception:
                    manager.connection.rollback()
                    raise

        corrupt_manager = CorruptingDatabaseManager()
        corrupt_service = self.make_service(database_manager=corrupt_manager)

        with self.assertRaises(AppError) as caught:
            corrupt_service.replace(self.request())

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "invalid_plan")

    def test_late_create_revision_and_key_value_failures_roll_back_all_tables(self):
        failure_scenarios = ("create", "revision", "key_value")
        for scenario in failure_scenarios:
            with self.subTest(scenario=scenario):
                self.db.execute("DELETE FROM planned_units")
                self.db.execute("DELETE FROM training_plans")
                self.db.execute("DELETE FROM kv")
                self.db.execute("DELETE FROM change_history")
                self.db.execute("UPDATE planning_state SET revision=7 WHERE id=1")
                self.revision.bump_calls = 0
                self.revision.fail_after_bump = False
                self.add_plan("old-plan")
                self.add_unit("old", plan_id="old-plan")
                self.set_constraints("old-plan", ["old constraint"])
                before = self.snapshot()

                service = self.service
                if scenario == "create":

                    class FailSecondCreate:
                        def __init__(inner_self, wrapped):
                            inner_self.wrapped = wrapped
                            inner_self.calls = 0

                        def create(inner_self, *args, **kwargs):
                            inner_self.calls += 1
                            result = inner_self.wrapped.create(*args, **kwargs)
                            if inner_self.calls == 2:
                                raise RuntimeError("planned unit failure")
                            return result

                    service = self.make_service(
                        planned_unit_service=FailSecondCreate(self.planned_units)
                    )
                elif scenario == "revision":
                    self.revision.fail_after_bump = True
                else:

                    class FailKeyValueSet:
                        def __init__(inner_self, wrapped):
                            inner_self.wrapped = wrapped

                        def get(inner_self, db, key):
                            return inner_self.wrapped.get(db, key)

                        def set(inner_self, db, key, value):
                            inner_self.wrapped.set(db, key, value)
                            raise RuntimeError("key-value failure")

                    service = self.make_service(
                        key_value_repository=FailKeyValueSet(self.key_values)
                    )

                request = self.request(dates=("2030-01-03", "2030-01-04"))
                if scenario == "key_value":
                    request["constraints"] = ["explicit"]
                with self.assertRaises(RuntimeError):
                    service.replace(request)
                self.assertEqual(self.snapshot(), before)

    def test_service_has_no_server_provider_or_event_imports(self):
        source_path = (
            Path(__file__).parents[1]
            / "backend"
            / "planning"
            / "replacement_service.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        modules = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [None])
        }
        self.assertFalse(
            any(
                module
                and (
                    module == "server"
                    or module.startswith("server.")
                    or ".providers" in module
                    or "event" in module.casefold()
                )
                for module in modules
            ),
            modules,
        )


if __name__ == "__main__":
    unittest.main()
