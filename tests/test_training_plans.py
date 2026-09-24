"""Transactional training-plan metadata regression tests."""

from __future__ import annotations

import json
import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from backend.db import row_factory
from backend.db.repositories import (
    KeyValueRepository,
    PlanningStateRepository,
    TrainingPlanRepository,
)
from backend.errors import AppError
from backend.planning.revision import PlanningRevisionService
from backend.planning.training_plans import (
    COACH_PLAN_CONSTRAINTS_PREFIX,
    TrainingPlanService,
)


class _DatabaseManager:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def unit_of_work(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, name, payload):
        self.events.append((name, payload))


class TrainingPlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.db.executescript(
            """
            CREATE TABLE training_plans (
                id TEXT PRIMARY KEY, name TEXT, goal TEXT, start_date TEXT,
                end_date TEXT, status TEXT, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
            CREATE TABLE planning_state (
                id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, updated_at TEXT
            );
            INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, 'old');
            """
        )
        self.now = "2026-09-20T09:00:00+00:00"
        self.repository = TrainingPlanRepository()
        self.key_values = KeyValueRepository(lambda: self.now)
        self.revisions = PlanningRevisionService(
            PlanningStateRepository(), lambda: self.now
        )
        self.events = _Events()
        self.service = TrainingPlanService(
            _DatabaseManager(self.db),
            self.repository,
            self.key_values,
            self.revisions,
            self.events,
            lambda: self.now,
        )
        self.plan_id = str(uuid.uuid4())
        self.repository.create(
            self.db,
            self.plan_id,
            "Base",
            "",
            "2026-01-01",
            "2026-01-03",
            "planned",
            "old",
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def revision(self):
        return self.db.execute(
            "SELECT revision FROM planning_state WHERE id=1"
        ).fetchone()["revision"]

    def test_update_commits_history_revision_and_event(self):
        changes = []
        with patch(
            "backend.planning.training_plans.change_history.record_change",
            side_effect=lambda *args, **kwargs: changes.append((args, kwargs)),
        ):
            result = self.service.update(
                self.plan_id,
                {
                    "name": "Updated",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-04",
                },
            )

        self.assertEqual(result["plan"]["name"], "Updated")
        self.assertEqual(self.repository.get(self.db, self.plan_id)["name"], "Updated")
        self.assertEqual(changes[0][0][3], "update")
        self.assertEqual(self.revision(), 1)
        self.assertEqual(self.events.events, [("coach", {"status": "changed"})])

    def test_failed_update_rolls_back_and_does_not_publish(self):
        with (
            patch(
                "backend.planning.training_plans.change_history.record_change",
                side_effect=RuntimeError("history failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.service.update(self.plan_id, {"name": "Not committed"})

        self.assertEqual(self.repository.get(self.db, self.plan_id)["name"], "Base")
        self.assertEqual(self.revision(), 0)
        self.assertEqual(self.events.events, [])

    def test_delete_and_public_validation_errors_match_server_contract(self):
        with patch("backend.planning.training_plans.change_history.record_change"):
            result = self.service.update(self.plan_id, {"action": "delete"})
        self.assertEqual(
            result, {"status": "deleted", "plan_id": self.plan_id, "plan": None}
        )
        self.assertIsNone(self.repository.get(self.db, self.plan_id))
        self.assertEqual(self.revision(), 1)

        cases = (
            ("not-a-uuid", {}, 400, "Ungültige Trainingsplan-ID."),
            (str(uuid.uuid4()), {}, 404, "Trainingsplan nicht gefunden."),
        )
        for plan_id, values, status, message in cases:
            with self.subTest(message=message), self.assertRaises(AppError) as raised:
                self.service.update(plan_id, values)
            self.assertEqual(raised.exception.status, status)
            self.assertEqual(str(raised.exception), message)

    def test_list_includes_persisted_constraints(self):
        constraints = [{"kind": "rest_day", "date": "2026-01-02"}]
        self.key_values.set(
            self.db,
            COACH_PLAN_CONSTRAINTS_PREFIX + self.plan_id,
            json.dumps(constraints),
        )

        plans = self.service.list()

        self.assertEqual(plans[0]["constraints"], constraints)

    def test_update_bounds_uses_caller_transaction_and_records_change(self):
        self.db.execute(
            "INSERT INTO planned_units VALUES (?, ?)",
            ("u1", json.dumps({"plan_id": self.plan_id, "date": "2026-01-03"})),
        )
        self.db.execute(
            "INSERT INTO planned_units VALUES (?, ?)",
            ("u2", json.dumps({"plan_id": self.plan_id, "date": "2026-01-05"})),
        )
        changes = []
        with patch(
            "backend.planning.training_plans.change_history.record_change",
            side_effect=lambda *args, **kwargs: changes.append((args, kwargs)),
        ):
            self.service.update_bounds(self.db, {self.plan_id})

        plan = self.repository.get(self.db, self.plan_id)
        self.assertEqual(
            (plan["start_date"], plan["end_date"]), ("2026-01-03", "2026-01-05")
        )
        self.assertEqual(changes[0][0][1:4], ("training_plan", self.plan_id, "update"))
        self.assertEqual(changes[0][1]["source"], "coach_apply")

    def test_restore_in_transaction_updates_without_history_revision_or_event(self):
        current = self.repository.get(self.db, self.plan_id)
        target = {"name": "Restored", "status": "active"}
        target_before = dict(target)

        with patch(
            "backend.planning.training_plans.change_history.record_change"
        ) as record_change:
            restored = self.service.restore_in_transaction(
                self.db, self.plan_id, current, target
            )

        stored = self.repository.get(self.db, self.plan_id)
        self.assertEqual(restored["name"], "Restored")
        self.assertEqual(stored["name"], "Restored")
        self.assertEqual(stored["status"], "active")
        self.assertEqual(stored["updated_at"], self.now)
        self.assertEqual(target, target_before)
        self.assertEqual(self.revision(), 0)
        self.assertEqual(self.events.events, [])
        record_change.assert_not_called()

    def test_restore_in_transaction_recreates_and_physically_deletes(self):
        self.repository.delete(self.db, self.plan_id)
        target = {
            "id": self.plan_id,
            "name": "Restored",
            "goal": "Finish",
            "start_date": "2026-02-01",
            "end_date": "2026-03-01",
            "status": "draft",
        }

        recreated = self.service.restore_in_transaction(
            self.db, self.plan_id, None, target
        )
        self.assertEqual(recreated, target)
        self.assertEqual(self.repository.get(self.db, self.plan_id)["name"], "Restored")

        deleted = self.service.restore_in_transaction(
            self.db,
            self.plan_id,
            self.repository.get(self.db, self.plan_id),
            None,
        )
        self.assertIsNone(deleted)
        self.assertIsNone(self.repository.get(self.db, self.plan_id))
        self.assertEqual(self.revision(), 0)
        self.assertEqual(self.events.events, [])

    def test_restore_in_transaction_rolls_back_with_outer_unit_of_work(self):
        original = self.repository.get(self.db, self.plan_id)

        with (
            self.assertRaisesRegex(RuntimeError, "abort undo"),
            self.service._database_manager.unit_of_work() as db,
        ):
            self.service.restore_in_transaction(
                db, self.plan_id, original, {"name": "Not committed"}
            )
            raise RuntimeError("abort undo")

        self.assertEqual(self.repository.get(self.db, self.plan_id), original)
        self.assertEqual(self.revision(), 0)
        self.assertEqual(self.events.events, [])


if __name__ == "__main__":
    unittest.main()
