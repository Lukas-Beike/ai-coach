"""Focused SQLite tests for the local training-plan artifact lifecycle."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning.training_plan_artifact_service import (
    TrainingPlanArtifactService,
)

NOW = "2026-09-20T09:00:00+00:00"
TODAY = date(2026, 9, 20)
ARTIFACT_ID = "00000000-0000-0000-0000-000000000001"


class LocalPlanCreationStub:
    """Write representative plan, unit, and revision rows on the given DB."""

    def __init__(self) -> None:
        self.calendar_error: AppError | None = None
        self.fail_after_writes = False
        self.calendar_calls: list[list[dict[str, object]]] = []

    def validate_calendar(self, workouts: list[dict[str, object]]) -> None:
        self.calendar_calls.append(workouts)
        if self.calendar_error:
            raise self.calendar_error

    def save(
        self,
        workouts: list[dict[str, object]],
        plan_name: str,
        goal: str,
        *,
        db: sqlite3.Connection,
    ) -> list[dict[str, str]]:
        plan_id = "00000000-0000-0000-0000-000000000010"
        unit_id = "00000000-0000-0000-0000-000000000011"
        plan_date = str(workouts[0]["date"])
        db.execute(
            "INSERT INTO training_plans "
            "(id, name, goal, start_date, end_date, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'planned', ?, ?)",
            (plan_id, plan_name, goal, plan_date, plan_date, NOW, NOW),
        )
        db.execute(
            "INSERT INTO planned_units "
            "(id, local_id, payload, sync_dirty, sync_state, sync_conflict, revision, tombstone, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, 'local', '', 0, 0, ?, ?)",
            (
                unit_id,
                unit_id,
                json.dumps(workouts[0], ensure_ascii=False),
                NOW,
                NOW,
            ),
        )
        db.execute(
            "UPDATE planning_state SET revision=revision+1, updated_at=? WHERE id=1",
            (NOW,),
        )
        if self.fail_after_writes:
            raise RuntimeError("late local plan failure")
        return [{"id": unit_id}]


class TrainingPlanArtifactServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "planning.sqlite"
        db = sqlite3.connect(self.database_path)
        try:
            db.row_factory = row_factory
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 7, ?)",
                (NOW,),
            )
            db.commit()
        finally:
            db.close()
        self.database_manager = DatabaseManager(
            self.database_path,
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        self.local_plan = LocalPlanCreationStub()
        self.ids = iter([ARTIFACT_ID, "00000000-0000-0000-0000-000000000002"])
        self.service = TrainingPlanArtifactService(
            self.database_manager,
            self.local_plan,
            lambda: TODAY,
            lambda: NOW,
            lambda: next(self.ids),
        )

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temp_dir.cleanup()

    @staticmethod
    def arguments() -> dict[str, object]:
        return {
            "payload": {
                "plan_name": "Plan für Läufer",
                "goal": "10-km-Ziel",
                "workouts": [
                    {
                        "date": "2026-09-22",
                        "sport": "rad",
                        "name": " Einheit ",
                        "description": "- 30m Z2",
                        "duration_minutes": "30",
                        "target": "POWER",
                        "rationale": "locker",
                    }
                ],
            }
        }

    def stage(self, *, conversation_id: str = "conversation-a") -> dict[str, object]:
        return self.service.stage(self.arguments(), conversation_id, "turn-a")

    def row(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> dict[str, object] | None:
        with self.database_manager.reader() as db:
            return db.execute(sql, parameters).fetchone()

    def count(self, table: str) -> int:
        row = self.row(f"SELECT COUNT(*) AS count FROM {table}")
        assert row is not None
        return int(row["count"])

    def test_stage_normalizes_workouts_and_captures_current_revision(self) -> None:
        result = self.stage()

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "draft",
                "artifact_id": ARTIFACT_ID,
                "base_revision": 7,
            },
        )
        stored = self.row(
            "SELECT payload, base_revision, status FROM coach_plan_artifacts WHERE id=?",
            (ARTIFACT_ID,),
        )
        self.assertIsNotNone(stored)
        payload_text = str(stored["payload"])
        self.assertIn("Plan für Läufer", payload_text)
        self.assertNotIn(": ", payload_text)
        self.assertNotIn(", ", payload_text)
        payload = json.loads(payload_text)
        workout = payload["workouts"][0]
        self.assertEqual(workout["sport"], "Ride")
        self.assertEqual(workout["name"], "Einheit")
        self.assertEqual(workout["duration_minutes"], 30)
        self.assertEqual(stored["base_revision"], 7)
        self.assertEqual(stored["status"], "draft")
        self.assertEqual(len(self.local_plan.calendar_calls), 1)

    def test_calendar_conflict_creates_no_artifact_row(self) -> None:
        self.local_plan.calendar_error = AppError(
            409, "Kalender belegt.", reason="plan_date_conflict"
        )

        with self.assertRaises(AppError) as raised:
            self.stage()

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.message, "Kalender belegt.")
        self.assertEqual(raised.exception.reason, "plan_date_conflict")
        self.assertEqual(self.count("coach_plan_artifacts"), 0)

    def test_successful_commit_is_atomic_and_replay_is_idempotent(self) -> None:
        self.stage()

        result = self.service.commit(ARTIFACT_ID, "conversation-a")

        self.assertEqual(result["status"], "committed")
        self.assertEqual(
            result["library_entry_ids"], ["00000000-0000-0000-0000-000000000011"]
        )
        self.assertEqual(
            self.row(
                "SELECT status FROM coach_plan_artifacts WHERE id=?", (ARTIFACT_ID,)
            )["status"],
            "committed",
        )
        self.assertEqual(
            self.row("SELECT revision FROM planning_state WHERE id=1")["revision"], 8
        )
        self.assertEqual(self.count("training_plans"), 1)
        self.assertEqual(self.count("planned_units"), 1)

        replay = self.service.commit(ARTIFACT_ID, "another-conversation")

        self.assertEqual(
            replay,
            {"ok": True, "status": "already_applied", "artifact_id": ARTIFACT_ID},
        )
        self.assertEqual(self.count("training_plans"), 1)

    def test_missing_unavailable_and_corrupt_payload_errors_are_preserved(self) -> None:
        with self.assertRaises(AppError) as missing:
            self.service.commit("missing", "conversation-a")
        self.assertEqual(
            (missing.exception.status, missing.exception.reason),
            (404, "artifact_not_found"),
        )

        self.stage()
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE coach_plan_artifacts SET status='superseded' WHERE id=?",
                (ARTIFACT_ID,),
            )
        with self.assertRaises(AppError) as unavailable:
            self.service.commit(ARTIFACT_ID, "conversation-a")
        self.assertEqual(
            (unavailable.exception.status, unavailable.exception.reason),
            (409, "artifact_not_available"),
        )

        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE coach_plan_artifacts SET status='draft', payload='{' WHERE id=?",
                (ARTIFACT_ID,),
            )
        with self.assertRaises(json.JSONDecodeError):
            self.service.commit(ARTIFACT_ID, "conversation-a")

    def test_conversation_conflict_and_explicit_rebind(self) -> None:
        self.stage()

        with self.assertRaises(AppError) as raised:
            self.service.commit(ARTIFACT_ID, "conversation-b")
        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (409, "artifact_conversation_conflict"),
        )
        self.assertEqual(
            self.row(
                "SELECT conversation_id FROM coach_plan_artifacts WHERE id=?",
                (ARTIFACT_ID,),
            )["conversation_id"],
            "conversation-a",
        )

        result = self.service.commit(
            ARTIFACT_ID, "conversation-b", explicit_artifact=True
        )

        self.assertEqual(result["status"], "committed")
        self.assertEqual(
            self.row(
                "SELECT conversation_id FROM coach_plan_artifacts WHERE id=?",
                (ARTIFACT_ID,),
            )["conversation_id"],
            "conversation-b",
        )

    def test_revision_conflict_rejects_stale_draft(self) -> None:
        self.stage()
        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE planning_state SET revision=revision+1 WHERE id=1")

        with self.assertRaises(AppError) as raised:
            self.service.commit(ARTIFACT_ID, "conversation-a")

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (409, "planning_revision_conflict"),
        )
        self.assertEqual(self.count("training_plans"), 0)
        self.assertEqual(
            self.row(
                "SELECT status FROM coach_plan_artifacts WHERE id=?", (ARTIFACT_ID,)
            )["status"],
            "draft",
        )

    def test_conditional_status_update_conflict_rolls_back_local_plan_writes(
        self,
    ) -> None:
        self.stage()
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER ignore_artifact_commit BEFORE UPDATE OF status ON coach_plan_artifacts "
                "WHEN NEW.status='committed' BEGIN SELECT RAISE(IGNORE); END"
            )

        with self.assertRaises(AppError) as raised:
            self.service.commit(ARTIFACT_ID, "conversation-a")

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (409, "artifact_revision_conflict"),
        )
        self.assertEqual(self.count("training_plans"), 0)
        self.assertEqual(self.count("planned_units"), 0)
        self.assertEqual(
            self.row("SELECT revision FROM planning_state WHERE id=1")["revision"], 7
        )
        self.assertEqual(
            self.row(
                "SELECT status FROM coach_plan_artifacts WHERE id=?", (ARTIFACT_ID,)
            )["status"],
            "draft",
        )

    def test_late_local_plan_failure_rolls_back_all_writes(self) -> None:
        self.stage()
        self.local_plan.fail_after_writes = True

        with self.assertRaisesRegex(RuntimeError, "late local plan failure"):
            self.service.commit(ARTIFACT_ID, "conversation-a")

        self.assertEqual(self.count("training_plans"), 0)
        self.assertEqual(self.count("planned_units"), 0)
        self.assertEqual(
            self.row("SELECT revision FROM planning_state WHERE id=1")["revision"], 7
        )
        self.assertEqual(
            self.row(
                "SELECT status FROM coach_plan_artifacts WHERE id=?", (ARTIFACT_ID,)
            )["status"],
            "draft",
        )


if __name__ == "__main__":
    unittest.main()
