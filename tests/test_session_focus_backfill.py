"""One-time backfill of unambiguous derived session focus on future units (#1849)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
import uuid
from datetime import date
from pathlib import Path

from backend.activities.workout_load import AthleteThresholds
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.planning.planned_unit_load import estimate_planned_unit
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill_assembly import build_canonical_backfill
from backend.sync.session_focus_backfill import (
    STATE_KEY,
    SessionFocusBackfill,
    summarize_session_focus_backfill,
)

NOW = "2026-11-08T08:00:00+00:00"
TODAY = date(2026, 11, 8)


class NoCalendarConflicts:
    def constraints(self, _workout):
        return []

    def conflicts(self, _workout, _excluded):
        return []


class SessionFocusBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary.name) / "backfill.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.revisions = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        self.counter = 0

        def new_id() -> uuid.UUID:
            self.counter += 1
            return uuid.UUID(int=self.counter)

        self.units = PlannedUnitService(
            self.manager,
            self.revisions,
            lambda: NOW,
            lambda: TODAY,
            new_id,
            lambda value: value,
            NoCalendarConflicts(),
            lambda: None,
        )
        self.undo_service = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            None,
            self.units,
            None,
            self.revisions,
            profile_mutation_coordinator=threading.RLock(),
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.stage = SessionFocusBackfill(
            key_values=self.key_values,
            clock=lambda: NOW,
            future_units=lambda limit: self.units.list(limit, future_only=True),
            estimator=lambda: (
                lambda unit: estimate_planned_unit(unit, AthleteThresholds())
            ),
            update_unit=self.units.update,
            bump_planning_revision=self.revisions.bump,
            database_manager=lambda: self.manager,
            history_undo=lambda: self.undo_service,
            database_lock=threading.RLock(),
        )

    def create(self, **overrides: object) -> str:
        workout = {
            "date": "2026-11-10",
            "sport": "Run",
            "name": "Lockerer Lauf",
            "description": "- 40m 60%",
            "duration_minutes": 40,
            **overrides,
        }
        return self.units.create(workout)["id"]

    def payload(self, local_id: str) -> dict:
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
            ).fetchone()
        return json.loads(row["payload"])

    def sync_columns(self) -> list[tuple]:
        with self.manager.reader() as db:
            return [
                tuple(row.values())
                for row in db.execute(
                    "SELECT local_id, sync_dirty, sync_state, last_synced_at, "
                    "baseline_hash FROM planned_units ORDER BY local_id"
                )
            ]

    def history_count(self) -> int:
        with self.manager.reader() as db:
            return db.execute("SELECT COUNT(*) AS n FROM change_history").fetchone()[
                "n"
            ]

    def run_stage(self):
        with self.manager.unit_of_work() as db:
            return self.stage.run_batch(db)

    def state(self) -> dict:
        with self.manager.reader() as db:
            return json.loads(self.key_values.get(db, STATE_KEY))

    def test_unambiguous_values_are_stored_and_the_rest_is_left_alone(self) -> None:
        easy = self.create()
        contested = self.create(name="Schwelle und Intervalle")
        unknown = self.create(name="Lauf")
        stored = self.create(name="Lockerer Lauf", session_focus="long")
        past = self.create(date="2026-11-01")
        legs = self.create(
            sport="WeightTraining", name="Kniebeuge schwer", description=""
        )
        core = self.create(
            sport="WeightTraining",
            name="Core leicht",
            description="",
            session_focus="core",
        )
        swim = self.create(sport="Swim", name="Lockerer Lauf")
        before_sync = self.sync_columns()
        before_history = self.history_count()

        report = self.run_stage()

        self.assertTrue(report.done)
        self.assertEqual("easy", self.payload(easy)["session_focus"])
        self.assertNotIn("session_focus", self.payload(contested))
        self.assertNotIn("session_focus", self.payload(unknown))
        self.assertEqual("long", self.payload(stored)["session_focus"])
        self.assertNotIn("session_focus", self.payload(past))
        self.assertNotIn("session_focus", self.payload(swim))
        self.assertEqual(
            ("legs", "heavy"),
            (
                self.payload(legs)["session_focus"],
                self.payload(legs)["strength_intensity"],
            ),
        )
        self.assertEqual(
            ("core", "light"),
            (
                self.payload(core)["session_focus"],
                self.payload(core)["strength_intensity"],
            ),
        )
        # Never an exercise structure, and no provider state touched.
        self.assertNotIn("strength_structure", self.payload(legs))
        self.assertEqual(before_sync, self.sync_columns())
        # Change history: one row per filled unit (easy, legs, core).
        self.assertEqual(before_history + 3, self.history_count())
        state = self.state()
        self.assertEqual("complete", state["status"])
        self.assertEqual({"focus": 2, "intensity": 2, "undecided": 2}, state["counts"])
        with self.manager.reader() as db:
            summary = summarize_session_focus_backfill(self.key_values, db)
        self.assertEqual("complete", summary["status"])
        self.assertNotIn("changes", summary)

    def test_a_second_run_changes_nothing(self) -> None:
        self.create()
        self.run_stage()
        # A unit created later is not touched by the finished step either.
        later = self.create(name="Lockerer Ride", sport="Ride")
        history = self.history_count()
        revision = self.revision()

        report = self.run_stage()

        self.assertEqual((0, True), (report.items, report.done))
        self.assertEqual(history, self.history_count())
        self.assertEqual(revision, self.revision())
        self.assertNotIn("session_focus", self.payload(later))

    def test_undo_restores_every_unit_in_one_step(self) -> None:
        first = self.create()
        second = self.create(name="Lockerer Ride", sport="Ride")
        self.run_stage()
        self.assertEqual("easy", self.payload(first)["session_focus"])

        result = self.stage.undo()

        self.assertEqual(
            {"status": "undone", "restored": 2},
            {key: result[key] for key in ("status", "restored")},
        )
        for local_id in (first, second):
            self.assertNotIn("session_focus", self.payload(local_id))
        with self.assertRaises(AppError) as again:
            self.stage.undo()
        self.assertEqual(409, again.exception.status)

    def test_undo_is_all_or_nothing_when_a_unit_was_edited_since(self) -> None:
        first = self.create()
        second = self.create(name="Lockerer Ride", sport="Ride")
        self.run_stage()
        self.units.update(second, {"session_focus": "recovery"})

        with self.assertRaises(AppError):
            self.stage.undo()

        self.assertEqual("easy", self.payload(first)["session_focus"])
        self.assertEqual("recovery", self.payload(second)["session_focus"])
        self.assertNotIn("undone_at", self.state())

    def test_undo_without_a_run_or_changes_is_refused(self) -> None:
        with self.assertRaises(AppError):
            self.stage.undo()
        self.create(name="Lauf")
        self.run_stage()
        with self.assertRaises(AppError):
            self.stage.undo()

    def test_a_failed_run_is_marked_and_retried(self) -> None:
        self.create()
        with self.manager.unit_of_work() as db:
            self.stage.mark_failed(db)
        self.assertEqual("failed", self.state()["status"])

        self.assertTrue(self.run_stage().done)
        self.assertEqual("complete", self.state()["status"])

    def revision(self) -> int:
        with self.manager.reader() as db:
            return db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()["revision"]


class AssemblyTests(unittest.TestCase):
    def test_extra_stages_run_after_the_canonical_ones(self) -> None:
        stage = SessionFocusBackfill.__new__(SessionFocusBackfill)
        assembly = build_canonical_backfill(
            database=lambda: None,
            key_values=KeyValueRepository(lambda: NOW),
            zone_provider=lambda: None,
            maintenance_gate=MaintenanceGate(),
            clock=lambda: NOW,
            extra_followups=(stage,),
        )
        followups = assembly.worker._followups
        self.assertIs(stage, followups[-1])
        self.assertGreater(len(followups), 1)


if __name__ == "__main__":
    unittest.main()
