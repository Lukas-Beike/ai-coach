"""Isolated tests for local planned-unit creation and listing."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend import change_history
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import planned_units
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService

NOW = "2026-09-20T08:00:00+00:00"
TODAY = date(2026, 9, 20)


class CountingDatabaseManager:
    def __init__(self, manager):
        self.manager = manager
        self.unit_of_work_calls = 0

    def unit_of_work(self):
        self.unit_of_work_calls += 1
        return self.manager.unit_of_work()


class CommitFailingDatabaseManager:
    def __init__(self, manager):
        self.manager = manager

    @contextmanager
    def unit_of_work(self):
        with self.manager.unit_of_work() as db:
            yield db
            raise RuntimeError("commit unavailable")


class CalendarConflictFake:
    def __init__(self):
        self.calls = []
        self.results = []

    def conflicts(self, workout, exclude_library_ids):
        self.calls.append((workout, exclude_library_ids))
        return self.results


class StaticRowDb:
    def __init__(self, row):
        self.row = row

    def execute(self, _query, _params):
        return self

    def fetchone(self):
        return self.row


class PlannedUnitServiceTests(unittest.TestCase):
    def setUp(self):
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
        self.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.calendar_conflicts = CalendarConflictFake()
        self.events = []
        self.service = PlannedUnitService(
            self.manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value.replace("secret", "[REDACTED]"),
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )

    def tearDown(self):
        self.manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def workout(**overrides):
        return {
            "date": "2026-09-21",
            "sport": "Run",
            "name": "Äußerst lockerer Lauf",
            "description": "- 30m 60% locker",
            "duration_minutes": 30,
            **overrides,
        }

    def state(self):
        with self.manager.reader() as db:
            planned = db.execute(
                "SELECT id, local_id, external_id, payload, sync_dirty, sync_state, "
                "sync_error, sync_conflict, baseline_hash, last_synced_at, created_at, updated_at "
                "FROM planned_units"
            ).fetchall()
            history = db.execute(
                "SELECT entity_type, entity_id, action, source FROM change_history"
            ).fetchall()
            revision = db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()["revision"]
        return planned, history, revision

    def make_conflict(self, conflict=None, *, conflict_json=None, state="conflict"):
        self.service.create(self.workout())
        self.events.clear()
        if conflict_json is None:
            conflict_json = json.dumps(
                {"remote": None} if conflict is None else conflict
            )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state=?, sync_dirty=1, "
                "sync_error='stale error', sync_conflict=? WHERE local_id=?",
                (state, conflict_json, str(self.id)),
            )
        return str(self.id)

    def test_create_normalizes_and_inserts_local_sync_state(self):
        created = self.service.create(self.workout())

        planned, history, revision = self.state()
        self.assertEqual(created["id"], str(self.id))
        self.assertEqual(created["sport"], "Run")
        self.assertEqual(created["type"], "Run")
        self.assertEqual(created["duration_minutes"], 30)
        self.assertEqual(planned[0]["id"], str(self.id))
        self.assertEqual(planned[0]["local_id"], str(self.id))
        self.assertIsNone(planned[0]["external_id"])
        self.assertEqual(
            json.loads(planned[0]["payload"])["name"], "Äußerst lockerer Lauf"
        )
        self.assertIn("Äußerst lockerer Lauf", planned[0]["payload"])
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertIsNone(planned[0]["baseline_hash"])
        self.assertIsNone(planned[0]["last_synced_at"])
        self.assertEqual(planned[0]["created_at"], NOW)
        self.assertEqual(planned[0]["updated_at"], NOW)
        self.assertEqual(
            [
                (row["entity_type"], row["entity_id"], row["action"], row["source"])
                for row in history
            ],
            [("planned_unit", str(self.id), "create", "local")],
        )
        self.assertEqual(revision, 1)

    def test_insert_preserves_remote_sync_metadata_on_caller_transaction(self):
        entry = {
            **self.workout(),
            "id": str(self.id),
            "external_id": "remote-42",
        }
        with self.manager.unit_of_work() as db:
            stored = self.service.insert(
                db,
                entry,
                sync_dirty=0,
                sync_state="synced",
                sync_error="secret failure",
                baseline_hash="baseline",
                last_synced_at=NOW,
            )

        planned, history, revision = self.state()
        self.assertEqual(stored["sync_status"], "synced")
        self.assertEqual(planned[0]["sync_dirty"], 0)
        self.assertEqual(planned[0]["sync_state"], "synced")
        self.assertEqual(planned[0]["sync_error"], "[REDACTED] failure")
        self.assertEqual(planned[0]["baseline_hash"], "baseline")
        self.assertEqual(planned[0]["last_synced_at"], NOW)
        self.assertEqual(history, [])
        self.assertEqual(revision, 0)

    def test_audit_and_revision_are_written_with_the_planned_unit(self):
        with self.manager.unit_of_work() as db:
            self.service.create(self.workout(), db=db, change_source="coach")
            counts = tuple(
                db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()["COUNT(*)"]
                for table in ("planned_units", "change_history")
            )
            revision = db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()["revision"]

        self.assertEqual(counts, (1, 1))
        self.assertEqual(revision, 1)
        _, history, _ = self.state()
        self.assertEqual(history[0]["source"], "coach")

    def test_revision_can_be_skipped_without_skipping_audit(self):
        self.service.create(self.workout(), bump_planning_revision=False)

        planned, history, revision = self.state()
        self.assertEqual(len(planned), 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(revision, 0)

    def test_explicit_db_does_not_open_another_unit_of_work(self):
        manager = CountingDatabaseManager(self.manager)
        service = PlannedUnitService(
            manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value,
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )
        with self.manager.unit_of_work() as db:
            before = manager.unit_of_work_calls
            service.create(self.workout(), db=db)
            self.assertEqual(manager.unit_of_work_calls, before)

    def test_validation_failure_does_not_persist_anything(self):
        with self.assertRaises(AppError):
            self.service.create(self.workout(sport=" "))

        self.assertEqual(self.state(), ([], [], 0))

    def test_audit_failure_rolls_back_insert_and_revision(self):
        with (
            patch(
                "backend.planning.planned_unit_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.create(self.workout())

        self.assertEqual(self.state(), ([], [], 0))

    def test_revision_failure_rolls_back_insert_and_audit(self):
        with (
            patch.object(
                self.service._planning_revision_service,
                "bump",
                side_effect=RuntimeError("revision unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "revision unavailable"),
        ):
            self.service.create(self.workout())

        self.assertEqual(self.state(), ([], [], 0))

    def test_list_preserves_archive_future_and_limit_filters(self):
        self.service.create(self.workout(date="2026-09-19", name="Past"))
        self.id = uuid.UUID("22345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-20", name="Today"))
        self.id = uuid.UUID("32345678-1234-5678-1234-567812345678")
        self.service.create(
            self.workout(date="2026-09-21", name="Archived", archived=True)
        )
        self.id = uuid.UUID("42345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-22", name="Future"))

        visible = self.service.list()
        archived = self.service.list(include_archived=True)
        future = self.service.list(future_only=True)
        bounded = self.service.list(limit=1)
        bounded_with_archived = self.service.list(limit=1, include_archived=True)

        self.assertEqual(
            [item["name"] for item in visible], ["Past", "Today", "Future"]
        )
        self.assertEqual(
            [item["name"] for item in archived],
            ["Past", "Today", "Archived", "Future"],
        )
        self.assertEqual([item["name"] for item in future], ["Today", "Future"])
        self.assertEqual(len(bounded), 1)
        self.assertEqual(len(bounded_with_archived), 2)

    def test_list_for_coach_returns_canonical_future_local_units_with_limit(self):
        self.service.create(self.workout(date="2026-09-19", name="Past"))
        self.id = uuid.UUID("22345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-20", name="Today"))
        self.id = uuid.UUID("32345678-1234-5678-1234-567812345678")
        self.service.create(
            self.workout(date="2026-09-21", name="Archived", archived=True)
        )
        self.id = uuid.UUID("42345678-1234-5678-1234-567812345678")
        deleted = self.service.create(self.workout(date="2026-09-22", name="Deleted"))
        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?",
                (deleted["id"],),
            ).fetchone()
            payload = json.loads(row["payload"])
            payload["local_deleted"] = True
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (json.dumps(payload), deleted["id"]),
            )
        self.id = uuid.UUID("52345678-1234-5678-1234-567812345678")
        self.service.create(self.workout(date="2026-09-23", name="Future"))

        result = self.service.list_for_coach(limit=2)
        bounded = self.service.list_for_coach(limit=1)

        self.assertEqual(set(result), {"local", "intervals", "canonical", "source"})
        self.assertEqual(result["intervals"], [])
        self.assertEqual(result["source"], "local")
        self.assertEqual(
            [item["name"] for item in result["local"]], ["Today", "Future"]
        )
        self.assertEqual(len(result["canonical"]), 2)
        self.assertEqual(
            [item["name"] for item in result["canonical"]], ["Today", "Future"]
        )
        self.assertEqual(
            [item["date"] for item in result["canonical"]],
            ["2026-09-20", "2026-09-23"],
        )
        self.assertTrue(all(item["is_local"] for item in result["canonical"]))
        self.assertTrue(all(not item["is_remote"] for item in result["canonical"]))
        self.assertTrue(
            all(item["sync_source"] == "local" for item in result["canonical"])
        )
        self.assertEqual([item["name"] for item in bounded["canonical"]], ["Today"])

    def test_update_resets_local_sync_metadata_records_effective_before_and_bumps_revision(
        self,
    ):
        self.service.create(self.workout())
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='synced', sync_error='old error', "
                "sync_conflict='old conflict' WHERE local_id=?",
                (str(self.id),),
            )

        with patch(
            "backend.planning.planned_unit_service.change_history.record_change",
            wraps=change_history.record_change,
        ) as record_change:
            result = self.service.update(str(self.id), {"name": "Neuer Lauf"})

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result["status"], "local")
        self.assertEqual(payload["name"], "Neuer Lauf")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual(history[0]["action"], "create")
        self.assertEqual(history[1]["action"], "update")
        self.assertEqual(revision, 2)
        before = record_change.call_args.args[4]
        after = record_change.call_args.args[5]
        self.assertEqual(before["sync_status"], "synced")
        self.assertEqual(after["sync_status"], "local")
        self.assertEqual(self.events, ["changed"])

    def test_archive_and_restore_are_dirty_local_updates(self):
        self.service.create(self.workout())

        archived = self.service.update(str(self.id), {"action": "archive"})
        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertTrue(archived["library_entry"]["archived"])
        self.assertTrue(payload["archived"])
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual(history[-1]["action"], "update")
        self.assertEqual(revision, 2)

        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_error='stale', sync_conflict='stale' "
                "WHERE local_id=?",
                (str(self.id),),
            )
        restored = self.service.update(str(self.id), {"action": "restore"})

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertFalse(restored["library_entry"]["archived"])
        self.assertFalse(payload["archived"])
        self.assertFalse(payload.get("local_deleted", False))
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual(
            [row["action"] for row in history], ["create", "update", "update"]
        )
        self.assertEqual(revision, 3)

    def test_delete_keeps_audited_tombstone_and_does_not_physically_delete(self):
        self.service.create(self.workout())

        result = self.service.update(str(self.id), {"action": "delete"})

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result, {"status": "deleted", "local_id": str(self.id)})
        self.assertTrue(payload["local_deleted"])
        self.assertTrue(payload["archived"])
        self.assertEqual(payload["sync_status"], "local")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertEqual([row["action"] for row in history], ["create", "delete"])
        self.assertEqual(revision, 2)
        self.assertEqual(self.events, ["changed"])

    def test_missing_corrupt_and_undated_rows_keep_their_error_contracts(self):
        cases = (
            (
                uuid.UUID("52345678-1234-5678-1234-567812345678"),
                None,
                404,
                "Lokale Planung nicht gefunden.",
            ),
            (
                uuid.UUID("62345678-1234-5678-1234-567812345678"),
                "not-json",
                500,
                "Die lokale Planung ist beschädigt.",
            ),
            (
                uuid.UUID("72345678-1234-5678-1234-567812345678"),
                json.dumps({"sport": "Run"}),
                403,
                "Nur lokale geplante Einheiten können bearbeitet werden.",
            ),
        )
        for local_id, payload, status, message in cases:
            with self.subTest(status=status):
                row = (
                    None
                    if payload is None
                    else {
                        "payload": payload,
                        "external_id": None,
                        "sync_state": "local",
                    }
                )
                with self.assertRaises(AppError) as caught:
                    self.service.update(
                        str(local_id), {"name": "Changed"}, db=StaticRowDb(row)
                    )
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.message, message)
                self.assertEqual(self.events, [])

    def test_date_conflict_is_preserved_and_skip_flag_bypasses_conflict_service(self):
        self.service.create(self.workout())
        self.calendar_conflicts.results = [{"kind": "local_library"}]
        with self.assertRaises(AppError) as caught:
            self.service.update(str(self.id), {"date": "2026-09-23"})

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            caught.exception.message,
            "Die lokale Einheit kann wegen einer bestehenden Kalendereinheit nicht verschoben werden.",
        )
        self.assertEqual(
            self.calendar_conflicts.calls,
            [({"date": "2026-09-23"}, {str(self.id)})],
        )
        self.assertEqual(len(self.state()[0]), 1)
        self.assertEqual(self.state()[2], 1)
        self.assertEqual(self.events, [])

        self.calendar_conflicts.results = []
        result = self.service.update(
            str(self.id), {"date": "2026-09-23"}, skip_calendar_conflict=True
        )
        self.assertEqual(result["library_entry"]["date"], "2026-09-23")
        self.assertEqual(len(self.calendar_conflicts.calls), 1)
        self.assertEqual(self.state()[2], 2)

    def test_external_transaction_owns_commit_revision_and_event_publication(self):
        manager = CountingDatabaseManager(self.manager)
        service = PlannedUnitService(
            manager,
            PlanningRevisionService(PlanningStateRepository(), lambda: NOW),
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value,
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )
        service.create(self.workout())
        self.events.clear()

        before = manager.unit_of_work_calls
        with self.manager.unit_of_work() as db:
            service.update(
                str(self.id),
                {"name": "External ohne Revision"},
                bump_planning_revision=False,
                db=db,
            )
            self.assertEqual(manager.unit_of_work_calls, before)
            self.assertEqual(
                db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()[
                    "revision"
                ],
                1,
            )
        self.assertEqual(self.events, [])

        with self.manager.unit_of_work() as db:
            service.update(str(self.id), {"name": "External mit Revision"}, db=db)
            self.assertEqual(
                db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()[
                    "revision"
                ],
                2,
            )
        self.assertEqual(self.events, [])
        self.assertEqual(
            json.loads(self.state()[0][0]["payload"])["name"], "External mit Revision"
        )

    def test_history_and_revision_failures_roll_back_and_do_not_publish(self):
        self.service.create(self.workout())
        self.events.clear()
        before = self.state()
        with (
            patch(
                "backend.planning.planned_unit_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.update(str(self.id), {"name": "Not committed"})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

        with (
            patch.object(
                self.service._planning_revision_service,
                "bump",
                side_effect=RuntimeError("revision unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "revision unavailable"),
        ):
            self.service.update(str(self.id), {"name": "Also not committed"})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

    def test_event_callback_runs_once_after_own_transaction_commits(self):
        self.service.create(self.workout())
        observations = []

        def publish_after_commit():
            with self.manager.reader() as db:
                payload = db.execute(
                    "SELECT payload FROM planned_units WHERE local_id=?",
                    (str(self.id),),
                ).fetchone()["payload"]
            observations.append(json.loads(payload)["name"])

        self.service._publish_change = publish_after_commit
        self.service.update(str(self.id), {"name": "Committed before event"})

        self.assertEqual(observations, ["Committed before event"])

    def test_failed_own_commit_does_not_publish_event(self):
        self.service.create(self.workout())
        self.events.clear()
        service = PlannedUnitService(
            CommitFailingDatabaseManager(self.manager),
            self.service._planning_revision_service,
            lambda: NOW,
            lambda: TODAY,
            lambda: self.id,
            lambda value: value,
            self.calendar_conflicts,
            lambda: self.events.append("changed"),
        )
        before = self.state()

        with self.assertRaisesRegex(RuntimeError, "commit unavailable"):
            service.update(str(self.id), {"name": "Not committed"})

        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

    def test_resolve_conflict_keep_local_resets_sync_metadata_and_bumps_once(self):
        local_id = self.make_conflict({"remote": {"id": "ignored"}})

        result = self.service.resolve_conflict(local_id, "keep_local")

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["strategy"], "keep_local")
        self.assertEqual(set(result), {"status", "strategy", "planned_unit"})
        self.assertEqual(result["planned_unit"]["name"], "Äußerst lockerer Lauf")
        self.assertEqual(payload["sync_status"], "local")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertEqual([row["action"] for row in history], ["create"])
        self.assertEqual(revision, 2)
        self.assertEqual(self.events, [])
        self.assertEqual(self.calendar_conflicts.calls, [])

    def test_resolve_conflict_adopts_normalized_remote_and_metadata(self):
        remote = {
            "id": "remote-42",
            "external_id": "provider-workout-42",
            "category": "WORKOUT",
            "start_date_local": "2026-09-22T07:30:00+02:00",
            "type": "Ride",
            "name": "Remote Fahrt",
            "description": "- 30m Z2",
            "moving_time": 1800,
        }
        local_id = self.make_conflict({"remote": remote})

        result = self.service.resolve_conflict(local_id, "adopt_remote")

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result["strategy"], "adopt_remote")
        self.assertEqual(result["planned_unit"]["id"], local_id)
        self.assertEqual(result["planned_unit"]["name"], "Remote Fahrt")
        self.assertEqual(payload["sync_status"], "synced")
        self.assertEqual(planned[0]["external_id"], "provider-workout-42")
        self.assertEqual(planned[0]["sync_dirty"], 0)
        self.assertEqual(planned[0]["sync_state"], "synced")
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertTrue(planned[0]["baseline_hash"])
        self.assertEqual(
            planned[0]["baseline_hash"],
            planned_units.planned_unit_payload_hash(payload),
        )
        self.assertEqual(planned[0]["last_synced_at"], NOW)
        self.assertEqual(planned[0]["updated_at"], NOW)
        self.assertEqual([row["action"] for row in history], ["create"])
        self.assertEqual(revision, 2)
        self.assertEqual(self.events, [])
        self.assertEqual(self.calendar_conflicts.calls, [])

    def test_resolve_conflict_adopts_remote_deletion_as_persistent_tombstone(self):
        local_id = self.make_conflict({"remote": None})

        result = self.service.resolve_conflict(local_id, "adopt_remote")

        planned, history, revision = self.state()
        payload = json.loads(planned[0]["payload"])
        self.assertEqual(result["planned_unit"]["sync_status"], "remote_deleted")
        self.assertTrue(payload["local_deleted"])
        self.assertTrue(payload["archived"])
        self.assertEqual(payload["sync_status"], "remote_deleted")
        self.assertEqual(planned[0]["sync_state"], "remote_deleted")
        self.assertEqual(planned[0]["sync_dirty"], 0)
        self.assertEqual(planned[0]["sync_conflict"], "")
        self.assertIsNone(planned[0]["sync_error"])
        self.assertEqual([row["action"] for row in history], ["create"])
        self.assertEqual(revision, 2)
        self.assertEqual(self.events, [])

    def test_resolve_conflict_rejects_closed_and_missing_conflicts(self):
        self.make_conflict(state="local")
        with self.assertRaises(AppError) as closed:
            self.service.resolve_conflict(str(self.id), "keep_local")
        with self.assertRaises(AppError) as missing:
            self.service.resolve_conflict(
                "52345678-1234-5678-1234-567812345678", "keep_local"
            )

        for caught in (closed.exception, missing.exception):
            self.assertEqual(caught.status, 409)
            self.assertEqual(
                caught.message,
                "Für diese Planung liegt kein offener Synchronisierungskonflikt vor.",
            )
        self.assertEqual(self.state()[2], 1)
        self.assertEqual(self.events, [])

    def test_resolve_conflict_rejects_invalid_conflict_json(self):
        self.make_conflict(conflict_json="{invalid")

        with self.assertRaises(AppError) as caught:
            self.service.resolve_conflict(str(self.id), "keep_local")

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            caught.exception.message,
            "Der gespeicherte Synchronisierungskonflikt ist nicht mehr gültig.",
        )
        self.assertEqual(self.state()[2], 1)
        self.assertEqual(self.events, [])

    def test_non_object_conflict_is_treated_as_remote_deletion(self):
        self.make_conflict(conflict_json=json.dumps([{"remote": {"id": "ignored"}}]))

        result = self.service.resolve_conflict(str(self.id), "adopt_remote")

        payload = json.loads(self.state()[0][0]["payload"])
        self.assertEqual(result["planned_unit"]["sync_status"], "remote_deleted")
        self.assertTrue(payload["local_deleted"])
        self.assertTrue(payload["archived"])

    def test_resolve_conflict_rejects_invalid_remote_event(self):
        self.make_conflict({"remote": {"id": "race", "category": "RACE"}})

        with self.assertRaises(AppError) as caught:
            self.service.resolve_conflict(str(self.id), "adopt_remote")

        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(
            caught.exception.message,
            "Das Remote-Event kann nicht übernommen werden.",
        )
        self.assertEqual(self.state()[2], 1)
        self.assertEqual(self.events, [])

    def test_resolve_conflict_revision_failure_rolls_back_payload_and_metadata(self):
        local_id = self.make_conflict({"remote": None})
        before = self.state()

        with (
            patch.object(
                self.service._planning_revision_service,
                "bump",
                side_effect=RuntimeError("revision unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "revision unavailable"),
        ):
            self.service.resolve_conflict(local_id, "adopt_remote")

        self.assertEqual(self.state(), before)
        self.assertEqual(self.events, [])

    def test_resolve_conflict_reads_back_only_after_commit_and_has_no_side_effects(
        self,
    ):
        local_id = self.make_conflict({"remote": None})
        original_list = self.service.list
        observed = []

        def readback(limit=500, include_archived=False, *, future_only=False):
            with self.manager.reader() as db:
                observed.append(
                    db.execute(
                        "SELECT sync_state FROM planned_units WHERE local_id=?",
                        (local_id,),
                    ).fetchone()["sync_state"]
                )
            return original_list(limit, include_archived, future_only=future_only)

        self.service.list = readback
        with (
            patch("backend.providers.intervals.IntervalsApiClient.post") as post,
            patch("backend.providers.intervals.IntervalsApiClient.put") as put,
            patch("backend.providers.intervals.IntervalsApiClient.delete") as delete,
        ):
            result = self.service.resolve_conflict(local_id, "adopt_remote")

        self.assertEqual(observed, ["remote_deleted"])
        self.assertEqual(result["planned_unit"]["sync_status"], "remote_deleted")
        self.assertEqual(self.events, [])
        self.assertEqual(self.calendar_conflicts.calls, [])
        post.assert_not_called()
        put.assert_not_called()
        delete.assert_not_called()

    def test_restore_existing_in_transaction_restores_visibility_and_local_state(self):
        entity_id = str(self.id)
        entry = planned_units.normalize_planned_unit(
            self.workout(
                date="2026-09-23",
                start_date_local="2026-09-23T07:15:00",
                archived=True,
                local_deleted=True,
            ),
            local_id=entity_id,
            external_id="remote-42",
            sync_status="synced",
        )
        target = {"date": "2026-09-21", "name": "Wiederhergestellt"}
        target_before = dict(target)
        with self.manager.unit_of_work() as db:
            self.service.insert(
                db,
                entry,
                sync_dirty=0,
                sync_state="synced",
            )
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )
            restored = self.service.restore_in_transaction(
                db, entity_id, current, target, "delete"
            )

        planned, history, revision = self.state()
        stored = json.loads(planned[0]["payload"])
        self.assertEqual(restored, stored)
        self.assertEqual(stored["name"], "Wiederhergestellt")
        self.assertEqual(stored["date"], "2026-09-21")
        self.assertEqual(stored["start_date_local"], "2026-09-21T07:15:00")
        self.assertFalse(stored["archived"])
        self.assertFalse(stored["local_deleted"])
        self.assertEqual(stored["external_id"], "remote-42")
        self.assertEqual(planned[0]["sync_dirty"], 1)
        self.assertEqual(planned[0]["sync_state"], "local")
        self.assertEqual(target, target_before)
        self.assertEqual(history, [])
        self.assertEqual(revision, 0)
        self.assertEqual(self.events, [])

    def test_restore_in_transaction_recreates_and_physically_deletes(self):
        entity_id = str(self.id)
        target = self.workout(name="Gelöschte Einheit")
        with self.manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(
                db, entity_id, None, target, "delete"
            )
        self.assertEqual(restored["id"], entity_id)
        self.assertEqual(self.state()[0][0]["sync_state"], "local")

        with self.manager.unit_of_work() as db:
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )
            deleted = self.service.restore_in_transaction(
                db, entity_id, current, None, "create"
            )
        self.assertIsNone(deleted)
        self.assertEqual(self.state(), ([], [], 0))

    def test_restore_in_transaction_rejects_conflict_and_corrupt_payload(self):
        entity_id = str(self.id)
        entry = planned_units.normalize_planned_unit(
            self.workout(archived=True, local_deleted=True), local_id=entity_id
        )
        with self.manager.unit_of_work() as db:
            self.service.insert(db, entry)
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )

        self.calendar_conflicts.results = [{"id": "occupied"}]
        with self.manager.unit_of_work() as db, self.assertRaises(AppError) as conflict:
            self.service.restore_in_transaction(
                db, entity_id, current, {"archived": False}, "delete"
            )
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(conflict.exception.reason, "plan_date_conflict")

        with self.manager.unit_of_work() as db:
            corrupt = {**current, "payload": "["}
            with self.assertRaises(AppError) as invalid:
                self.service.restore_in_transaction(
                    db, entity_id, corrupt, {"name": "Alt"}, "update"
                )
        self.assertEqual(invalid.exception.status, 409)
        self.assertEqual(
            invalid.exception.message,
            "Die lokale Planung kann nicht wiederhergestellt werden.",
        )

    def test_restore_in_transaction_rolls_back_with_outer_unit_of_work(self):
        entity_id = str(self.id)
        entry = planned_units.normalize_planned_unit(
            self.workout(name="Vorher"), local_id=entity_id
        )
        with self.manager.unit_of_work() as db:
            self.service.insert(db, entry)

        with (
            self.assertRaisesRegex(RuntimeError, "abort undo"),
            self.manager.unit_of_work() as db,
        ):
            current = dict(
                db.execute(
                    "SELECT * FROM planned_units WHERE local_id=?", (entity_id,)
                ).fetchone()
            )
            self.service.restore_in_transaction(
                db, entity_id, current, {"name": "Nachher"}, "update"
            )
            raise RuntimeError("abort undo")

        stored = json.loads(self.state()[0][0]["payload"])
        self.assertEqual(stored["name"], "Vorher")
        self.assertEqual(self.state()[1:], ([], 0))


if __name__ == "__main__":
    unittest.main()
