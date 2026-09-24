from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.errors import CORRUPT_LIBRARY_ERROR, INVALID_LIBRARY_ID_ERROR, AppError
from backend.sync.library import (
    WorkoutLibraryRefreshService,
    WorkoutLibraryRemoteReconciler,
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
    workout_library_sync_guard,
    workout_library_sync_running,
)

NOW = "2026-09-20T12:00:00+00:00"
LIBRARY_ID = "12345678-1234-5678-1234-567812345678"


class TestRedactor:
    def __init__(self):
        self.calls = []
        self.output = None

    def redact_text(self, text):
        self.calls.append(text)
        return self.output if self.output is not None else f"redacted:{text}"


class CountingSQLite:
    connect_calls = 0

    @classmethod
    def connect(cls, *args, **kwargs):
        cls.connect_calls += 1
        return sqlite3.connect(*args, **kwargs)


class WorkoutLibrarySyncStateServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.redactor = TestRedactor()
        self.service = WorkoutLibrarySyncStateService(
            self.database_manager,
            self.redactor,
            KeyValueRepository(lambda: NOW),
            lambda: NOW,
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE workout_library (id TEXT NOT NULL, local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                "sync_error TEXT, last_synced_at TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL)"
            )

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def _payload(value):
        return (
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )

    def add_library(
        self,
        local_id,
        *,
        state="local",
        external_id=None,
        payload="{}",
        dirty=1,
        error=None,
    ):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, external_id, payload, sync_dirty, "
                "sync_state, sync_error, last_synced_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"workout-{local_id}",
                    local_id,
                    external_id,
                    self._payload(payload),
                    dirty,
                    state,
                    error,
                    None,
                    "before",
                ),
            )

    def add_planned(
        self,
        local_id,
        *,
        state="local",
        external_id=None,
        payload="{}",
        dirty=1,
    ):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(local_id, external_id, payload, sync_dirty, sync_state) "
                "VALUES (?, ?, ?, ?, ?)",
                (local_id, external_id, self._payload(payload), dirty, state),
            )

    def library_row(self, local_id):
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT * FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()

    def test_request_unit_of_work_is_reused_by_preview_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            CountingSQLite.connect_calls = 0
            manager = DatabaseManager(
                Path(directory) / "request-scope.db",
                CountingSQLite,
                row_factory=row_factory,
            )
            service = WorkoutLibrarySyncStateService(
                manager,
                self.redactor,
                KeyValueRepository(lambda: NOW),
                lambda: NOW,
            )
            try:
                with manager.unit_of_work() as db:
                    db.execute(
                        "CREATE TABLE workout_library (id TEXT NOT NULL, local_id TEXT PRIMARY KEY, external_id TEXT, "
                        "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                        "sync_error TEXT, last_synced_at TEXT, updated_at TEXT NOT NULL)"
                    )
                    db.execute(
                        "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, external_id TEXT, "
                        "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL)"
                    )
                    db.execute(
                        "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
                    )
                with manager.unit_of_work():
                    connected = CountingSQLite.connect_calls
                    service.preview()
                    service.summary()
                    self.assertEqual(CountingSQLite.connect_calls, connected)
            finally:
                manager.close()

    def test_load_for_sync_normalizes_uuid_and_preserves_non_object_json(self):
        self.add_library(LIBRARY_ID, payload={"name": "Strength"})

        normalized_id, row, workout = self.service.load_for_sync(LIBRARY_ID.upper())

        self.assertEqual(normalized_id, LIBRARY_ID)
        self.assertEqual(row["local_id"], LIBRARY_ID)
        self.assertEqual(workout, {"name": "Strength"})
        self.add_library("12345678-1234-5678-1234-567812345679", payload="[]")
        _, _, non_object = self.service.load_for_sync(
            "12345678-1234-5678-1234-567812345679"
        )
        self.assertEqual(non_object, [])

    def test_load_for_sync_reports_invalid_missing_and_corrupt_records(self):
        self.add_library(LIBRARY_ID, payload="{invalid")

        with self.assertRaises(AppError) as invalid:
            self.service.load_for_sync("not-a-uuid")
        self.assertEqual(
            (invalid.exception.status, invalid.exception.message),
            (400, INVALID_LIBRARY_ID_ERROR),
        )
        with self.assertRaises(AppError) as missing:
            self.service.load_for_sync("12345678-1234-5678-1234-567812345679")
        self.assertEqual(
            (missing.exception.status, missing.exception.message),
            (404, "Lokale Bibliothekseinheit nicht gefunden."),
        )
        with self.assertRaises(AppError) as corrupt:
            self.service.load_for_sync(LIBRARY_ID)
        self.assertEqual(
            (corrupt.exception.status, corrupt.exception.message),
            (500, CORRUPT_LIBRARY_ERROR),
        )

    def test_store_remote_identity_requires_id_and_preserves_inputs(self):
        local_workout = {"id": LIBRARY_ID, "name": "Strength"}
        remote_workout = {"id": "  remote-1  ", "type": "WeightTraining"}
        local_before = copy.deepcopy(local_workout)
        remote_before = copy.deepcopy(remote_workout)
        self.add_library(LIBRARY_ID, payload=local_workout)

        self.assertEqual(
            self.service.store_remote_identity(
                LIBRARY_ID, local_workout, remote_workout
            ),
            "remote-1",
        )
        stored = self.library_row(LIBRARY_ID)
        self.assertEqual(stored["external_id"], "remote-1")
        self.assertEqual(
            json.loads(stored["payload"]),
            {"id": LIBRARY_ID, "name": "Strength", "external_id": "remote-1"},
        )
        self.assertEqual(local_workout, local_before)
        self.assertEqual(remote_workout, remote_before)
        with self.assertRaises(AppError) as missing_id:
            self.service.store_remote_identity(LIBRARY_ID, local_workout, {})
        self.assertEqual(missing_id.exception.status, 502)
        self.assertEqual(
            missing_id.exception.message,
            "Die Bibliothekseinheit konnte nicht zu Intervals.icu übertragen werden.",
        )

    def test_finish_validates_and_updates_library_and_kv_atomically(self):
        local_workout = {
            "id": LIBRARY_ID,
            "name": "Strength",
            "sport": "WeightTraining",
            "description": "Three sets of ten.",
        }
        remote_workout = {
            "id": "remote-strength",
            "type": "WeightTraining",
            "name": "Strength",
            "description": "Three sets of ten.",
        }
        local_before = copy.deepcopy(local_workout)
        remote_before = copy.deepcopy(remote_workout)
        self.add_library(LIBRARY_ID, payload=local_workout, state="syncing")
        self.service.store_remote_identity(LIBRARY_ID, local_workout, remote_workout)

        synced = self.service.finish(
            LIBRARY_ID, "remote-strength", local_workout, remote_workout
        )

        row = self.library_row(LIBRARY_ID)
        self.assertEqual(row["external_id"], "remote-strength")
        self.assertEqual(row["sync_dirty"], 0)
        self.assertEqual(row["sync_state"], "synced")
        self.assertIsNone(row["sync_error"])
        self.assertEqual(row["last_synced_at"], NOW)
        self.assertEqual(row["updated_at"], NOW)
        self.assertEqual(json.loads(row["payload"]), synced)
        with self.database_manager.reader() as db:
            values = {
                row["key"]: row["value"]
                for row in db.execute("SELECT key, value FROM kv").fetchall()
            }
        self.assertEqual(
            values,
            {"last_library_sync_at": NOW, "last_library_sync_error": ""},
        )
        self.assertEqual(local_workout, local_before)
        self.assertEqual(remote_workout, remote_before)

    def test_validation_failure_keeps_new_remote_identity_for_retry(self):
        local_workout = {
            "id": LIBRARY_ID,
            "name": "Strength",
            "sport": "WeightTraining",
            "description": "Three sets of ten.",
        }
        invalid_remote = {
            "id": "remote-new",
            "type": "Run",
            "description": "Provider returned the wrong sport.",
        }
        self.add_library(LIBRARY_ID, payload=local_workout)

        external_id = self.service.store_remote_identity(
            LIBRARY_ID, local_workout, invalid_remote
        )
        with self.assertRaises(AppError) as validation:
            self.service.finish(LIBRARY_ID, external_id, local_workout, invalid_remote)

        row = self.library_row(LIBRARY_ID)
        self.assertEqual(validation.exception.status, 502)
        self.assertEqual(row["external_id"], "remote-new")
        self.assertEqual(json.loads(row["payload"])["external_id"], "remote-new")
        self.assertEqual(row["sync_state"], "local")
        self.assertEqual(row["sync_dirty"], 1)
        with self.database_manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM kv").fetchone()["count"], 0
            )

    def test_finish_failure_rolls_back_library_and_both_kv_changes(self):
        local_workout = {
            "id": LIBRARY_ID,
            "name": "Strength",
            "sport": "WeightTraining",
            "description": "Three sets of ten.",
        }
        remote_workout = {
            "id": "remote-strength",
            "type": "WeightTraining",
            "name": "Strength",
            "description": "Three sets of ten.",
        }
        raw_payload = json.dumps(local_workout)
        self.add_library(
            LIBRARY_ID,
            payload=raw_payload,
            external_id="remote-old",
            state="syncing",
            dirty=1,
            error="prior error",
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER fail_library_sync_error BEFORE INSERT ON kv "
                "WHEN NEW.key='last_library_sync_error' BEGIN "
                "SELECT RAISE(ABORT, 'forced rollback'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.service.finish(
                LIBRARY_ID, "remote-strength", local_workout, remote_workout
            )

        row = self.library_row(LIBRARY_ID)
        self.assertEqual(row["payload"], raw_payload)
        self.assertEqual(row["external_id"], "remote-old")
        self.assertEqual(row["sync_state"], "syncing")
        self.assertEqual(row["sync_dirty"], 1)
        self.assertEqual(row["sync_error"], "prior error")
        with self.database_manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM kv").fetchone()["count"], 0
            )

    def test_preview_categories_counts_order_hash_and_fingerprint(self):
        self.add_library("lib-new", payload={"name": "New"})
        self.add_library(
            "lib-changed", external_id="remote-changed", payload={"name": "Changed"}
        )
        self.add_library("lib-error", state="sync_error", payload="bad-json")
        self.add_library("lib-missing", state="remote_missing", external_id="gone")
        self.add_library("lib-conflict", state="conflict", external_id="conflict-id")
        self.add_library("lib-synced", state="synced")
        self.add_planned(
            "planned-local",
            payload={"date": " 2026-11-12T06:00:00", "name": "Planned"},
        )
        self.add_planned("planned-error", state="sync_error", external_id="plan-error")
        self.add_planned(
            "planned-missing", state="remote_missing", external_id="plan-gone"
        )
        self.add_planned(
            "planned-conflict", state="conflict", external_id="plan-conflict"
        )
        self.add_planned("planned-synced", state="synced")

        summary, entries, fingerprint = self.service.preview()
        repeated = self.service.preview()

        self.assertEqual(
            summary,
            {
                "new": 1,
                "changed": 1,
                "missing": 2,
                "error_retry": 1,
                "planned": 4,
                "conflict": 2,
            },
        )
        self.assertEqual(
            [entry["local_id"] for entry in entries],
            [
                "lib-changed",
                "lib-conflict",
                "lib-error",
                "lib-missing",
                "lib-new",
                "planned-conflict",
                "planned-error",
                "planned-local",
                "planned-missing",
            ],
        )
        self.assertEqual(
            [entry["category"] for entry in entries],
            [
                "changed",
                "conflict",
                "error_retry",
                "missing",
                "new",
                "conflict",
                "planned",
                "planned",
                "missing",
            ],
        )
        planned = next(
            entry for entry in entries if entry["local_id"] == "planned-local"
        )
        self.assertEqual(planned["entity"], "planned_unit")
        self.assertTrue(planned["syncs_calendar"])
        self.assertTrue(planned["has_remote_id"] is False)
        self.assertEqual(planned["planned_date"], "2026-11-12")
        self.assertEqual(
            planned["payload_hash"],
            hashlib.sha256(
                b'{"date": " 2026-11-12T06:00:00", "name": "Planned"}'
            ).hexdigest(),
        )
        lib_new = next(entry for entry in entries if entry["local_id"] == "lib-new")
        self.assertEqual(lib_new["entity"], "workout_library")
        self.assertFalse(lib_new["syncs_calendar"])
        self.assertEqual(lib_new["planned_date"], None)
        expected_fingerprint = hashlib.sha256(
            json.dumps(
                {"summary": summary, "entries": entries},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(fingerprint, expected_fingerprint)
        self.assertEqual((summary, entries, fingerprint), repeated)

    def test_update_handles_corrupt_payloads_dirty_rules_and_redaction_limit(self):
        self.add_library("bad-json", payload="not-json")
        self.add_library("non-object", payload="[]")
        self.add_library("preserve", payload={"name": "Run"})
        self.add_library("missing", payload={"name": "Gone"})
        self.redactor.output = "r" * 1200

        self.assertTrue(self.service.update("bad-json", "sync_error", "provider error"))
        self.assertTrue(self.service.update("non-object", "synced"))
        self.assertTrue(self.service.update("preserve", "remote_missing"))
        self.assertTrue(self.service.update("missing", "conflict"))

        bad = self.library_row("bad-json")
        self.assertEqual(json.loads(bad["payload"]), {"sync_status": "sync_error"})
        self.assertEqual(bad["sync_error"], "r" * 1000)
        self.assertEqual(bad["sync_dirty"], 1)
        self.assertEqual(bad["updated_at"], NOW)
        non_object = self.library_row("non-object")
        self.assertEqual(json.loads(non_object["payload"]), {"sync_status": "synced"})
        self.assertEqual(non_object["sync_dirty"], 0)
        self.assertIsNone(non_object["sync_error"])
        preserve = self.library_row("preserve")
        self.assertEqual(
            json.loads(preserve["payload"]),
            {"name": "Run", "sync_status": "remote_missing"},
        )
        self.assertEqual(preserve["sync_dirty"], 0)
        self.assertEqual(self.library_row("missing")["sync_dirty"], 1)
        self.assertEqual(self.redactor.calls, ["provider error"])
        self.assertFalse(self.service.update("absent", "sync_error", "failure"))

    def test_persist_calendar_identity_preserves_payload_and_trims_optional_external_id(
        self,
    ):
        original = {"name": "Template", "nested": {"keep": True}}
        event = {"id": 123, "external_id": "  calendar-1  "}
        original_before = copy.deepcopy(original)
        event_before = copy.deepcopy(event)
        self.add_library("identity", payload=original)

        self.assertTrue(self.service.persist_calendar_identity("identity", event))

        row = self.library_row("identity")
        self.assertEqual(
            json.loads(row["payload"]),
            {
                "name": "Template",
                "nested": {"keep": True},
                "remote_event_id": "123",
                "remote_event_external_id": "calendar-1",
            },
        )
        self.assertEqual(row["updated_at"], NOW)
        self.assertEqual(original, original_before)
        self.assertEqual(event, event_before)

        event_without_external_id = {"id": "calendar-2", "external_id": " "}
        self.assertTrue(
            self.service.persist_calendar_identity(
                "identity", event_without_external_id
            )
        )
        payload = json.loads(self.library_row("identity")["payload"])
        self.assertEqual(payload["remote_event_id"], "calendar-2")
        self.assertEqual(payload["remote_event_external_id"], "calendar-1")

    def test_persist_calendar_identity_returns_false_for_missing_or_non_object_payload(
        self,
    ):
        self.add_library("non-object", payload="[]")
        self.add_library("corrupt", payload="invalid-json")

        self.assertFalse(self.service.persist_calendar_identity("absent", {"id": 1}))
        self.assertFalse(
            self.service.persist_calendar_identity("non-object", {"id": 1})
        )
        self.assertTrue(self.service.persist_calendar_identity("corrupt", {"id": 2}))
        self.assertEqual(
            json.loads(self.library_row("corrupt")["payload"]), {"remote_event_id": "2"}
        )

    def test_summary_includes_library_and_planned_counts(self):
        for index in range(2):
            self.add_library(f"local-{index}", state="local")
        self.add_library("syncing", state="syncing")
        for index in range(3):
            self.add_library(f"synced-{index}", state="synced")
        self.add_library("error", state="sync_error")
        for index in range(2):
            self.add_library(f"missing-{index}", state="remote_missing")
        self.add_library("archived", state="archived")
        self.add_planned("p-local", state="local")
        for index in range(2):
            self.add_planned(f"p-error-{index}", state="sync_error")
        for index in range(3):
            self.add_planned(f"p-missing-{index}", state="remote_missing")
        for index in range(4):
            self.add_planned(f"p-conflict-{index}", state="conflict")
        for index in range(5):
            self.add_planned(f"p-synced-{index}", state="synced")

        self.assertEqual(
            self.service.summary(),
            {
                "local": 2,
                "syncing": 1,
                "synced": 3,
                "sync_error": 1,
                "remote_missing": 2,
                "archived": 1,
                "planned_local": 1,
                "planned_sync_error": 2,
                "planned_remote_missing": 3,
                "planned_conflict": 4,
                "planned_synced": 5,
                "planned_pending": 6,
                "planned_conflicts": 4,
            },
        )


class WorkoutLibrarySyncServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.redactor = TestRedactor()
        self.state_service = WorkoutLibrarySyncStateService(
            self.database_manager,
            self.redactor,
            KeyValueRepository(lambda: NOW),
            lambda: NOW,
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE workout_library (id TEXT NOT NULL, local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                "sync_error TEXT, last_synced_at TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL)"
            )
        self.config = Config(
            port=8090,
            openai_api_key="",
            openai_base_url="",
            openai_model="",
            gemini_api_key="",
            gemini_model="",
            ai_provider="",
            intervals_api_key="fake-key",
            intervals_athlete_id="0",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="x" * 12,
            secure_cookies=False,
            data_retention_days=-1,
        )
        self.client = Mock()
        self.service = self.new_service()

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def new_service(self, *, config=None, client=None, lock=None):
        kwargs = {"_lock": lock} if lock is not None else {}
        return WorkoutLibrarySyncService(
            config or self.config,
            lambda: client or self.client,
            self.state_service,
            **kwargs,
        )

    @staticmethod
    def workout(name="Workout"):
        return {
            "sport": "WeightTraining",
            "type": "WeightTraining",
            "name": name,
            "description": "Three sets of ten.",
            "duration_minutes": 30,
        }

    def add_entry(
        self,
        *,
        local_id=LIBRARY_ID,
        state="local",
        external_id=None,
        workout=None,
    ):
        local_workout = workout or self.workout()
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, external_id, payload, sync_dirty, "
                "sync_state, sync_error, last_synced_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, ?, NULL, NULL, ?)",
                (
                    f"workout-{local_id}",
                    local_id,
                    external_id,
                    json.dumps(local_workout),
                    state,
                    "before",
                ),
            )

    def library_row(self, local_id=LIBRARY_ID):
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT * FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()

    def test_sync_entry_updates_existing_remote_workout(self):
        self.add_entry(state="sync_error", external_id="remote-old")
        remote = {**self.workout(), "id": "ignored", "type": "WeightTraining"}
        self.client.update_library_workout.return_value = remote

        synced = self.service.sync_entry(LIBRARY_ID)

        self.client.update_library_workout.assert_called_once_with(
            "remote-old", self.workout()
        )
        self.client.get_workout_library.assert_not_called()
        self.client.create_library_workouts.assert_not_called()
        self.assertEqual(synced["external_id"], "remote-old")
        self.assertEqual(self.library_row()["sync_state"], "synced")

    def test_sync_entry_recovers_remote_missing_before_creating(self):
        self.add_entry(state="remote_missing", external_id="remote-gone")
        recovered = {**self.workout(), "id": "remote-recovered"}
        self.client.get_workout_library.return_value = [recovered]

        synced = self.service.sync_entry(LIBRARY_ID)

        self.client.get_workout_library.assert_called_once_with()
        self.client.create_library_workouts.assert_not_called()
        self.client.update_library_workout.assert_not_called()
        self.assertEqual(synced["external_id"], "remote-recovered")

    def test_sync_entry_creates_when_no_remote_match_exists(self):
        self.add_entry()
        created = {**self.workout(), "id": "remote-created"}
        self.client.get_workout_library.return_value = []
        self.client.create_library_workouts.return_value = [created]

        synced = self.service.sync_entry(LIBRARY_ID)

        self.client.get_workout_library.assert_called_once_with()
        self.client.create_library_workouts.assert_called_once_with([self.workout()])
        self.assertEqual(synced["external_id"], "remote-created")
        self.assertEqual(self.library_row()["sync_state"], "synced")

    def test_sync_entry_already_synced_is_idempotent(self):
        workout = {"sport": "Run", "description": "incomplete"}
        self.add_entry(state="synced", external_id="remote-already", workout=workout)

        synced = self.service.sync_entry(LIBRARY_ID)

        self.assertEqual(synced, workout)
        self.client.update_library_workout.assert_not_called()
        self.client.get_workout_library.assert_not_called()
        self.client.create_library_workouts.assert_not_called()

    def test_sync_entry_rejects_invalid_id_and_missing_api_key_before_provider(self):
        with self.assertRaises(AppError) as invalid:
            self.service.sync_entry("not-a-uuid")
        self.assertEqual(invalid.exception.status, 400)

        no_key_service = self.new_service(
            config=replace(self.config, intervals_api_key="")
        )
        with self.assertRaises(AppError) as missing_key:
            no_key_service.sync_entry(LIBRARY_ID)
        self.assertEqual(missing_key.exception.status, 503)
        self.client.update_library_workout.assert_not_called()
        self.client.get_workout_library.assert_not_called()
        self.client.create_library_workouts.assert_not_called()

    def test_remote_identity_is_persisted_before_result_validation(self):
        self.add_entry()
        invalid_remote = {**self.workout(), "id": "remote-created", "type": "Run"}
        self.client.get_workout_library.return_value = []
        self.client.create_library_workouts.return_value = [invalid_remote]

        with self.assertRaises(AppError) as raised:
            self.service.sync_entry(LIBRARY_ID)

        row = self.library_row()
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(row["external_id"], "remote-created")
        self.assertEqual(json.loads(row["payload"])["external_id"], "remote-created")
        self.assertEqual(row["sync_state"], "sync_error")
        self.assertEqual(row["sync_dirty"], 1)

    def test_sync_error_is_saved_redacted_and_reraised(self):
        self.add_entry()
        self.client.get_workout_library.side_effect = RuntimeError(
            "fake provider failure"
        )

        with self.assertRaisesRegex(RuntimeError, "fake provider failure"):
            self.service.sync_entry(LIBRARY_ID)

        row = self.library_row()
        self.assertEqual(row["sync_state"], "sync_error")
        self.assertEqual(row["sync_error"], "redacted:fake provider failure")
        self.assertEqual(self.redactor.calls, ["fake provider failure"])
        self.assertFalse(workout_library_sync_running())

    def test_guard_acquisition_is_visible_through_running_status(self):
        self.assertFalse(workout_library_sync_running())

        with workout_library_sync_guard():
            self.assertTrue(workout_library_sync_running())

        self.assertFalse(workout_library_sync_running())

    def test_sync_calendar_entry_skips_missing_date(self):
        self.assertIsNone(
            self.service.sync_calendar_entry(LIBRARY_ID, {"external_id": "remote-1"})
        )
        self.client.plan_library_workout.assert_not_called()

    def test_sync_calendar_entry_requires_external_id(self):
        with self.assertRaises(AppError) as raised:
            self.service.sync_calendar_entry(LIBRARY_ID, {"date": "2026-10-01"})

        self.assertEqual(raised.exception.status, 502)
        self.client.plan_library_workout.assert_not_called()

    def test_sync_calendar_entry_rejects_invalid_provider_response(self):
        self.add_entry()
        self.client.plan_library_workout.return_value = {"external_id": "remote-1"}

        with self.assertRaises(AppError) as raised:
            self.service.sync_calendar_entry(
                LIBRARY_ID,
                {"date": "2026-10-01T08:00:00", "external_id": "remote-1"},
            )

        self.assertEqual(raised.exception.status, 502)
        payload = json.loads(self.library_row()["payload"])
        self.assertNotIn("remote_event_id", payload)

    def test_sync_calendar_entry_persists_remote_calendar_identity(self):
        self.add_entry()
        event = {"id": 123, "external_id": "calendar-1"}
        workout = {
            **self.workout(),
            "date": "2026-10-01T08:00:00",
            "external_id": "remote-1",
        }
        self.client.plan_library_workout.return_value = event

        result = self.service.sync_calendar_entry(LIBRARY_ID, workout)

        self.client.plan_library_workout.assert_called_once_with(
            "remote-1", workout, "2026-10-01"
        )
        self.assertEqual(result, event)
        self.assertEqual(
            json.loads(self.library_row()["payload"])["remote_event_id"], "123"
        )

    def test_plan_remote_is_a_thin_provider_operation(self):
        event = {"id": "calendar-1"}
        self.client.plan_library_workout.return_value = event
        workout = self.workout()

        result = self.service.plan_remote("remote-1", workout, "2026-10-01")

        self.client.plan_library_workout.assert_called_once_with(
            "remote-1", workout, "2026-10-01"
        )
        self.assertIs(result, event)

    def test_default_lock_is_shared_between_service_instances(self):
        first_id = LIBRARY_ID
        second_id = "12345678-1234-5678-1234-567812345679"
        self.add_entry(local_id=first_id, workout=self.workout("First"))
        self.add_entry(local_id=second_id, workout=self.workout("Second"))
        first_entered = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()
        activity_lock = threading.Lock()
        active = 0
        max_active = 0

        def create(workouts):
            nonlocal active, max_active
            name = workouts[0]["name"]
            with activity_lock:
                active += 1
                max_active = max(max_active, active)
            self.assertTrue(workout_library_sync_running())
            if name == "First":
                first_entered.set()
                release_first.wait(timeout=2)
            else:
                second_entered.set()
            with activity_lock:
                active -= 1
            return [{"id": f"remote-{name.casefold()}", **workouts[0]}]

        self.client.get_workout_library.return_value = []
        self.client.create_library_workouts.side_effect = create
        second_service = self.new_service()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.service.sync_entry, first_id)
            self.assertTrue(first_entered.wait(timeout=1))
            second = executor.submit(second_service.sync_entry, second_id)
            try:
                self.assertFalse(second_entered.wait(timeout=0.1))
            finally:
                release_first.set()
            first.result(timeout=2)
            second.result(timeout=2)
        self.assertEqual(max_active, 1)
        self.assertFalse(workout_library_sync_running())


class WorkoutLibraryRemoteReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE workout_library (id TEXT PRIMARY KEY, local_id TEXT NOT NULL UNIQUE, "
                "external_id TEXT, payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL DEFAULT 1, "
                "sync_state TEXT NOT NULL DEFAULT 'local', sync_error TEXT, last_synced_at TEXT, "
                "updated_at TEXT NOT NULL)"
            )
        self.ids = iter(
            (
                "11111111-1111-4111-8111-111111111111",
                "22222222-2222-4222-8222-222222222222",
                "33333333-3333-4333-8333-333333333333",
            )
        )
        self.service = WorkoutLibraryRemoteReconciler(
            self.database_manager, lambda: NOW, lambda: next(self.ids)
        )

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def add_row(
        self,
        *,
        storage_id="storage-existing",
        local_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        external_id="remote-existing",
        payload=None,
        dirty=0,
        state="synced",
    ):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, external_id, payload, sync_dirty, "
                "sync_state, sync_error, last_synced_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    storage_id,
                    local_id,
                    external_id,
                    json.dumps(payload or {"name": "Old"}),
                    dirty,
                    state,
                    "previous-sync",
                    "before",
                ),
            )

    def rows(self):
        with self.database_manager.reader() as db:
            return db.execute("SELECT * FROM workout_library ORDER BY id").fetchall()

    @staticmethod
    def remote(name, **fields):
        return {"name": name, "type": "Run", "description": f"{name} plan", **fields}

    def test_import_and_update_preserve_identity_and_external_id_priority(self):
        imported = self.service.reconcile(
            [
                self.remote("New", id=" remote-one ", external_id="ignored"),
                self.remote("External ID fallback", external_id="remote-two"),
                self.remote("Skipped"),
            ]
        )

        self.assertEqual(len(imported), 2)
        self.assertEqual(imported[0]["external_id"], "remote-one")
        self.assertEqual(imported[0]["id"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(imported[1]["external_id"], "remote-two")
        self.assertEqual(imported[1]["id"], "22222222-2222-4222-8222-222222222222")
        original_row = self.rows()[0]
        self.assertEqual(original_row["local_id"], imported[0]["id"])
        self.assertEqual(original_row["external_id"], "remote-one")

        updated = self.service.reconcile(
            [self.remote("Updated", id="remote-one", external_id="ignored-too")]
        )

        self.assertEqual(updated[0]["name"], "Updated")
        self.assertEqual(updated[0]["id"], imported[0]["id"])
        self.assertEqual(updated[0]["external_id"], "remote-one")
        row = self.rows()[0]
        self.assertEqual(row["id"], original_row["id"])
        self.assertEqual(row["local_id"], original_row["local_id"])
        self.assertEqual(row["updated_at"], NOW)
        self.assertEqual(row["sync_state"], "synced")
        self.assertEqual(row["sync_dirty"], 0)

    def test_dirty_object_payload_is_left_untouched_and_returned_as_local(self):
        local_payload = {
            "name": "My local edit",
            "type": "Run",
            "description": "Local plan",
            "custom_local_field": {"keep": True},
        }
        self.add_row(
            payload=local_payload,
            dirty=1,
            state="sync_error",
        )

        result = self.service.reconcile(
            [self.remote("Remote overwrite", id="remote-existing")]
        )

        self.assertEqual(result[0]["name"], "My local edit")
        self.assertEqual(result[0]["sync_status"], "sync_error")
        row = self.rows()[0]
        self.assertEqual(json.loads(row["payload"]), local_payload)
        self.assertEqual(row["sync_state"], "sync_error")
        self.assertEqual(row["sync_dirty"], 1)

    def test_remote_update_preserves_local_metadata_and_row_ids(self):
        metadata = {
            "date": "2026-10-03T08:30:00",
            "rationale": "Recovery",
            "plan_id": "plan-1",
            "plan_name": "Autumn plan",
            "source": "coach",
            "private_calendar_adjustment": {"minutes": 10},
            "archived": False,
            "local_marked": True,
            "local_deleted": False,
        }
        self.add_row(payload={"name": "Old", **metadata})

        result = self.service.reconcile(
            [self.remote("Remote version", id="remote-existing")]
        )

        self.assertEqual(result[0]["name"], "Remote version")
        for key, value in metadata.items():
            self.assertEqual(result[0][key], value, key)
        row = self.rows()[0]
        self.assertEqual(row["id"], "storage-existing")
        self.assertEqual(row["local_id"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertEqual(
            json.loads(row["payload"])["private_calendar_adjustment"], {"minutes": 10}
        )

    def test_remove_missing_marks_clean_remote_rows_and_skips_dirty_rows(self):
        self.add_row(
            storage_id="clean-storage",
            local_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            external_id="remote-gone",
            payload={"name": "Gone", "custom": "retained"},
        )
        self.add_row(
            storage_id="dirty-storage",
            local_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            external_id="remote-dirty",
            payload={"name": "Dirty"},
            dirty=1,
            state="sync_error",
        )
        self.add_row(
            storage_id="local-storage",
            local_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            external_id="remote-local",
            payload={"name": "Local state"},
            dirty=0,
            state="local",
        )

        self.service.reconcile([], remove_missing=True)

        rows = {row["id"]: row for row in self.rows()}
        self.assertEqual(rows["clean-storage"]["sync_state"], "remote_missing")
        self.assertEqual(rows["clean-storage"]["sync_dirty"], 0)
        self.assertEqual(
            json.loads(rows["clean-storage"]["payload"]),
            {"name": "Gone", "custom": "retained", "sync_status": "remote_missing"},
        )
        self.assertEqual(rows["dirty-storage"]["sync_state"], "sync_error")
        self.assertEqual(rows["dirty-storage"]["sync_dirty"], 1)
        self.assertEqual(rows["local-storage"]["sync_state"], "local")

    def test_batch_rolls_back_when_an_input_element_is_invalid(self):
        with self.assertRaises(AttributeError):
            self.service.reconcile(
                [self.remote("Would be inserted", id="remote-first"), None]
            )

        self.assertEqual(self.rows(), [])

    def test_batch_rolls_back_when_uuid_generation_fails_mid_batch(self):
        calls = 0

        def fail_on_second_id():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected id failure")
            return "44444444-4444-4444-8444-444444444444"

        service = WorkoutLibraryRemoteReconciler(
            self.database_manager, lambda: NOW, fail_on_second_id
        )
        with self.assertRaisesRegex(RuntimeError, "injected id failure"):
            service.reconcile(
                [
                    self.remote("First", id="remote-first"),
                    self.remote("Second", id="remote-second"),
                ]
            )

        self.assertEqual(self.rows(), [])


class WorkoutLibraryRefreshServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "refresh.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
            )
        self.key_value_repository = KeyValueRepository(lambda: NOW)
        self.config = Config(
            port=8090,
            openai_api_key="",
            openai_base_url="",
            openai_model="",
            gemini_api_key="",
            gemini_model="",
            ai_provider="",
            intervals_api_key="fake-key",
            intervals_athlete_id="0",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="x" * 12,
            secure_cookies=False,
            data_retention_days=-1,
        )
        self.provider_client = Mock()
        self.provider_factory = Mock(return_value=self.provider_client)
        self.remote_workouts = [{"id": "remote-one", "name": "Easy run"}]
        self.provider_client.get_workout_library.return_value = self.remote_workouts
        self.reconciler = Mock()
        self.reconciler.reconcile.return_value = [
            {"external_id": "remote-one", "name": "Easy run"}
        ]
        self.workout_library = Mock()
        self.workout_library.list.return_value = [
            {"name": "Active"},
            {"name": "Archived", "archived": True},
        ]
        self.sync_state = Mock()
        self.sync_state.summary.return_value = {"local": 1, "synced": 2}
        self.event_buffer = Mock()
        self.service = self.new_service()

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def new_service(self, *, config=None):
        return WorkoutLibraryRefreshService(
            config or self.config,
            self.database_manager,
            self.provider_factory,
            self.reconciler,
            self.workout_library,
            self.sync_state,
            self.key_value_repository,
            self.event_buffer,
            lambda: NOW,
        )

    def set_marker(self, key, value):
        with self.database_manager.unit_of_work() as db:
            self.key_value_repository.set(db, key, value)

    def get_marker(self, key):
        with self.database_manager.unit_of_work() as db:
            return self.key_value_repository.get(db, key)

    def assert_no_success_publication(self):
        self.assertIsNone(self.get_marker("last_library_sync_at"))
        self.assertIsNone(self.get_marker("last_library_sync_error"))
        self.event_buffer.publish.assert_not_called()

    def test_missing_intervals_key_raises_existing_503_error(self):
        service = self.new_service(config=replace(self.config, intervals_api_key=""))

        with self.assertRaises(AppError) as raised:
            service.refresh()

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(
            raised.exception.message, "INTERVALS_API_KEY ist nicht konfiguriert."
        )
        self.provider_factory.assert_not_called()

    def test_existing_marker_skips_remote_read_and_counts_archived_workouts(self):
        self.set_marker("last_library_sync_at", "previous-sync")

        result = self.service.refresh(reason="manual")

        self.assertEqual(
            result,
            {
                "status": "skipped",
                "reason": "local_authoritative",
                "workouts": 2,
                "local_synced": 0,
                "local_errors": [],
                "synced_at": "previous-sync",
                "library_state": {"local": 1, "synced": 2},
            },
        )
        self.provider_factory.assert_not_called()
        self.workout_library.list.assert_called_once_with(include_archived=True)
        self.event_buffer.publish.assert_not_called()
        self.assertEqual(self.get_marker("last_library_sync_at"), "previous-sync")

    def test_success_reconciles_once_sets_markers_publishes_and_returns_result(self):
        result = self.service.refresh(reason="startup")

        self.assertEqual(
            result,
            {
                "status": "ok",
                "workouts": 1,
                "local_synced": 0,
                "local_errors": [],
                "synced_at": NOW,
                "library_state": {"local": 1, "synced": 2},
            },
        )
        self.provider_factory.assert_called_once_with()
        self.provider_client.get_workout_library.assert_called_once_with()
        self.reconciler.reconcile.assert_called_once_with(
            self.remote_workouts, remove_missing=True
        )
        self.assertEqual(self.get_marker("last_library_sync_at"), NOW)
        self.assertEqual(self.get_marker("last_library_sync_error"), "")
        self.event_buffer.publish.assert_called_once_with(
            "coach", {"status": "changed"}
        )

    def test_cancel_before_provider_read_raises_chat_cancelled(self):
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(AppError) as raised:
            self.service.refresh(cancel_event=cancel_event)

        self.assertEqual(raised.exception.status, 499)
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertEqual(
            raised.exception.message, "Die Coach-Anfrage wurde abgebrochen."
        )
        self.provider_factory.assert_not_called()
        self.assert_no_success_publication()

    def test_cancel_after_provider_read_prevents_reconciliation_and_publication(self):
        cancel_event = threading.Event()

        def read_and_cancel(*, cancel_event):
            cancel_event.set()
            return self.remote_workouts

        self.provider_client.get_workout_library.side_effect = read_and_cancel

        with self.assertRaises(AppError) as raised:
            self.service.refresh(cancel_event=cancel_event)

        self.assertEqual(raised.exception.status, 499)
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertEqual(
            raised.exception.message, "Die Coach-Anfrage wurde abgebrochen."
        )
        self.provider_client.get_workout_library.assert_called_once_with(
            cancel_event=cancel_event
        )
        self.reconciler.reconcile.assert_not_called()
        self.assert_no_success_publication()

    def test_cancel_event_is_forwarded_to_provider_read(self):
        cancel_event = threading.Event()

        self.service.refresh(cancel_event=cancel_event)

        self.provider_client.get_workout_library.assert_called_once_with(
            cancel_event=cancel_event
        )

    def test_provider_failure_does_not_mark_or_publish(self):
        self.provider_client.get_workout_library.side_effect = RuntimeError(
            "provider failed"
        )

        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            self.service.refresh()

        self.reconciler.reconcile.assert_not_called()
        self.assert_no_success_publication()

    def test_reconcile_failure_does_not_mark_or_publish(self):
        self.reconciler.reconcile.side_effect = RuntimeError("reconcile failed")

        with self.assertRaisesRegex(RuntimeError, "reconcile failed"):
            self.service.refresh()

        self.assert_no_success_publication()

    def test_refresh_uses_shared_library_lock_and_running_state(self):
        provider_started = threading.Event()
        running_during_read = []

        def read_library():
            provider_started.set()
            running_during_read.append(workout_library_sync_running())
            return self.remote_workouts

        self.provider_client.get_workout_library.side_effect = read_library
        refresh_started = threading.Event()

        def refresh():
            refresh_started.set()
            return self.service.refresh()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with workout_library_sync_guard():
                self.assertTrue(workout_library_sync_running())
                future = executor.submit(refresh)
                self.assertTrue(refresh_started.wait(timeout=1))
                self.assertFalse(future.done())
                self.provider_client.get_workout_library.assert_not_called()
            result = future.result(timeout=2)

        self.assertTrue(provider_started.is_set())
        self.assertEqual(running_during_read, [True])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(workout_library_sync_running())


if __name__ == "__main__":
    unittest.main()
