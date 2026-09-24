import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import PlanningStateRepository
from backend.errors import AppError
from backend.planning.state_service import StructuredTrainingStateService


class _ListService:
    def __init__(self, result, record_read):
        self.result = result
        self.record_read = record_read
        self.calls = []

    def list(self, *args):
        self.record_read()
        self.calls.append(args)
        return self.result


class _TrackingManager:
    def __init__(self, manager):
        self.manager = manager
        self.active = False

    @contextmanager
    def unit_of_work(self):
        with self.manager.unit_of_work() as db:
            self.active = True
            try:
                yield db
            finally:
                self.active = False


class StructuredTrainingStateServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temp_dir.name) / "state.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 4, 'now')"
            )
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, sync_state TEXT, payload TEXT)"
            )
            db.execute(
                "CREATE TABLE workout_library (local_id TEXT PRIMARY KEY, sync_state TEXT, payload TEXT, updated_at TEXT)"
            )
            self._insert_planned(db, "later", "2026-09-22", "B")
            self._insert_planned(db, "first", "2026-09-21", "A")
            self._insert_planned(db, "inactive", "2026-09-23", "C", archived=True)
            self._insert_planned(db, "deleted", "2026-09-24", "D", local_deleted=True)
            db.execute(
                "INSERT INTO workout_library(local_id, sync_state, payload, updated_at) VALUES (?, ?, ?, ?)",
                (
                    "template",
                    "local",
                    json.dumps({"name": "Easy template", "sport": "Run"}),
                    "2026-09-20T10:00:00+00:00",
                ),
            )

        self.tracking_manager = _TrackingManager(self.manager)
        self.dependencies_in_uow = []
        self.competitions = _ListService(
            [{"id": "competition"}], self._record_dependency_read
        )
        self.training_plans = _ListService(
            [{"id": "training-plan"}], self._record_dependency_read
        )
        self.artifacts = [{"id": "artifact"}]
        self.jobs = [{"id": "job"}]
        self.service = StructuredTrainingStateService(
            self.tracking_manager,
            PlanningStateRepository(),
            self.competitions,
            self.training_plans,
            lambda: self._dependency_result(self.artifacts),
            lambda: self._dependency_result(self.jobs),
            lambda: date(2026, 9, 20),
        )

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _insert_planned(db, local_id, plan_date, name, **flags):
        payload = {"date": plan_date, "name": name, "sport": "Run", **flags}
        db.execute(
            "INSERT INTO planned_units(local_id, sync_state, payload) VALUES (?, ?, ?)",
            (local_id, "local", json.dumps(payload)),
        )

    def _record_dependency_read(self):
        self.dependencies_in_uow.append(self.tracking_manager.active)

    def _dependency_result(self, result):
        self._record_dependency_read()
        return result

    def test_read_returns_dependency_results_and_pages_in_query_order(self):
        first = self.service.read(limit=1)

        self.assertEqual(4, first["planning_revision"])
        self.assertEqual(self.artifacts, first["artifact_refs"])
        self.assertEqual([{"id": "competition"}], first["competitions"])
        self.assertEqual([{"id": "training-plan"}], first["training_plans"])
        self.assertEqual(self.jobs, first["jobs"])
        self.assertEqual((100,), self.training_plans.calls[0])
        self.assertEqual(
            ["first"], [item["local_id"] for item in first["planned_units"]]
        )
        self.assertTrue(first["planned_units_page"]["has_more"])

        second = self.service.read(
            limit=1, cursor=first["planned_units_page"]["next_cursor"]
        )

        self.assertEqual(
            ["later"], [item["local_id"] for item in second["planned_units"]]
        )
        self.assertFalse(second["planned_units_page"]["has_more"])
        self.assertIsNone(second["planned_units_page"]["next_cursor"])

    def test_injected_dependency_reads_happen_after_the_unit_of_work(self):
        self.service.read(limit=1)

        self.assertEqual([False, False, False, False], self.dependencies_in_uow)

    def test_invalid_cursor_is_a_400_with_existing_reason_and_message(self):
        with self.assertRaises(AppError) as error:
            self.service.read(cursor="not-a-cursor")

        self.assertEqual(400, error.exception.status)
        self.assertEqual("invalid_page_cursor", error.exception.reason)
        self.assertEqual("Ungueltiger Planungscursor.", error.exception.message)

    def test_revision_drift_rejects_next_page(self):
        first = self.service.read(limit=1)
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE planning_state SET revision=revision+1 WHERE id=1")

        with self.assertRaises(AppError) as error:
            self.service.read(
                limit=1, cursor=first["planned_units_page"]["next_cursor"]
            )

        self.assertEqual(409, error.exception.status)
        self.assertEqual("planning_revision_conflict", error.exception.reason)
        self.assertEqual(
            "Die Planung hat sich waehrend des Lesens geaendert. Alle Seiten erneut lesen.",
            error.exception.message,
        )

    def test_cursor_is_bound_to_include_inactive_and_today(self):
        first = self.service.read(include_inactive=True, limit=1)
        cursor = first["planned_units_page"]["next_cursor"]
        with self.assertRaises(AppError) as changed_filter:
            self.service.read(cursor=cursor, include_inactive=False, limit=1)
        self.assertEqual("planning_revision_conflict", changed_filter.exception.reason)

        next_day = date(2026, 9, 21)
        changed_today_service = StructuredTrainingStateService(
            self.manager,
            PlanningStateRepository(),
            self.competitions,
            self.training_plans,
            lambda: self.artifacts,
            lambda: self.jobs,
            lambda: next_day,
        )
        with self.assertRaises(AppError) as changed_today:
            changed_today_service.read(cursor=cursor, include_inactive=True, limit=1)
        self.assertEqual("planning_revision_conflict", changed_today.exception.reason)

    def test_target_projection_skips_corrupt_payload_and_limit_is_bounded(self):
        result = self.service.read(limit=10_000)

        self.assertEqual(366, result["planned_units_page"]["limit"])
        self.assertEqual(
            {"first", "later"}, {item["local_id"] for item in result["planned_units"]}
        )
        self.assertEqual(
            ["template"], [item["local_id"] for item in result["training_templates"]]
        )
        self.assertIsNone(
            self.service._target_ref(
                {"local_id": "broken", "payload": "{broken"}, planned=True
            )
        )

    def test_include_inactive_returns_archived_and_local_deleted_rows(self):
        result = self.service.read(include_inactive=True)

        self.assertEqual(
            {"first", "later", "inactive", "deleted"},
            {item["local_id"] for item in result["planned_units"]},
        )

    def test_today_filter_excludes_past_rows(self):
        with self.manager.unit_of_work() as db:
            self._insert_planned(db, "past", "2026-09-19", "Past")

        result = self.service.read()

        self.assertNotIn("past", {item["local_id"] for item in result["planned_units"]})


if __name__ == "__main__":
    unittest.main()
