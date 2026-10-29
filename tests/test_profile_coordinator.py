"""Synthetic persistence checks for the profile mutation coordinator."""

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.athlete.context import AthleteContextService
from backend.athlete.profile import ProfileService, normalize_profile
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.structured_tool_round import CoachStructuredToolRoundService
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.turn_undo import CoachTurnUndoService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.http_api.athlete_put import AthletePutRoutes
from backend.sync.garmin_profile_body_export import GarminProfileBodyExport


class ProfileCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.tmp.name) / "profile.db", sqlite3, row_factory=row_factory
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.coordinator = threading.RLock()
        self.database_lock = threading.RLock()
        self.kv = KeyValueRepository(lambda: "2026-10-29T12:00:00+00:00")
        self.repository = ProfileRepository(self.kv)
        self.profile = ProfileService(
            self.manager,
            self.repository,
            self.kv,
            on_location_changed=lambda *args, **kwargs: None,
            mutation_coordinator=self.coordinator,
        )
        self.history = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, self.repository),
            self.profile,
            None,
            None,
            None,
            None,
            None,
            profile_mutation_coordinator=self.coordinator,
        )

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def change(self):
        with self.manager.reader() as db:
            return dict(
                db.execute(
                    "SELECT id, after_hash FROM change_history WHERE entity_type='profile' ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
            )

    def assert_waits_without_blocking_other_writes(self, operation):
        started, done = threading.Event(), threading.Event()
        errors = []

        def run():
            started.set()
            try:
                operation()
            except Exception as exc:  # noqa: BLE001 - propagate worker failures to the test thread
                errors.append(exc)
            finally:
                done.set()

        entered, release = threading.Event(), threading.Event()
        saved = {"weight_kg": "75", "body_fat_pct": "15", "timezone": "UTC"}
        export_profile = Mock(mutation_coordinator=self.coordinator)
        export_profile.get.return_value = saved
        export_profile.revision.return_value = "synthetic-revision"
        client = Mock()

        def upload(**_kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("synthetic")
            return {
                "detailedImportResult": {
                    "successes": [{"id": "synthetic"}],
                    "failures": [],
                }
            }

        client.add_body_composition.side_effect = upload
        reader = Mock()
        reader.configured.return_value = True
        reader._authenticated_client.return_value = (client, "synthetic")
        fixture = Mock()
        fixture.path.return_value = None
        exporter = GarminProfileBodyExport(export_profile, reader, fixture, None)
        results = []
        export_thread = threading.Thread(
            target=lambda: results.append(exporter.export(saved, "synthetic-revision"))
        )
        export_thread.start()
        self.assertTrue(entered.wait(2))
        thread = threading.Thread(target=run)
        try:
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(done.wait(0.15))
            with self.manager.unit_of_work() as db:
                self.kv.set(db, "synthetic_unrelated", "written")
        finally:
            release.set()
            export_thread.join(5)
            thread.join(5)
        self.assertEqual(results, ["success"])
        self.assertTrue(done.is_set())
        self.assertEqual(errors, [])
        with self.manager.reader() as db:
            self.assertEqual(self.kv.get(db, "synthetic_unrelated"), "written")

    def test_patch_context_and_direct_coach_wait_and_persist(self):
        self.assert_waits_without_blocking_other_writes(
            lambda: self.profile.patch({"name": "First"})
        )
        competition = Mock()
        competition.list.return_value = []
        context = AthleteContextService(
            self.manager,
            self.profile,
            competition,
            normalize_profile,
            lambda value: value,
            lambda: "2026-10-29",
            lambda: "synthetic",
        )
        self.assert_waits_without_blocking_other_writes(
            lambda: context.save({"name": "Second"}, [])
        )
        coach = CoachProfileUpdateService(
            self.profile, self.manager, self.database_lock
        )
        intent = {
            "operation": "update_profile",
            "target_system": "local",
            "authorization_scope": ["local_profile"],
        }
        self.assert_waits_without_blocking_other_writes(
            lambda: coach.apply(
                {
                    "changes": [
                        {"field": "name", "expected_value": "Second", "value": "Third"}
                    ]
                },
                intent,
            )
        )
        self.assertEqual(self.profile.get()["name"], "Third")

    def test_http_profile_and_context_wait_before_database_lock(self):
        competition = Mock()
        competition.list.return_value = []
        context = AthleteContextService(
            self.manager,
            self.profile,
            competition,
            normalize_profile,
            lambda value: value,
            lambda: "2026-10-29",
            lambda: "synthetic",
        )
        attempted = threading.Event()
        lock = self.coordinator

        class ObservableCoordinator:
            def __enter__(self):
                attempted.set()
                lock.acquire()
                return self

            def __exit__(self, *args):
                lock.release()

        self.profile.mutation_coordinator = ObservableCoordinator()
        routes = AthletePutRoutes(
            lambda: context, lambda: self.profile, self.database_lock
        )
        for path, payload, expected in (
            ("/api/profile", {"name": "HTTP"}, "HTTP"),
            (
                "/api/athlete-context",
                {"profile": {"name": "Context"}, "competitions": []},
                "Context",
            ),
        ):
            with self.subTest(path=path):
                attempted.clear()
                handler = Mock()
                handler.read_json.return_value = payload
                errors = []

                def request(handler=handler, path=path, errors=errors):
                    try:
                        routes.handle(handler, path)
                    except Exception as exc:  # noqa: BLE001 - report thread failures
                        errors.append(exc)

                with lock:
                    thread = threading.Thread(target=request, daemon=True)
                    thread.start()
                    self.assertTrue(attempted.wait(2))
                    # Model an export holding the coordinator and persisting tokens.
                    acquired = self.database_lock.acquire(timeout=2)
                    try:
                        self.assertTrue(
                            acquired, "request acquired DB lock before coordinator"
                        )
                        with self.manager.unit_of_work() as db:
                            self.kv.set(db, "synthetic_token_write", "done")
                    finally:
                        if acquired:
                            self.database_lock.release()
                thread.join(5)
                self.assertFalse(thread.is_alive(), "request deadlocked")
                self.assertEqual(errors, [])
                handler.send_json.assert_called_once()
                self.assertEqual(self.profile.get()["name"], expected)

    def test_structured_round_persists_profile_and_receipt(self):
        coach = CoachProfileUpdateService(
            self.profile, self.manager, self.database_lock
        )
        intent = {
            "operation": "update_profile",
            "target_system": "local",
            "authorization_scope": ["local_profile"],
        }
        arguments = {
            "changes": [{"field": "name", "expected_value": "", "value": "Round"}]
        }
        dispatch = Mock()
        dispatch.execute.side_effect = lambda name, args, **kwargs: coach.apply(
            args, intent
        )
        execution = CoachStructuredToolExecutionService(
            self.manager,
            self.database_lock,
            self.kv,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            dispatch,
            self.coordinator,
        )
        jobs = Mock()
        jobs.turn_open.return_value = True
        round_service = CoachStructuredToolRoundService(
            lambda: self.manager,
            self.database_lock,
            Mock(),
            Mock(),
            execution,
            Mock(),
            Mock(),
            jobs,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            self.coordinator,
        )
        state = SimpleNamespace(
            context={},
            conversation_id="conversation",
            client_turn_id="turn",
            session_csrf_hash="synthetic",
            sync_job_ids=[],
            cancel_event=None,
            command_receipts=[],
        )
        metadata = {
            key: "synthetic"
            for key in (
                "call_id",
                "effect_key",
                "step_key",
                "repair_key",
                "scope_repair_key",
                "request_binding_key",
                "plan_effect_key",
            )
        }
        metadata.update(name="update_profile", arguments=arguments)
        self.assert_waits_without_blocking_other_writes(
            lambda: round_service._execute_and_record(metadata, {}, state)
        )
        self.assertEqual(self.profile.get()["name"], "Round")
        self.assertEqual(len(state.command_receipts[0]["changes"]), 1)
        jobs.merge_receipt.assert_called_once()

    def test_single_and_turn_undo_wait_and_restore(self):
        self.profile.patch({"name": "First"})
        change = self.change()
        self.assert_waits_without_blocking_other_writes(
            lambda: self.history.apply(
                {
                    "change_id": change["id"],
                    "expected_current_hash": change["after_hash"],
                }
            )
        )
        self.assertEqual(self.profile.get()["name"], "")
        self.profile.patch({"name": "Second"})
        change = self.change()
        receipt = {
            "change_summary": {"undoable": True},
            "command_receipts": [{"changes": [change]}],
        }
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands (id, client_turn_id, intent, target_system, status, receipt, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "id",
                    "turn",
                    "{}",
                    "local",
                    "completed",
                    json.dumps(receipt),
                    "now",
                    "now",
                ),
            )
        undo = CoachTurnUndoService(
            lambda: self.manager, self.database_lock, lambda: self.history
        )
        self.assert_waits_without_blocking_other_writes(lambda: undo.undo("turn"))
        self.assertEqual(self.profile.get()["name"], "")

    def test_exception_releases_coordinator(self):
        with self.assertRaises(AppError):
            self.profile.patch({"timezone": "invalid timezone"})
        self.assert_waits_without_blocking_other_writes(
            lambda: self.profile.patch({"name": "After"})
        )
        self.assertEqual(self.profile.get()["name"], "After")
