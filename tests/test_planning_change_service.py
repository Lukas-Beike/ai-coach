"""Tests for complete structured planning change orchestration."""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.db.repositories import (
    PlanningStateRepository,
    TrainingPlanRepository,
)
from backend.errors import AppError
from backend.planning import changes


def _dict_row(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


class _DatabaseManager:
    def __init__(self, db: sqlite3.Connection, trace: list[str]) -> None:
        self.db = db
        self.trace = trace
        self.calls = 0

    @contextmanager
    def unit_of_work(self):
        self.calls += 1
        self.trace.append("begin")
        try:
            yield self.db
            self.db.commit()
            self.trace.append("commit")
        except Exception:
            self.db.rollback()
            self.trace.append("rollback")
            raise


class _CalendarConflictService:
    def conflicts(
        self, workout: dict[str, Any], exclude_library_ids: set[str]
    ) -> list[dict[str, Any]]:
        return []


class _TrackingValidator:
    def __init__(self, validator: Any, trace: list[str]) -> None:
        self.validator = validator
        self.trace = trace

    def validate(self, changes, arguments, db, require_revision):
        self.trace.append("validate")
        return self.validator.validate(changes, arguments, db, require_revision)


class _TrackingResolver:
    def __init__(self, resolver: Any, trace: list[str]) -> None:
        self.resolver = resolver
        self.trace = trace

    def derive(self, changes, authorized_plan_id, db):
        self.trace.append("derive")
        return self.resolver.derive(changes, authorized_plan_id, db)


class _PlannedUnitService:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.create_calls: list[dict[str, Any]] = []
        self.update_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.fail_on_update: int | None = None

    def create(self, workout, *, db, bump_planning_revision):
        self.trace.append("create")
        self.create_calls.append(
            {"workout": dict(workout), "bump_planning_revision": bump_planning_revision}
        )
        local_id = f"created-{len(self.create_calls)}"
        entry = {**workout, "id": local_id, "local_id": local_id}
        db.execute(
            "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
            (local_id, json.dumps(entry)),
        )
        return entry

    def update(
        self,
        local_id,
        values,
        *,
        skip_calendar_conflict,
        bump_planning_revision,
        db,
    ):
        self.trace.append("update")
        self.update_calls.append(
            (
                local_id,
                dict(values),
                {
                    "skip_calendar_conflict": skip_calendar_conflict,
                    "bump_planning_revision": bump_planning_revision,
                },
            )
        )
        row = db.execute(
            "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
        ).fetchone()
        current = json.loads(row["payload"])
        action = str(values.get("action") or "update").strip().casefold()
        updated = {**current, **values}
        if action == "archive":
            updated["archived"] = True
        elif action == "restore":
            updated["archived"] = False
            updated["local_deleted"] = False
        elif action == "delete":
            updated["local_deleted"] = True
        db.execute(
            "UPDATE planned_units SET payload=? WHERE local_id=?",
            (json.dumps(updated), local_id),
        )
        if self.fail_on_update == len(self.update_calls):
            raise RuntimeError("planned unit update failed")
        return {"local_id": local_id, "status": "local", "library_entry": updated}


class _RevisionService:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.bump_calls = 0
        self.fail_bump = False

    def bump(self, db) -> None:
        self.trace.append("bump")
        self.bump_calls += 1
        db.execute("UPDATE planning_state SET revision=revision+1 WHERE id=1")
        if self.fail_bump:
            raise RuntimeError("revision update failed")

    def read(self, db) -> int:
        self.trace.append("read")
        if hasattr(self, "read_override"):
            return self.read_override
        return int(
            db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()[
                "revision"
            ]
        )


class _TrainingPlanService:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.bounds_calls: list[set[str]] = []
        self.fail_bounds = False

    def update_bounds(self, db, plan_ids) -> None:
        self.trace.append("bounds")
        normalized = set(plan_ids)
        self.bounds_calls.append(normalized)
        for plan_id in normalized:
            db.execute(
                "INSERT OR REPLACE INTO plan_bounds(plan_id) VALUES (?)", (plan_id,)
            )
        if self.fail_bounds:
            raise RuntimeError("plan bounds update failed")


class StructuredTrainingChangeServiceTests(unittest.TestCase):
    today = date(2031, 6, 1)

    def setUp(self) -> None:
        self.trace: list[str] = []
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = _dict_row
        self.db.executescript(
            """
            CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER);
            INSERT INTO planning_state(id, revision) VALUES (1, 7);
            CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE training_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                goal TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE plan_bounds (plan_id TEXT PRIMARY KEY);
            """
        )
        self.db.commit()
        self.database_manager = _DatabaseManager(self.db, self.trace)
        self.planned_units = _PlannedUnitService(self.trace)
        self.revisions = _RevisionService(self.trace)
        self.plans = _TrainingPlanService(self.trace)
        plan_repository = TrainingPlanRepository()
        plan_repository.create(
            self.db,
            "plan-a",
            "Spring plan",
            "Build",
            "2031-06-01",
            "2031-06-30",
            "planned",
            "2031-06-01T00:00:00Z",
        )
        self.db.commit()
        validator = changes.StructuredTrainingChangeValidator(
            PlanningStateRepository(), _CalendarConflictService()
        )
        resolver = changes.StructuredTrainingPlanResolver(plan_repository)
        self.validator = _TrackingValidator(validator, self.trace)
        self.resolver = _TrackingResolver(resolver, self.trace)
        self.published = 0
        self.service = self._make_service()

    def tearDown(self) -> None:
        self.db.close()

    def _make_service(self, *, max_changes: int = 10):
        def publish_change() -> None:
            self.trace.append("publish")
            self.published += 1

        return changes.StructuredTrainingChangeService(
            self.database_manager,
            self.validator,
            self.resolver,
            self.planned_units,
            self.revisions,
            self.plans,
            lambda: self.today,
            max_changes,
            publish_change,
        )

    def _add_unit(self, local_id: str, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, separators=(",", ":"))
        self.db.execute(
            "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
            (local_id, serialized),
        )
        self.db.commit()
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _create(self, *, plan_id: str | None = None) -> dict[str, Any]:
        change = {
            "action": "create",
            "date": "2031-06-13",
            "sport": "Run",
            "name": "Easy run",
            "description": "- 30m 60% easy",
            "duration_minutes": 30,
            "target": "POWER",
            "rationale": "Recovery",
            "id": "attacker-controlled-id",
            "plan_name": "attacker-controlled-name",
        }
        if plan_id is not None:
            change["plan_id"] = plan_id
        return change

    def _unit(self, local_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
        ).fetchone()
        return json.loads(row["payload"])

    def test_mixed_batch_derives_plan_preserves_order_and_projects_deduplicated_result(
        self,
    ) -> None:
        payload_hash = self._add_unit(
            "unit-a",
            {
                "id": "unit-a",
                "date": "2031-06-10",
                "name": "Before",
                "plan_id": "plan-a",
                "archived": False,
                "local_deleted": False,
            },
        )
        arguments = {
            "expected_revision": 7,
            "changes": [
                {
                    "action": "update",
                    "local_id": "unit-a",
                    "date": "2031-06-12",
                    "expected_payload_hash": payload_hash,
                },
                {
                    "action": "archive",
                    "local_id": "unit-a",
                    "expected_payload_hash": payload_hash,
                },
                {
                    "action": "restore",
                    "local_id": "unit-a",
                    "expected_payload_hash": payload_hash,
                },
                {
                    "action": "delete",
                    "local_id": "unit-a",
                    "expected_payload_hash": payload_hash,
                },
                self._create(),
            ],
        }

        original_prepare = changes.prepare_structured_training_changes

        def tracked_prepare(*args, **kwargs):
            self.trace.append("prepare")
            return original_prepare(*args, **kwargs)

        with patch.object(
            changes, "prepare_structured_training_changes", side_effect=tracked_prepare
        ):
            result = self.service.apply(arguments, require_revision=True)

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "applied",
                "planning_revision": 8,
                "changes": [
                    {"local_id": "unit-a", "status": "local"},
                    {"local_id": "unit-a", "status": "local"},
                    {"local_id": "unit-a", "status": "local"},
                    {"local_id": "unit-a", "status": "local"},
                    {"local_id": "created-1", "status": "local"},
                ],
                "library_entry_ids": ["unit-a", "created-1"],
            },
        )
        self.assertEqual(
            [call[1]["action"] for call in self.planned_units.update_calls],
            ["update", "archive", "restore", "delete"],
        )
        self.assertTrue(
            all(
                call[2]
                == {
                    "skip_calendar_conflict": True,
                    "bump_planning_revision": False,
                }
                for call in self.planned_units.update_calls
            )
        )
        created = self.planned_units.create_calls[0]
        self.assertEqual(created["bump_planning_revision"], False)
        self.assertEqual(created["workout"]["source"], "coach")
        self.assertEqual(created["workout"]["plan_id"], "plan-a")
        self.assertEqual(created["workout"]["plan_name"], "Spring plan")
        self.assertNotIn("id", created["workout"])
        self.assertNotIn("local_id", created["workout"])
        self.assertEqual(self.plans.bounds_calls, [{"plan-a"}])
        self.assertEqual(self.revisions.bump_calls, 1)
        self.assertEqual(self.published, 1)
        self.assertTrue(self._unit("unit-a")["local_deleted"])
        self.assertEqual(
            self.trace,
            [
                "begin",
                "prepare",
                "validate",
                "derive",
                "update",
                "update",
                "update",
                "update",
                "create",
                "bump",
                "bounds",
                "read",
                "commit",
                "publish",
            ],
        )

    def test_create_with_blank_plan_id_remains_standalone(self) -> None:
        self._add_unit(
            "unit-a",
            {
                "date": "2031-06-10",
                "plan_id": "plan-a",
                "archived": False,
                "local_deleted": False,
            },
        )
        self.service.apply(
            {
                "changes": [
                    {"action": "update", "local_id": "unit-a", "date": "2031-06-12"},
                    self._create(plan_id="   "),
                ]
            }
        )
        created = self.planned_units.create_calls[0]["workout"]
        self.assertNotIn("plan_id", created)
        self.assertNotIn("plan_name", created)
        self.assertEqual(self.plans.bounds_calls, [{"plan-a"}])

    def test_apply_in_db_uses_only_the_callers_transaction_and_publishes_nothing(
        self,
    ) -> None:
        self._add_unit(
            "standalone",
            {"date": "2031-06-10", "archived": False, "local_deleted": False},
        )

        with self.database_manager.unit_of_work() as db:
            result = self.service.apply_in_db(
                db, {"changes": [{"action": "delete", "local_id": "standalone"}]}
            )
            self.assertEqual(result["planning_revision"], 8)
            self.assertEqual(self.trace.count("begin"), 1)
            self.assertNotIn("commit", self.trace)
            self.assertEqual(self.published, 0)

        self.assertEqual(self.database_manager.calls, 1)
        self.assertEqual(self.trace[-1], "commit")
        self.assertEqual(self.published, 0)

    def test_required_revision_and_payload_hash_are_delegated_before_any_write(
        self,
    ) -> None:
        self._add_unit(
            "unit-a",
            {
                "date": "2031-06-10",
                "archived": False,
                "local_deleted": False,
            },
        )
        with self.assertRaises(AppError) as raised:
            self.service.apply(
                {
                    "expected_revision": 7,
                    "changes": [{"action": "update", "local_id": "unit-a"}],
                },
                require_revision=True,
            )
        self.assertEqual(raised.exception.reason, "payload_hash_required")
        self.assertEqual(self.planned_units.update_calls, [])
        self.assertEqual(self.revisions.bump_calls, 0)
        self.assertEqual(
            self.db.execute("SELECT revision FROM planning_state").fetchone()[
                "revision"
            ],
            7,
        )
        self.assertEqual(self.published, 0)
        self.assertEqual(self.trace[-1], "rollback")

    def test_preparation_validation_and_derivation_errors_write_nothing(self) -> None:
        invalid_create = {"action": "create", "date": "2031-06-13"}
        with self.subTest(phase="prepare"), self.assertRaises(AppError):
            self.service.apply({"changes": [invalid_create]})
        self.assertEqual(self.trace[-1], "rollback")
        self.assertNotIn("validate", self.trace)

        self.trace.clear()
        with self.subTest(phase="validate"), self.assertRaises(AppError):
            self.service.apply(
                {"changes": [{"action": "update", "local_id": "missing"}]},
                require_revision=True,
            )
        self.assertNotIn("derive", self.trace)
        self.assertNotIn("update", self.trace)

        self.trace.clear()
        with self.subTest(phase="derive"), self.assertRaises(AppError):
            self.service.apply(
                {"changes": [{"action": "update", "local_id": "unit-a"}]},
                authorized_plan_id="missing-plan",
            )
        self.assertIn("validate", self.trace)
        self.assertIn("derive", self.trace)
        self.assertNotIn("update", self.trace)
        self.assertNotIn("bump", self.trace)
        self.assertEqual(
            self.db.execute("SELECT revision FROM planning_state").fetchone()[
                "revision"
            ],
            7,
        )
        self.assertEqual(self.planned_units.create_calls, [])
        self.assertEqual(self.planned_units.update_calls, [])
        self.assertEqual(self.published, 0)

        self.trace.clear()
        injected_identity = {**self._create(), "local_id": "injected-id"}
        with self.subTest(phase="prepare-local-id"), self.assertRaises(AppError):
            self.service.apply({"changes": [injected_identity]})
        self.assertNotIn("validate", self.trace)
        self.assertEqual(self.planned_units.create_calls, [])
        self.assertEqual(self.published, 0)

        self.trace.clear()
        limited_service = self._make_service(max_changes=1)
        with self.subTest(phase="change-limit"), self.assertRaises(AppError):
            limited_service.apply(
                {
                    "changes": [
                        {"action": "update", "local_id": "unit-a"},
                        {"action": "archive", "local_id": "unit-b"},
                    ]
                }
            )
        self.assertNotIn("validate", self.trace)
        self.assertEqual(self.planned_units.update_calls, [])
        self.assertEqual(self.published, 0)

    def test_current_revision_is_used_when_revision_read_returns_zero(self) -> None:
        self._add_unit(
            "standalone",
            {"date": "2031-06-10", "archived": False, "local_deleted": False},
        )
        self.revisions.read_override = 0

        result = self.service.apply(
            {"expected_revision": 7, "changes": [{"local_id": "standalone"}]}
        )

        self.assertEqual(result["planning_revision"], 7)
        self.assertEqual(self.published, 1)

    def test_later_row_revision_and_bounds_failures_roll_back_entire_batch(
        self,
    ) -> None:
        for failure in ("row", "revision", "bounds"):
            with self.subTest(failure=failure):
                self.db.execute("DELETE FROM planned_units")
                self.db.execute("DELETE FROM plan_bounds")
                self.db.execute("UPDATE planning_state SET revision=7 WHERE id=1")
                self.db.execute(
                    "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
                    ("unit-a", json.dumps({"date": "2031-06-10", "plan_id": "plan-a"})),
                )
                self.db.execute(
                    "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
                    ("unit-b", json.dumps({"date": "2031-06-11", "plan_id": "plan-a"})),
                )
                self.db.commit()
                before = [
                    (row["local_id"], row["payload"])
                    for row in self.db.execute(
                        "SELECT local_id, payload FROM planned_units ORDER BY local_id"
                    ).fetchall()
                ]
                self.trace.clear()
                self.planned_units.update_calls.clear()
                self.planned_units.fail_on_update = 2 if failure == "row" else None
                self.revisions.fail_bump = failure == "revision"
                self.plans.fail_bounds = failure == "bounds"

                arguments = {
                    "changes": [
                        {"action": "update", "local_id": "unit-a", "name": "first"},
                        {"action": "archive", "local_id": "unit-b"},
                    ]
                }
                with self.assertRaises(RuntimeError):
                    self.service.apply(arguments)

                after = [
                    (row["local_id"], row["payload"])
                    for row in self.db.execute(
                        "SELECT local_id, payload FROM planned_units ORDER BY local_id"
                    ).fetchall()
                ]
                self.assertEqual(after, before)
                self.assertEqual(
                    self.db.execute(
                        "SELECT revision FROM planning_state WHERE id=1"
                    ).fetchone()["revision"],
                    7,
                )
                self.assertEqual(
                    self.db.execute("SELECT COUNT(*) AS n FROM plan_bounds").fetchone()[
                        "n"
                    ],
                    0,
                )
                self.assertEqual(self.trace[-1], "rollback")
                self.assertNotIn("publish", self.trace)
                self.planned_units.fail_on_update = None
                self.revisions.fail_bump = False
                self.plans.fail_bounds = False

    def test_public_api_has_no_server_dependency_or_callback_apply_functions(
        self,
    ) -> None:
        source_path = Path(changes.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports_server = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name == "server" for alias in node.names)
            )
            or (isinstance(node, ast.ImportFrom) and node.module == "server")
            for node in ast.walk(tree)
        )
        self.assertFalse(imports_server)
        self.assertTrue(hasattr(changes, "StructuredTrainingChangeValidator"))
        self.assertTrue(hasattr(changes, "StructuredTrainingPlanResolver"))
        self.assertTrue(hasattr(changes, "StructuredTrainingChangeService"))
        self.assertFalse(hasattr(changes, "PlanningChangeDependencies"))
        self.assertFalse(hasattr(changes, "apply_structured_changes"))
        self.assertFalse(hasattr(changes, "apply_structured_changes_in_db"))
        function_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertNotIn("apply_structured_changes", function_names)
        self.assertNotIn("apply_structured_changes_in_db", function_names)


if __name__ == "__main__":
    unittest.main()
