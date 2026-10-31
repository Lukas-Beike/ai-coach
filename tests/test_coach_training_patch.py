"""Direct transaction and authorization contracts for Coach training patches."""

from __future__ import annotations

import json
import unittest

from test_coach_dialogue import DialogueHarness, server

from backend.coach import limits as coach_limits
from backend.planning.training_plans import COACH_PLAN_CONSTRAINTS_PREFIX


class CoachTrainingPatchTests(DialogueHarness, unittest.TestCase):
    def action(self, *scopes: str) -> dict:
        return {"authorization_scope": list(scopes), "request": {"constraints": []}}

    def add_plan(self, plan_id: str) -> None:
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db,
                plan_id,
                plan_id,
                "Build",
                "2026-09-01",
                "2026-09-30",
                "planned",
                "2026-09-01T00:00:00Z",
            )

    def add_unit(self, plan_id: str, day: str) -> str:
        workout = {**self.workout(day=day), "plan_id": plan_id, "plan_name": plan_id}
        return server.PLANNING_DATA.planned_unit().create(workout)["id"]

    def rename(self, local_id: str) -> dict:
        state = self.state()
        expected_hash = next(
            item["expected_payload_hash"]
            for item in state["planned_units"]
            if item["local_id"] == local_id
        )
        change = {
            "local_id": local_id,
            "action": "update",
            "name": "Renamed",
            "expected_payload_hash": expected_hash,
        }
        return {
            "expected_revision": state["planning_revision"],
            "changes": [change],
            "workouts": [],
        }

    def constraints(self, plan_id: str) -> str | None:
        return server.key_value_service().get(COACH_PLAN_CONSTRAINTS_PREFIX + plan_id)

    def test_named_plan_rejects_foreign_unit_before_write(self):
        self.add_plan("plan-a")
        self.add_plan("plan-b")
        unit_b = self.add_unit("plan-b", "2026-09-10")
        action = self.action("training_plan:plan-a", f"planned_unit:{unit_b}")
        action["request"]["constraints"] = ["Synthetic no intensity"]
        before = self.state()
        with self.assertRaises(server.AppError) as error:
            server.COACH_PLANNING_TOOLS.training_patch_service().apply(
                self.rename(unit_b), action
            )
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(error.exception.reason, "intent_scope_denied")
        self.assertEqual(self.state(), before)
        self.assertIsNone(self.constraints("plan-a"))
        self.assertIsNone(self.constraints("plan-b"))

    def test_named_plan_stores_constraints_only_under_that_plan(self):
        self.add_plan("plan-a")
        self.add_plan("plan-b")
        unit_a = self.add_unit("plan-a", "2026-09-10")
        self.add_unit("plan-b", "2026-09-11")
        action = self.action("training_plan:plan-a", f"planned_unit:{unit_a}")
        action["request"]["constraints"] = ["Synthetic no intensity"]
        result = server.COACH_PLANNING_TOOLS.training_patch_service().apply(
            self.rename(unit_a), action
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            json.loads(self.constraints("plan-a") or "null"),
            action["request"]["constraints"],
        )
        self.assertIsNone(self.constraints("plan-b"))

    def test_two_named_plans_are_rejected_before_write(self):
        self.add_plan("plan-a")
        self.add_plan("plan-b")
        unit_a = self.add_unit("plan-a", "2026-09-10")
        before = self.state()
        action = self.action(
            "local_plan",
            "training_plan:plan-a",
            "training_plan:plan-b",
            f"planned_unit:{unit_a}",
        )
        for arguments in (
            self.rename(unit_a),
            {
                "expected_revision": before["planning_revision"],
                "changes": [],
                "workouts": [self.workout(day="2026-09-12")],
            },
        ):
            with self.subTest(changes=bool(arguments["changes"])):
                with self.assertRaises(server.AppError) as error:
                    server.COACH_PLANNING_TOOLS.training_patch_service().apply(
                        arguments, action
                    )
                self.assertEqual(error.exception.status, 400)
                self.assertEqual(error.exception.reason, "intent_scope_denied")
        self.assertEqual(self.state(), before)

    def test_patch_without_named_plan_keeps_unit_changes_and_creations(self):
        self.add_plan("plan-b")
        unit_b = self.add_unit("plan-b", "2026-09-10")
        action = self.action("local_plan", f"planned_unit:{unit_b}")
        action["request"]["constraints"] = ["Synthetic no intensity"]
        result = server.COACH_PLANNING_TOOLS.training_patch_service().apply(
            self.rename(unit_b), action
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            json.loads(self.constraints("plan-b") or "null"),
            action["request"]["constraints"],
        )
        names = {
            item["local_id"]: item["name"] for item in self.state()["planned_units"]
        }
        self.assertEqual(names[unit_b], "Renamed")
        created = server.COACH_PLANNING_TOOLS.training_patch_service().apply(
            {
                "expected_revision": self.state()["planning_revision"],
                "changes": [],
                "workouts": [self.workout(day="2026-09-12")],
            },
            self.action("local_plan", "training_plan:plan-b"),
        )
        self.assertEqual(len(created["library_entry_ids"]), 1)

    def test_one_batch_creates_workout_and_advances_revision_once(self):
        before = self.state()["planning_revision"]
        result = server.COACH_PLANNING_TOOLS.training_patch_service().apply(
            {"expected_revision": before, "changes": [], "workouts": [self.workout()]},
            self.action("local_plan"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["planning_revision"], before + 1)
        self.assertEqual(len(result["library_entry_ids"]), 1)
        self.assertEqual(len(self.state()["planned_units"]), 1)

    def test_stale_revision_does_not_create_workout(self):
        before = self.state()
        with self.assertRaises(server.AppError) as error:
            server.COACH_PLANNING_TOOLS.training_patch_service().apply(
                {
                    "expected_revision": before["planning_revision"] - 1,
                    "changes": [],
                    "workouts": [self.workout()],
                },
                self.action("local_plan"),
            )
        self.assertEqual(error.exception.reason, "planning_revision_conflict")
        self.assertEqual(self.state()["planned_units"], before["planned_units"])
        self.assertEqual(self.state()["planning_revision"], before["planning_revision"])

    def test_duplicate_calendar_day_rolls_back_plan_and_revision(self):
        before = self.state()["planning_revision"]
        w1 = {
            **self.workout(name="One"),
            "date": "2026-09-08",
            "starts_at_local": "2026-09-08T08:00:00",
            "duration_minutes": 60,
        }
        w2 = {
            **self.workout(name="Two"),
            "date": "2026-09-08",
            "starts_at_local": "2026-09-08T08:30:00",
            "duration_minutes": 30,
        }
        with self.assertRaises(server.AppError) as error:
            server.COACH_PLANNING_TOOLS.training_patch_service().apply(
                {
                    "expected_revision": before,
                    "changes": [],
                    "workouts": [w1, w2],
                    "plan_name": "Synthetic conflicting plan",
                },
                self.action("local_plan"),
            )
        self.assertEqual(error.exception.reason, "plan_date_conflict")
        self.assertEqual(self.state()["planning_revision"], before)
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM training_plans").fetchone()[
                    "count"
                ],
                0,
            )

    def test_multiple_workouts_on_same_calendar_day_are_applied(self):
        before = self.state()["planning_revision"]
        result = server.COACH_PLANNING_TOOLS.training_patch_service().apply(
            {
                "expected_revision": before,
                "changes": [],
                "workouts": [
                    self.workout(name="One"),
                    {**self.workout(name="Two"), "sport": "Run"},
                ],
                "plan_name": "Synthetic multiple workouts plan",
            },
            self.action("local_plan"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["library_entry_ids"]), 2)
        self.assertEqual(len(self.state()["planned_units"]), 2)

    def test_approved_constraints_are_attached_to_created_plan(self):
        action = self.action("local_plan")
        action["request"]["constraints"] = ["Synthetic no hard session on Friday"]
        server.COACH_PLANNING_TOOLS.training_patch_service().apply(
            {
                "expected_revision": self.state()["planning_revision"],
                "changes": [],
                "workouts": [self.workout()],
            },
            action,
        )
        with server.database_manager().unit_of_work() as db:
            plan_id = db.execute("SELECT id FROM training_plans").fetchone()["id"]
        self.assertEqual(
            json.loads(
                server.key_value_service().get(COACH_PLAN_CONSTRAINTS_PREFIX + plan_id)
            ),
            action["request"]["constraints"],
        )

    def test_addition_requires_local_plan_scope(self):
        with self.assertRaises(server.AppError) as error:
            server.COACH_PLANNING_TOOLS.training_patch_service().apply(
                {
                    "expected_revision": self.state()["planning_revision"],
                    "changes": [],
                    "workouts": [self.workout()],
                },
                self.action(),
            )
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.state()["planned_units"], [])

    def test_empty_or_oversized_batch_is_rejected_before_write(self):
        service = server.COACH_PLANNING_TOOLS.training_patch_service()
        for arguments in (
            {"changes": [], "workouts": []},
            {
                "changes": [],
                "workouts": [self.workout()]
                * (coach_limits.COACH_TRAINING_CHANGE_LIMIT + 1),
            },
        ):
            with (
                self.subTest(size=len(arguments["workouts"])),
                self.assertRaises(server.AppError) as error,
            ):
                service.apply(arguments, self.action("local_plan"))
            self.assertEqual(error.exception.reason, "change_limit")
        self.assertEqual(self.state()["planned_units"], [])
