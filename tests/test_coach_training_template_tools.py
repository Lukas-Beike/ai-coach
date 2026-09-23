from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.db.manager import DatabaseManager
from backend.errors import STRUCTURED_AUTHORIZATION_ERROR, AppError


class TrainingTemplateToolTests(unittest.TestCase):
    def test_restore_batch_uses_current_manager_and_rolls_back_prior_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_manager = DatabaseManager(Path(directory) / "old.db", sqlite3)
            current_manager = DatabaseManager(Path(directory) / "current.db", sqlite3)
            for manager in (old_manager, current_manager):
                with manager.unit_of_work() as db:
                    db.execute("CREATE TABLE writes (template_id TEXT PRIMARY KEY)")

            active_manager = [old_manager]
            lock = threading.RLock()
            library_resolutions: list[DatabaseManager] = []

            class Library:
                def update(self, local_id, values):
                    with active_manager[0].unit_of_work() as db:
                        db.execute("INSERT INTO writes VALUES (?)", (local_id,))
                        if values.get("invalid"):
                            raise AppError(400, "invalid template")
                    return {"local_id": local_id}

                def create_template(self, values):
                    raise AssertionError("Unexpected create")

            def manager_factory():
                self.assertTrue(lock._is_owned())
                return active_manager[0]

            def library_factory():
                self.assertTrue(lock._is_owned())
                library_resolutions.append(active_manager[0])
                return Library()

            service = TrainingTemplateToolService(manager_factory, lock, library_factory)
            active_manager[0] = current_manager  # Simulate manager replacement after restore.
            intent = {
                "operation": "manage_training_templates",
                "authorization_scope": ["library_workout:restored", "library_workout:bad"],
            }

            with self.assertRaisesRegex(AppError, "invalid template"):
                service.execute(
                    {
                        "templates": [
                            {"action": "restore", "local_id": "restored"},
                            {"action": "update", "local_id": "bad", "invalid": True},
                        ]
                    },
                    intent,
                )

            self.assertEqual(library_resolutions, [current_manager])
            with current_manager.reader() as db:
                self.assertEqual(db.execute("SELECT * FROM writes").fetchall(), [])
            with old_manager.reader() as db:
                self.assertEqual(db.execute("SELECT * FROM writes").fetchall(), [])
            old_manager.close()
            current_manager.close()

    def test_requires_operation_and_template_scope_before_manager_resolution(self) -> None:
        manager_calls = []
        service = TrainingTemplateToolService(
            lambda: manager_calls.append("manager"),
            threading.RLock(),
            lambda: self.fail("Library must not be resolved"),
        )
        with self.assertRaises(AppError) as denied:
            service.execute({"templates": [{"name": "x"}]}, {"operation": "other"})
        self.assertEqual(denied.exception.message, STRUCTURED_AUTHORIZATION_ERROR)
        self.assertEqual(manager_calls, [])

        with self.assertRaises(AppError) as missing_scope:
            service.execute(
                {"templates": [{"name": "x"}]},
                {"operation": "manage_training_templates", "authorization_scope": []},
            )
        self.assertEqual(missing_scope.exception.status, 403)
        self.assertEqual(manager_calls, [])


if __name__ == "__main__":
    unittest.main()
