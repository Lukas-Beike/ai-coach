from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.db.manager import DatabaseManager
from backend.errors import AppError


class RecordingSQLiteBackend:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def connect(self, path: str | Path, **kwargs: object) -> sqlite3.Connection:
        connection = sqlite3.connect(path, **kwargs)
        connection.set_trace_callback(self.statements.append)
        return connection


class CoachDialoguePlanScopeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backend = RecordingSQLiteBackend()
        self.database = DatabaseManager(
            Path(self.temp_dir.name) / "scope.sqlite",
            self.backend,
            row_factory=sqlite3.Row,
        )
        self.lock = threading.RLock()
        self.service = CoachDialoguePlanScopeService(self.database, self.lock)
        with self.database.unit_of_work() as db:
            db.executescript(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT);"
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, client_turn_id TEXT, role TEXT);"
                "CREATE TABLE coach_plan_artifacts (id TEXT PRIMARY KEY, client_turn_id TEXT, payload TEXT, status TEXT);"
            )
            db.execute(
                "INSERT INTO planned_units VALUES (?, ?)",
                ("unit-1", json.dumps({"date": "2026-09-25"})),
            )
            db.executemany(
                "INSERT INTO messages VALUES (?, ?, 'user')",
                [(11, "turn-1"), (12, "turn-foreign")],
            )
            artifact_payload = json.dumps({"workouts": [{"date": "2026-09-26"}]})
            db.executemany(
                "INSERT INTO coach_plan_artifacts VALUES (?, ?, ?, 'draft')",
                [("draft-1", "turn-1", artifact_payload), ("draft-foreign", "turn-foreign", artifact_payload)],
            )
        self.backend.statements.clear()

    def tearDown(self) -> None:
        self.database.close()
        self.temp_dir.cleanup()

    @staticmethod
    def action(*, scopes: list[str] | None = None, source_ids: list[int] | None = None) -> dict:
        return {
            "period": {"start": "2026-09-24", "end": "2026-10-10"},
            "authorization_scope": scopes or ["planned_unit:unit-1"],
            "request": {"source_message_ids": source_ids or [11]},
            "artifact_id": "draft-1",
        }

    def test_accepts_bounded_workout_change_and_library_entry_dates(self) -> None:
        self.service.validate("stage_training_plan", {"payload": {"workouts": [{"date": "2026-09-25"}]}}, self.action())
        self.service.validate("apply_training_changes", {"changes": [{"local_id": "unit-1", "date": "2026-09-26"}]}, self.action())
        self.service.validate("apply_workout_library_plan", {"entries": [{"date": "2026-09-27"}]}, self.action())

    def test_rejects_dates_outside_period_for_workouts_changes_and_library_entries(self) -> None:
        for name, arguments in (
            ("stage_training_plan", {"workouts": [{"date": "2026-10-11"}]}),
            ("apply_training_changes", {"changes": [{"local_id": "unit-1", "date": "2026-10-11"}]}),
            ("apply_workout_library_plan", {"entries": [{"date": "2026-10-11"}]}),
        ):
            with self.subTest(name=name), self.assertRaises(AppError) as raised:
                self.service.validate(name, arguments, self.action())
            self.assertEqual((raised.exception.status, raised.exception.reason), (403, "request_period"))

    def test_rejects_planned_unit_scope_mismatch_before_database_lookup(self) -> None:
        action = self.action(scopes=["planned_unit:unit-2"])

        with self.assertRaises(AppError) as raised:
            self.service.validate("apply_training_changes", {"changes": [{"local_id": "unit-1"}]}, action)

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.assertFalse(any("SELECT payload FROM planned_units" in sql for sql in self.backend.statements))

    def test_rejects_missing_planned_unit(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.validate(
                "apply_training_changes",
                {"changes": [{"local_id": "unit-missing"}]},
                self.action(scopes=["planned_unit:unit-missing"]),
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (404, "request_object_missing"))

    def test_rejects_existing_planned_unit_outside_period(self) -> None:
        with self.database.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id='unit-1'",
                (json.dumps({"date": "2026-10-11"}),),
            )
        self.backend.statements.clear()

        with self.assertRaises(AppError) as raised:
            self.service.validate("apply_training_changes", {"changes": [{"local_id": "unit-1"}]}, self.action())

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "request_period"))

    def test_rejects_foreign_draft_without_leaving_explicit_artifact_flag(self) -> None:
        action = self.action(source_ids=[11])
        action["artifact_id"] = "draft-foreign"
        action["_artifact_explicit"] = True

        with self.assertRaises(AppError) as raised:
            self.service.validate("commit_training_plan", {}, action)

        self.assertEqual((raised.exception.status, raised.exception.reason), (409, "artifact_conversation_conflict"))
        self.assertNotIn("_artifact_explicit", action)

    def test_marks_only_a_verified_draft_from_a_classified_source_message(self) -> None:
        action = self.action(source_ids=[11])

        self.service.validate("commit_training_plan", {}, action)

        self.assertIs(action["_artifact_explicit"], True)

    def test_rejects_draft_with_workout_outside_period_without_setting_flag(self) -> None:
        with self.database.unit_of_work() as db:
            db.execute(
                "UPDATE coach_plan_artifacts SET payload=? WHERE id='draft-1'",
                (json.dumps({"workouts": [{"date": "2026-10-11"}]}),),
            )
        self.backend.statements.clear()
        action = self.action(source_ids=[11])

        with self.assertRaises(AppError) as raised:
            self.service.validate("commit_training_plan", {}, action)

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "request_period"))
        self.assertNotIn("_artifact_explicit", action)

    def test_scope_validation_performs_reads_only(self) -> None:
        self.service.validate(
            "apply_training_changes",
            {"changes": [{"local_id": "unit-1", "date": "2026-09-26"}]},
            self.action(),
        )

        writes = [
            statement for statement in self.backend.statements
            if re.match(r"\s*(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b", statement, re.IGNORECASE)
        ]
        self.assertEqual([], writes)


if __name__ == "__main__":
    unittest.main()
