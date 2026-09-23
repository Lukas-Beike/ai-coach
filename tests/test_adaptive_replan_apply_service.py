from __future__ import annotations

import ast
import inspect
import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import PlanAdjustmentRepository, PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import adaptive
from backend.planning.adaptive import AdaptiveReplanApplyService
from backend.planning.revision import PlanningRevisionService

NOW = "2026-09-20T08:00:00+00:00"
TODAY = date(2026, 9, 20)


class MarkAppliedFailingRepository(PlanAdjustmentRepository):
    def mark_applied(self, db, adjustment_id, payload, status, applied_at):
        super().mark_applied(db, adjustment_id, payload, status, applied_at)
        raise RuntimeError("mark applied failed")


class AdaptiveReplanApplyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "adaptive-apply.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.repository = PlanAdjustmentRepository()
        self.revisions = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        self.service = self.make_service()

    def tearDown(self):
        self.manager.close()
        self.temporary_directory.cleanup()

    def make_service(self, repository=None):
        return AdaptiveReplanApplyService(
            self.manager,
            repository or self.repository,
            self.revisions,
            lambda: TODAY,
            lambda: NOW,
        )

    @staticmethod
    def workout(workout_id, day, **overrides):
        return {
            "id": workout_id,
            "date": day,
            "type": "Ride",
            "name": "Easy ride",
            "duration_minutes": 30,
            "description": "- 30m 60% Easy",
            "target": "AUTO",
            **overrides,
        }

    def add_workout(self, workout_id, workout, *, sync_state="local"):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, sync_dirty, sync_state, "
                "sync_conflict, created_at, updated_at) VALUES (?, ?, ?, 0, ?, '', ?, ?)",
                (
                    workout_id,
                    workout_id,
                    json.dumps(workout, ensure_ascii=False),
                    sync_state,
                    NOW,
                    NOW,
                ),
            )

    def add_preview(self, payload, adjustment_id=None):
        adjustment_id = adjustment_id or str(uuid.uuid4())
        with self.manager.unit_of_work() as db:
            self.repository.create_preview(
                db, adjustment_id, json.dumps(payload, ensure_ascii=False), NOW
            )
        return adjustment_id

    def row(self, query, params=()):
        with self.manager.reader() as db:
            return db.execute(query, params).fetchone()

    def test_applies_replacement_audit_revision_and_illness_checkins_atomically(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(
            workout_id,
            "2026-09-21",
            name="Tempo ride",
            description="- 30m 80%",
            workout_doc={"old": True},
            icu_training_load=88,
            icu_intensity=7,
        )
        self.add_workout(workout_id, original, sync_state="synced")
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO athlete_checkins(checkin_date, illness, notes, created_at, updated_at) "
                "VALUES (?, 'allergy', 'preexisting', ?, ?)",
                ("2026-09-20", NOW, NOW),
            )
        replacement = self.workout(
            workout_id,
            "2026-09-21",
            name="Recovery ride",
            duration_minutes=25,
            description="- 25m 50% Easy",
            workout_doc={"new": True},
            icu_training_load=20,
            icu_intensity=2,
        )
        archived_id = str(uuid.uuid4())
        archived = self.workout(archived_id, "2026-09-22")
        self.add_workout(archived_id, archived)
        preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": workout_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            original
                        ),
                        "payload": replacement,
                    },
                    {
                        "library_workout_id": archived_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            archived
                        ),
                        "payload": {
                            **archived,
                            "archived": True,
                            "description": "not valid for workout validation",
                        },
                    },
                ],
                "illness_pause": {
                    "start_date": "2026-09-20",
                    "end_date": "2026-09-21",
                    "illness": "cold",
                },
            }
        )

        result = self.service.apply(preview_id.upper())

        self.assertEqual(
            result,
            {
                "status": "applied",
                "id": preview_id,
                "updated": 2,
                "updated_checkins": 2,
                "stale": [],
                "illness_pause": {
                    "start_date": "2026-09-20",
                    "end_date": "2026-09-21",
                    "illness": "cold",
                },
            },
        )
        planned = self.row(
            "SELECT payload, sync_dirty, sync_state FROM planned_units WHERE local_id=?",
            (workout_id,),
        )
        saved = json.loads(planned["payload"])
        self.assertEqual((planned["sync_dirty"], planned["sync_state"]), (1, "local"))
        self.assertEqual(saved["name"], "Recovery ride")
        self.assertEqual(saved["moving_time"], 1500)
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
            self.assertNotIn(key, saved)
        archived_saved = json.loads(
            self.row(
                "SELECT payload FROM planned_units WHERE local_id=?", (archived_id,)
            )["payload"]
        )
        self.assertTrue(archived_saved["archived"])
        self.assertEqual(self.row("SELECT revision FROM planning_state")["revision"], 1)
        checkins = self.row(
            "SELECT illness, notes FROM athlete_checkins WHERE checkin_date='2026-09-20'"
        )
        self.assertEqual(checkins["illness"], "allergy; cold")
        self.assertEqual(
            checkins["notes"],
            "preexisting · Krankheitspause prognostiziert ab 2026-09-20",
        )
        self.assertIsNotNone(
            self.row("SELECT 1 FROM athlete_checkins WHERE checkin_date='2026-09-21'")
        )
        audit = self.row(
            "SELECT source, before_hash, after_hash, diff FROM change_history "
            "WHERE entity_id=?",
            (workout_id,),
        )
        self.assertEqual(audit["source"], "adaptive_replan")
        self.assertNotEqual(audit["before_hash"], audit["after_hash"])
        self.assertIn("Tempo ride", audit["diff"])
        applied = json.loads(
            self.row("SELECT payload FROM plan_adjustments WHERE id=?", (preview_id,))[
                "payload"
            ]
        )
        self.assertTrue(applied["illness_pause"]["approved"])
        self.assertEqual(
            self.service.apply(preview_id),
            {"status": "already_applied", "id": preview_id},
        )

    def test_stale_partial_and_past_reasons_are_idempotent(self):
        good_id, changed_id, past_id = (str(uuid.uuid4()) for _ in range(3))
        good = self.workout(good_id, "2026-09-22")
        changed = self.workout(changed_id, "2026-09-22", name="Changed after preview")
        past = self.workout(past_id, "2026-09-19")
        for workout_id, payload in (
            (good_id, good),
            (changed_id, changed),
            (past_id, past),
        ):
            self.add_workout(workout_id, payload)
        preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": good_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            good
                        ),
                        "payload": {**good, "name": "Updated"},
                    },
                    {
                        "library_workout_id": changed_id,
                        "source_fingerprint": "wrong-fingerprint",
                        "payload": {**changed, "name": "Must not overwrite"},
                    },
                    {
                        "library_workout_id": past_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            past
                        ),
                        "payload": {**past, "name": "Must not update past"},
                    },
                    {
                        "library_workout_id": str(uuid.uuid4()),
                        "source_fingerprint": "absent",
                        "payload": good,
                    },
                ]
            }
        )

        result = self.service.apply(preview_id)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["updated"], 1)
        self.assertEqual(
            [
                (item["library_workout_id"], item["reason"])
                for item in result["stale"][:2]
            ],
            [(changed_id, "changed"), (past_id, "past")],
        )
        self.assertEqual(len(result["stale"]), 3)
        self.assertEqual(result["stale"][2]["reason"], "missing")
        self.assertIsInstance(result["stale"][2]["library_workout_id"], str)
        self.assertEqual(self.row("SELECT revision FROM planning_state")["revision"], 1)
        self.assertEqual(
            self.service.apply(preview_id),
            {"status": "already_partial", "id": preview_id},
        )

        stale_id = str(uuid.uuid4())
        self.add_workout(stale_id, self.workout(stale_id, "2026-09-22"))
        stale_preview_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": stale_id,
                        "source_fingerprint": "old",
                        "payload": self.workout(stale_id, "2026-09-22", name="no"),
                    }
                ]
            }
        )
        stale_result = self.service.apply(stale_preview_id)
        self.assertEqual(stale_result["status"], "stale")
        self.assertEqual(stale_result["updated"], 0)
        self.assertEqual(self.row("SELECT revision FROM planning_state")["revision"], 1)
        self.assertEqual(
            self.service.apply(stale_preview_id),
            {"status": "already_stale", "id": stale_preview_id},
        )

    def test_invalid_uuid_and_missing_preview_raise_app_errors(self):
        with self.assertRaises(AppError) as invalid:
            self.service.apply("not-a-uuid")
        self.assertEqual(
            (invalid.exception.status, invalid.exception.message),
            (400, "Ungültige Plananpassung."),
        )
        with self.assertRaises(AppError) as missing:
            self.service.apply(uuid.uuid4())
        self.assertEqual(
            (missing.exception.status, missing.exception.message),
            (404, "Plananpassung nicht gefunden."),
        )

    def test_non_object_preview_payload_fails_without_writes(self):
        adjustment_id = str(uuid.uuid4())
        with self.manager.unit_of_work() as db:
            self.repository.create_preview(db, adjustment_id, "[]", NOW)
        before = self._state_snapshot()

        with self.assertRaises(AttributeError):
            self.service.apply(adjustment_id)

        self.assertEqual(self._state_snapshot(), before)

    def test_late_mark_applied_failure_rolls_back_all_tables(self):
        workout_id = str(uuid.uuid4())
        original = self.workout(workout_id, "2026-09-21")
        self.add_workout(workout_id, original)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO athlete_checkins(checkin_date, illness, notes, created_at, updated_at) "
                "VALUES ('2026-09-20', 'existing', 'notes', ?, ?)",
                (NOW, NOW),
            )
        adjustment_id = self.add_preview(
            {
                "changes": [
                    {
                        "library_workout_id": workout_id,
                        "source_fingerprint": adaptive.adaptive_workout_fingerprint(
                            original
                        ),
                        "payload": {**original, "name": "Updated"},
                    }
                ],
                "illness_pause": {
                    "start_date": "2026-09-20",
                    "end_date": "2026-09-21",
                    "illness": "cold",
                },
            }
        )
        before = self._state_snapshot()
        service = self.make_service(MarkAppliedFailingRepository())

        with self.assertRaisesRegex(RuntimeError, "mark applied failed"):
            service.apply(adjustment_id)

        self.assertEqual(self._state_snapshot(), before)

    def _state_snapshot(self):
        with self.manager.reader() as db:
            return {
                table: [
                    dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()
                ]
                for table in (
                    "plan_adjustments",
                    "planned_units",
                    "athlete_checkins",
                    "planning_state",
                    "change_history",
                )
            }

    def test_module_has_no_server_provider_event_imports_or_removed_api(self):
        tree = ast.parse(inspect.getsource(adaptive))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.append(node.module)
                modules.extend(alias.name for alias in node.names)
        self.assertTrue(
            all(
                not any(
                    "server" == part.casefold()
                    or "provider" in part.casefold()
                    or "event" in part.casefold()
                    for part in module.split(".")
                )
                for module in modules
            )
        )
        defined_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        self.assertNotIn("AdaptiveDependencies", defined_names)
        self.assertNotIn("apply_adaptive_changes", defined_names)
        self.assertFalse(hasattr(adaptive, "AdaptiveDependencies"))
        self.assertFalse(hasattr(adaptive, "apply_adaptive_changes"))


if __name__ == "__main__":
    unittest.main()
