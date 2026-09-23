"""Tests for transaction-scoped structured training plan resolution."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.db.repositories import TrainingPlanRepository
from backend.errors import AppError
from backend.planning.changes import StructuredTrainingPlanResolver


class TrackingTrainingPlanRepository(TrainingPlanRepository):
    def __init__(self) -> None:
        self.lookups: list[str] = []

    def get(self, db: Any, plan_id: str) -> dict[str, Any] | None:
        self.lookups.append(plan_id)
        return super().get(db, plan_id)


def _dict_row(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {column[0]: value for column, value in zip(cursor.description, row)}


class StructuredTrainingPlanResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "planning.sqlite3"
        self.db = sqlite3.connect(database_path)
        self.db.row_factory = _dict_row
        self.db.execute(
            "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT)"
        )
        self.db.execute(
            """CREATE TABLE training_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                goal TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.repository = TrackingTrainingPlanRepository()
        self.resolver = StructuredTrainingPlanResolver(self.repository)

    def tearDown(self) -> None:
        self.db.close()
        self.temporary_directory.cleanup()

    def add_plan(
        self, plan_id: str, *, name: str = "Plan", status: str = "planned"
    ) -> None:
        self.repository.create(
            self.db,
            plan_id,
            name,
            "Build",
            "2031-01-01",
            "2031-01-31",
            status,
            "2031-01-01T00:00:00Z",
        )

    def add_unit(self, local_id: str, payload: str | dict[str, Any]) -> None:
        serialized = payload if isinstance(payload, str) else json.dumps(payload)
        self.db.execute(
            "INSERT INTO planned_units(local_id, payload) VALUES (?, ?)",
            (local_id, serialized),
        )

    def derive(
        self,
        changes: list[dict[str, Any]],
        authorized_plan_id: str | None = None,
    ) -> tuple[dict[str, str], set[str]]:
        return self.resolver.derive(changes, authorized_plan_id, self.db)

    def assert_app_error(
        self,
        call,
        *,
        status: int,
        message: str,
        reason: str,
    ) -> None:
        with self.assertRaises(AppError) as raised:
            call()
        self.assertEqual(raised.exception.status, status)
        self.assertEqual(raised.exception.message, message)
        self.assertEqual(raised.exception.reason, reason)

    def test_missing_and_unreadable_or_non_dict_payloads_have_no_membership(
        self,
    ) -> None:
        self.add_unit("broken", "{")
        self.add_unit("array", ["not", "a", "mapping"])
        self.add_unit("null", "null")

        result = self.derive(
            [
                {"action": "update", "local_id": "missing"},
                {"action": "update", "local_id": "broken"},
                {"action": "update", "local_id": "array"},
                {"action": "update", "local_id": "null"},
            ]
        )

        self.assertEqual(result, ({}, set()))
        self.assertEqual(self.repository.lookups, [])

    def test_empty_and_standalone_memberships_do_not_derive_a_plan(self) -> None:
        self.add_unit("empty", {"plan_id": "   ", "date": "2031-02-10"})
        self.add_unit("standalone", {"date": "2031-02-11"})

        result = self.derive(
            [
                {"action": "update", "local_id": "empty"},
                {"action": "update", "local_id": "standalone"},
            ]
        )

        self.assertEqual(result, ({}, set()))
        self.assertEqual(self.repository.lookups, [])

    def test_one_active_membership_derives_plan_and_truncates_name(self) -> None:
        long_name = "P" * 250
        self.add_plan("plan-a", name=long_name)
        self.add_unit("unit-a", {"plan_id": "  plan-a  ", "date": "2031-02-10"})

        result = self.derive([{"action": "update", "local_id": " unit-a "}])

        self.assertEqual(result, ({"plan_id": "plan-a", "plan_name": "P" * 200}, set()))
        self.assertEqual(self.repository.lookups, ["plan-a"])

    def test_multiple_memberships_are_ambiguous_and_archived_or_missing_plans_are_ignored(
        self,
    ) -> None:
        self.add_plan("plan-a")
        self.add_plan("plan-b")
        self.add_plan("archived", status="archived")
        self.add_unit("unit-a", {"plan_id": "plan-a"})
        self.add_unit("unit-b", {"plan_id": "plan-b"})
        self.add_unit("unit-archived", {"plan_id": "archived"})
        self.add_unit("unit-missing", {"plan_id": "no-plan-row"})

        self.assertEqual(
            self.derive(
                [
                    {"local_id": "unit-a"},
                    {"local_id": "unit-b"},
                ]
            ),
            ({}, set()),
        )
        self.assertEqual(self.derive([{"local_id": "unit-archived"}]), ({}, set()))
        self.assertEqual(self.derive([{"local_id": "unit-missing"}]), ({}, set()))

    def test_bounds_change_only_for_date_moves_and_archive_actions(self) -> None:
        self.add_plan("plan-a")
        self.add_unit("unit-a", {"plan_id": "plan-a", "date": "2031-02-10T00:00"})

        self.assertEqual(
            self.derive(
                [{"local_id": "unit-a", "action": "update", "name": "renamed"}]
            ),
            ({"plan_id": "plan-a", "plan_name": "Plan"}, set()),
        )
        self.assertEqual(
            self.derive(
                [{"local_id": "unit-a", "action": "update", "date": "2031-02-10"}]
            )[1],
            set(),
        )
        self.assertEqual(
            self.derive(
                [{"local_id": "unit-a", "action": "update", "date": "2031-02-11"}]
            )[1],
            {"plan-a"},
        )
        for action in ("delete", "archive", "restore"):
            with self.subTest(action=action):
                self.assertEqual(
                    self.derive([{"local_id": "unit-a", "action": action}])[1],
                    {"plan-a"},
                )
        self.assertEqual(
            self.derive([{"local_id": "unit-a", "action": "create"}]),
            ({}, set()),
        )

    def test_authorized_plan_is_applied_or_rejected_with_exact_scope_errors(
        self,
    ) -> None:
        self.add_plan("plan-a")
        self.add_plan("plan-b", name="Other")
        self.add_plan("archived", status="archived")
        self.add_unit("unit-a", {"plan_id": "plan-a"})

        self.assertEqual(
            self.derive([{"local_id": "unit-a"}], " plan-a "),
            ({"plan_id": "plan-a", "plan_name": "Plan"}, set()),
        )
        self.assert_app_error(
            lambda: self.derive([{"local_id": "unit-a"}], "plan-b"),
            status=403,
            message="Die Planreferenzen der Änderung sind nicht eindeutig.",
            reason="intent_scope_denied",
        )
        for unavailable in ("missing", "archived"):
            with self.subTest(unavailable=unavailable):
                self.assert_app_error(
                    lambda unavailable=unavailable: self.derive([], unavailable),
                    status=409,
                    message="Der benannte Trainingsplan ist nicht aktiv.",
                    reason="plan_not_available",
                )
        self.assertEqual(
            self.derive([], "plan-b"),
            ({"plan_id": "plan-b", "plan_name": "Other"}, set()),
        )

    def test_create_plan_ids_support_implicit_explicit_and_standalone_cases(
        self,
    ) -> None:
        self.add_plan("plan-a")
        self.add_unit("unit-a", {"plan_id": "plan-a", "date": "2031-02-10"})
        create = {"action": "create", "date": "2031-02-11"}

        self.assertEqual(
            self.derive([{"local_id": "unit-a"}, create]),
            ({"plan_id": "plan-a", "plan_name": "Plan"}, {"plan-a"}),
        )
        self.assertEqual(
            self.derive([{"local_id": "unit-a"}, {**create, "plan_id": " plan-a "}]),
            ({"plan_id": "plan-a", "plan_name": "Plan"}, {"plan-a"}),
        )
        self.assertEqual(self.derive([create]), ({}, set()))
        self.assertEqual(self.derive([{**create, "plan_id": ""}]), ({}, set()))
        self.assert_app_error(
            lambda: self.derive(
                [{"local_id": "unit-a"}, {**create, "plan_id": "other"}]
            ),
            status=403,
            message="Eine neue Einheit darf nur dem eindeutig abgeleiteten Plan zugeordnet werden.",
            reason="intent_scope_denied",
        )

    def test_changes_are_not_mutated(self) -> None:
        self.add_plan("plan-a")
        self.add_unit("unit-a", {"plan_id": "plan-a", "date": "2031-02-10"})
        changes = [
            {"action": "update", "local_id": "unit-a", "date": "2031-02-11"},
            {"action": "create", "plan_id": " plan-a "},
        ]
        original = copy.deepcopy(changes)

        self.derive(changes)

        self.assertEqual(changes, original)


if __name__ == "__main__":
    unittest.main()
