"""Temporary-SQLite tests for remote planned-unit reconciliation."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.planning import planned_units
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.sync.planned_units import RemotePlannedUnitReconciler

NOW = "2026-09-20T08:00:00+00:00"
TODAY = date(2026, 9, 20)


class RevisionSpy:
    def __init__(self, fail: bool = False):
        self.service = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        self.calls = 0
        self.fail = fail

    def bump(self, db: Any) -> None:
        self.calls += 1
        self.service.bump(db)
        if self.fail:
            raise RuntimeError("revision bump failed")


class CalendarConflictFake:
    def conflicts(
        self, _workout: dict[str, Any], _exclude_library_ids: Any
    ) -> list[Any]:
        return []


class InterleavingCursor:
    def __init__(self, row: Any):
        self.row = row

    def fetchone(self) -> Any:
        return self.row


class InterleavingConnection:
    def __init__(self, db: Any):
        self.db = db
        self.interleave = True

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        if self.interleave and "json_extract(payload, '$.remote_event_id')=?" in query:
            self.interleave = False
            row = self.db.execute(query, params).fetchone()
            payload = json.loads(row["payload"])
            payload["name"] = "Parallel local edit"
            payload["sync_status"] = "local"
            self.db.execute(
                "UPDATE planned_units SET payload=?, sync_dirty=1, sync_state='local', "
                "updated_at=? WHERE local_id=?",
                (json.dumps(payload, ensure_ascii=False), NOW, row["local_id"]),
            )
            return InterleavingCursor(row)
        return self.db.execute(query, params)


class InterleavingDatabaseManager:
    def __init__(self, manager: DatabaseManager):
        self.manager = manager

    @contextmanager
    def unit_of_work(self):
        with self.manager.unit_of_work() as db:
            yield InterleavingConnection(db)


class CorruptRowsCursor:
    def __init__(self, rows: list[Any]):
        self.rows = rows

    def fetchall(self) -> list[Any]:
        return self.rows


class CorruptRowConnection:
    def __init__(self, db: Any, local_id: str):
        self.db = db
        self.local_id = local_id

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        if "json_extract(payload, '$.remote_event_id') IS NOT NULL" in query:
            rows = self.db.execute(query, params).fetchall()
            corrupt = self.db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (self.local_id,)
            ).fetchone()
            return CorruptRowsCursor([*rows, corrupt])
        return self.db.execute(query, params)


class CorruptRowDatabaseManager:
    def __init__(self, manager: DatabaseManager, local_id: str):
        self.manager = manager
        self.local_id = local_id

    @contextmanager
    def unit_of_work(self):
        with self.manager.unit_of_work() as db:
            yield CorruptRowConnection(db, self.local_id)


class RemotePlannedUnitReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "planned-units.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        self.revision = RevisionSpy()
        self.service = PlannedUnitService(
            self.manager,
            self.revision,
            lambda: NOW,
            lambda: TODAY,
            uuid.uuid4,
            lambda value: value,
            CalendarConflictFake(),
            lambda: None,
        )
        self.reconciler = self.make_reconciler()

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def make_reconciler(self, manager: Any = None, revision: Any = None):
        return RemotePlannedUnitReconciler(
            manager or self.manager,
            self.service,
            revision or self.revision,
            lambda: NOW,
            lambda: TODAY,
        )

    @staticmethod
    def event(remote_id: str, day: str, **overrides: Any) -> dict[str, Any]:
        return {
            "id": remote_id,
            "external_id": f"intervals-{remote_id}",
            "category": "WORKOUT",
            "type": "Ride",
            "name": f"Remote {remote_id}",
            "start_date_local": f"{day}T07:00:00",
            "moving_time": 1800,
            **overrides,
        }

    def row(self, remote_id: str) -> dict[str, Any]:
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT * FROM planned_units WHERE "
                "json_extract(payload, '$.remote_event_id')=?",
                (remote_id,),
            ).fetchone()
        return row

    def payload(self, remote_id: str) -> dict[str, Any]:
        return json.loads(self.row(remote_id)["payload"])

    def planning_revision(self) -> int:
        with self.manager.reader() as db:
            return self.revision.service.read(db)

    def set_payload(
        self, remote_id: str, *, state: str, dirty: int, **values: Any
    ) -> None:
        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT local_id, payload FROM planned_units WHERE "
                "json_extract(payload, '$.remote_event_id')=?",
                (remote_id,),
            ).fetchone()
            payload = json.loads(row["payload"])
            payload.update(values)
            payload["sync_status"] = state
            db.execute(
                "UPDATE planned_units SET payload=?, sync_state=?, sync_dirty=?, updated_at=? "
                "WHERE local_id=?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    state,
                    dirty,
                    NOW,
                    row["local_id"],
                ),
            )

    def test_import_is_normalized_idempotent_and_stores_remote_baseline(self) -> None:
        event = self.event("one", "2026-09-21", name="Easy Ride")

        first = self.reconciler.reconcile([event])
        first_row = self.row("one")
        second = self.reconciler.reconcile([event])

        self.assertEqual(first, {"imported": 1, "updated": 0, "conflicts": 0})
        self.assertEqual(second, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.payload("one")["name"], "Easy Ride")
        self.assertEqual(first_row["sync_state"], "synced")
        self.assertEqual(first_row["sync_dirty"], 0)
        self.assertEqual(
            first_row["baseline_hash"],
            planned_units.planned_unit_payload_hash(self.payload("one")),
        )
        self.assertEqual(first_row["last_synced_at"], NOW)
        self.assertEqual(self.planning_revision(), 1)
        self.assertEqual(self.revision.calls, 1)

    def test_clean_remote_update_preserves_local_metadata(self) -> None:
        self.reconciler.reconcile([self.event("one", "2026-09-21")])
        self.set_payload(
            "one",
            state="synced",
            dirty=0,
            plan_id="plan-local",
            plan_name="Local plan",
            rationale="Coach rationale",
            archived=True,
            private_calendar_adjustment={"reason": "private"},
        )

        result = self.reconciler.reconcile(
            [self.event("one", "2026-09-21", name="Updated remote")]
        )

        payload = self.payload("one")
        self.assertEqual(result, {"imported": 0, "updated": 1, "conflicts": 0})
        self.assertEqual(payload["name"], "Updated remote")
        self.assertEqual(payload["plan_id"], "plan-local")
        self.assertEqual(payload["plan_name"], "Local plan")
        self.assertEqual(payload["rationale"], "Coach rationale")
        self.assertTrue(payload["archived"])
        self.assertEqual(payload["private_calendar_adjustment"], {"reason": "private"})
        self.assertEqual(self.row("one")["sync_state"], "synced")
        self.assertEqual(self.revision.calls, 2)

    def test_dirty_local_edit_becomes_conflict_without_overwriting_payload(
        self,
    ) -> None:
        self.reconciler.reconcile([self.event("one", "2026-09-21")])
        self.set_payload("one", state="local", dirty=1, name="Local name")

        result = self.reconciler.reconcile(
            [self.event("one", "2026-09-21", name="Remote name")]
        )

        row = self.row("one")
        self.assertEqual(result, {"imported": 0, "updated": 0, "conflicts": 1})
        self.assertEqual(self.payload("one")["name"], "Local name")
        self.assertEqual(row["sync_state"], "conflict")
        self.assertEqual(row["sync_dirty"], 1)
        self.assertEqual(
            json.loads(row["sync_conflict"])["remote"]["name"], "Remote name"
        )

    def test_optimistic_row_equality_keeps_parallel_local_change(self) -> None:
        self.reconciler.reconcile([self.event("one", "2026-09-21")])
        interleaved = self.make_reconciler(InterleavingDatabaseManager(self.manager))

        result = interleaved.reconcile(
            [self.event("one", "2026-09-21", name="Remote update")]
        )

        row = self.row("one")
        self.assertEqual(result, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.payload("one")["name"], "Parallel local edit")
        self.assertEqual(row["sync_state"], "local")
        self.assertEqual(row["sync_dirty"], 1)
        self.assertEqual(self.revision.calls, 1)

    def test_missing_detection_is_bounded_and_marks_only_rows_inside_window(
        self,
    ) -> None:
        self.reconciler.reconcile(
            [
                self.event("seen", "2026-09-21"),
                self.event("missing-inside", "2026-09-22"),
                self.event("missing-outside", "2026-09-24"),
            ]
        )

        result = self.reconciler.reconcile(
            [self.event("seen", "2026-09-21")],
            calendar_start="2026-09-21",
            calendar_end="2026-09-22",
        )

        self.assertEqual(result, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.row("missing-inside")["sync_state"], "remote_missing")
        self.assertEqual(self.row("missing-inside")["sync_dirty"], 0)
        self.assertEqual(self.row("missing-outside")["sync_state"], "synced")
        self.assertEqual(self.revision.calls, 2)

    def test_out_of_window_missing_row_creates_no_tombstone(self) -> None:
        self.reconciler.reconcile(
            [self.event("seen", "2026-09-21"), self.event("later", "2026-09-24")]
        )
        before_revision = self.planning_revision()

        result = self.reconciler.reconcile(
            [self.event("seen", "2026-09-21")],
            calendar_start="2026-09-21",
            calendar_end="2026-09-22",
        )

        self.assertEqual(result, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.row("later")["sync_state"], "synced")
        self.assertEqual(self.planning_revision(), before_revision)
        self.assertEqual(self.revision.calls, 1)

    def test_missing_local_edit_becomes_conflict(self) -> None:
        self.reconciler.reconcile([self.event("one", "2026-09-21")])
        self.set_payload("one", state="sync_error", dirty=1, name="Local pending")

        result = self.reconciler.reconcile(
            [], calendar_start="2026-09-21", calendar_end="2026-09-21"
        )

        row = self.row("one")
        self.assertEqual(result, {"imported": 0, "updated": 0, "conflicts": 1})
        self.assertEqual(row["sync_state"], "conflict")
        self.assertEqual(row["sync_dirty"], 1)
        self.assertEqual(json.loads(row["sync_conflict"])["type"], "remote_missing")
        self.assertEqual(self.payload("one")["name"], "Local pending")

    def test_invalid_and_non_workout_events_are_skipped(self) -> None:
        result = self.reconciler.reconcile(
            [
                None,
                {**self.event("not-workout", "2026-09-21"), "category": "ACTIVITY"},
                {**self.event("bad-date", "2026-09-21"), "start_date_local": "bad"},
                {**self.event("past", "2026-09-19")},
                {"category": "WORKOUT", "start_date_local": "2026-09-21T08:00:00"},
            ],
            calendar_start="2026-09-21",
            calendar_end="2026-09-21",
        )

        self.assertEqual(result, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.revision.calls, 0)
        with self.manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT count(*) AS count FROM planned_units").fetchone()[
                    "count"
                ],
                0,
            )

    def test_many_changes_bump_revision_once(self) -> None:
        self.reconciler.reconcile(
            [
                self.event("update", "2026-09-21"),
                self.event("missing", "2026-09-22"),
            ]
        )
        self.set_payload("update", state="synced", dirty=0)

        result = self.reconciler.reconcile(
            [self.event("update", "2026-09-21", name="Changed")],
            calendar_start="2026-09-21",
            calendar_end="2026-09-22",
        )

        self.assertEqual(result, {"imported": 0, "updated": 1, "conflicts": 0})
        self.assertEqual(self.row("missing")["sync_state"], "remote_missing")
        self.assertEqual(self.revision.calls, 2)
        self.assertEqual(self.planning_revision(), 2)

    def test_revision_failure_rolls_back_import_and_revision(self) -> None:
        failing_revision = RevisionSpy(fail=True)
        reconciler = self.make_reconciler(revision=failing_revision)

        with self.assertRaisesRegex(RuntimeError, "revision bump failed"):
            reconciler.reconcile([self.event("one", "2026-09-21")])

        with self.manager.reader() as db:
            count = db.execute(
                "SELECT count(*) AS count FROM planned_units"
            ).fetchone()["count"]
        self.assertEqual(count, 0)
        self.assertEqual(self.planning_revision(), 0)
        self.assertEqual(failing_revision.calls, 1)

    def test_non_object_local_payload_rolls_back_import_and_revision(self) -> None:
        local_id = "corrupt-local-unit"
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, external_id, payload, sync_dirty, "
                "sync_state, sync_conflict, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 0, 'synced', '', ?, ?)",
                (local_id, local_id, "corrupt-external", "[]", NOW, NOW),
            )
        reconciler = self.make_reconciler(
            CorruptRowDatabaseManager(self.manager, local_id)
        )

        with self.assertRaises(AttributeError):
            reconciler.reconcile([self.event("new-import", "2026-09-21")])

        with self.manager.reader() as db:
            imported = db.execute(
                "SELECT count(*) AS count FROM planned_units WHERE "
                "json_extract(payload, '$.remote_event_id')='new-import'"
            ).fetchone()["count"]
            corrupt = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
            ).fetchone()
        self.assertEqual(imported, 0)
        self.assertEqual(corrupt["payload"], "[]")
        self.assertEqual(self.planning_revision(), 0)
        self.assertEqual(self.revision.calls, 0)


if __name__ == "__main__":
    unittest.main()
