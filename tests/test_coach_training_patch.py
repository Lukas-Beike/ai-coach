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

    def test_one_batch_creates_workout_and_advances_revision_once(self):
        before = self.state()["planning_revision"]
        result = server.coach_training_patch_service().apply(
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
            server.coach_training_patch_service().apply(
                {"expected_revision": before["planning_revision"] - 1,
                 "changes": [], "workouts": [self.workout()]},
                self.action("local_plan"),
            )
        self.assertEqual(error.exception.reason, "planning_revision_conflict")
        self.assertEqual(self.state()["planned_units"], before["planned_units"])
        self.assertEqual(self.state()["planning_revision"], before["planning_revision"])

    def test_duplicate_calendar_day_rolls_back_plan_and_revision(self):
        before = self.state()["planning_revision"]
        with self.assertRaises(server.AppError) as error:
            server.coach_training_patch_service().apply(
                {"expected_revision": before, "changes": [],
                 "workouts": [self.workout(name="One"), self.workout(name="Two")],
                 "plan_name": "Synthetic conflicting plan"},
                self.action("local_plan"),
            )
        self.assertEqual(error.exception.reason, "plan_date_conflict")
        self.assertEqual(self.state()["planning_revision"], before)
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM training_plans").fetchone()["count"], 0)

    def test_approved_constraints_are_attached_to_created_plan(self):
        action = self.action("local_plan")
        action["request"]["constraints"] = ["Synthetic no hard session on Friday"]
        server.coach_training_patch_service().apply(
            {"expected_revision": self.state()["planning_revision"],
             "changes": [], "workouts": [self.workout()]},
            action,
        )
        with server.database_manager().unit_of_work() as db:
            plan_id = db.execute("SELECT id FROM training_plans").fetchone()["id"]
        self.assertEqual(
            json.loads(server.key_value_service().get(COACH_PLAN_CONSTRAINTS_PREFIX + plan_id)),
            action["request"]["constraints"],
        )

    def test_addition_requires_local_plan_scope(self):
        with self.assertRaises(server.AppError) as error:
            server.coach_training_patch_service().apply(
                {"expected_revision": self.state()["planning_revision"],
                 "changes": [], "workouts": [self.workout()]},
                self.action(),
            )
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.state()["planned_units"], [])

    def test_empty_or_oversized_batch_is_rejected_before_write(self):
        service = server.coach_training_patch_service()
        for arguments in (
            {"changes": [], "workouts": []},
            {"changes": [], "workouts": [self.workout()] * (coach_limits.COACH_TRAINING_CHANGE_LIMIT + 1)},
        ):
            with self.subTest(size=len(arguments["workouts"])), self.assertRaises(server.AppError) as error:
                service.apply(arguments, self.action("local_plan"))
            self.assertEqual(error.exception.reason, "change_limit")
        self.assertEqual(self.state()["planned_units"], [])
