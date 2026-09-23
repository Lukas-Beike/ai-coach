from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.sync.full_resync import (
    PROVIDER_RESYNC_KEYS,
    FullProviderResyncService,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import OPERATION_CONTEXT

NOW = "2026-09-20T12:00:00+00:00"


class RecordingObserver:
    def __init__(self):
        self.calls = []
        self.scopes = []

    @contextmanager
    def observe(self, provider, area, reason, operation_id):
        self.calls.append((provider, area, reason, operation_id))
        token = OPERATION_CONTEXT.set(
            {"operation_id": operation_id, "trigger": "full_resync"}
        )
        scope = SimpleNamespace(result=None)
        self.scopes.append(scope)
        try:
            yield scope
        finally:
            OPERATION_CONTEXT.reset(token)


class RecordingResyncGate(ProviderResyncGate):
    def __init__(self, provider):
        super().__init__(provider)
        self.operation_entries = 0

    @contextmanager
    def operation(self):
        self.operation_entries += 1
        with super().operation():
            yield


class RecordingLogger:
    def __init__(self):
        self.events = []
        self.exceptions = []

    def log(self, level, message, *, extra):
        self.events.append((level, message, extra))

    def exception(self, message, **kwargs):
        self.exceptions.append((message, kwargs))


class FullProviderResyncServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "full-resync.sqlite3"
        with closing(sqlite3.connect(database_path)) as db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.commit()
        self.database = DatabaseManager(
            database_path,
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.intervals_gate = RecordingResyncGate("Intervals.icu")
        self.garmin_gate = RecordingResyncGate("Garmin")
        self.intervals_service = SimpleNamespace(sync=self._intervals_sync)
        self.garmin_service = SimpleNamespace(
            configured=lambda: True, sync=self._garmin_sync
        )
        self.competition_service = SimpleNamespace(sync=self._competition_sync)
        self.observer = RecordingObserver()
        self.logger = RecordingLogger()
        self.intervals_calls = []
        self.garmin_calls = []
        self.competition_calls = []
        self.intervals_result = {"status": "ok", "activities": 12}
        self.competition_result = {"status": "ok", "imported": 2}
        self.garmin_result = {"status": "ok", "records": 20}
        self.intervals_error = None
        self.service = self._service()

    def tearDown(self):
        self.database.close()
        self.temporary_directory.cleanup()

    def _intervals_sync(self, *args, **kwargs):
        self.intervals_calls.append((args, kwargs))
        if self.intervals_error:
            raise self.intervals_error
        return self.intervals_result

    def _garmin_sync(self, **kwargs):
        self.garmin_calls.append(kwargs)
        return self.garmin_result

    def _competition_sync(self, **kwargs):
        self.competition_calls.append(kwargs)
        return self.competition_result

    def _service(self, *, config=None, key_values=None):
        return FullProviderResyncService(
            config or SimpleNamespace(intervals_api_key="fake-key"),
            self.intervals_service,
            self.garmin_service,
            self.competition_service,
            self.observer,
            self.intervals_gate,
            self.garmin_gate,
            self.database,
            key_values or self.key_values,
            lambda value: value.replace("api-secret", "[redacted]"),
            self.logger,
            lambda: NOW,
            lambda: 10.0,
            lambda: "generated-operation",
            -1,
        )

    def _get_value(self, provider, field):
        keys = PROVIDER_RESYNC_KEYS[provider]
        with self.database.reader() as db:
            return self.key_values.get(db, keys[field])

    def _set_value(self, provider, field, value):
        keys = PROVIDER_RESYNC_KEYS[provider]
        with self.database.unit_of_work() as db:
            self.key_values.set(db, keys[field], value)

    def test_state_projects_running_status_and_last_error_in_contract_order(self):
        self._set_value("intervals", "running", "0")
        self._set_value("intervals", "status", "stale progress")
        self._set_value("intervals", "last_at", NOW)
        self._set_value("intervals", "error", "prior failure")

        state = self.service.state("intervals")
        self.assertEqual(
            list(state), ["running", "status", "last_resync_at", "last_error"]
        )
        self.assertEqual(
            state,
            {
                "running": False,
                "status": None,
                "last_resync_at": NOW,
                "last_error": "prior failure",
            },
        )

        self._set_value("intervals", "running", "1")
        self.assertEqual(self.service.state("intervals")["status"], "stale progress")

    def test_state_reads_all_values_through_one_reader(self):
        with patch.object(
            self.database, "reader", wraps=self.database.reader
        ) as reader:
            self.service.state("intervals")

        reader.assert_called_once_with()

    def test_state_reuses_caller_owned_database_connection(self):
        with (
            self.database.unit_of_work() as db,
            patch.object(self.database, "reader") as reader,
        ):
            self.service.state("intervals", db)

        reader.assert_not_called()

    def test_unknown_provider_uses_application_error_contract(self):
        with self.assertRaises(AppError) as caught:
            self.service.resync("unknown")
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.message, "Unbekannte Anbindung.")

    def test_intervals_without_key_uses_existing_error(self):
        service = self._service(config=SimpleNamespace(intervals_api_key=""))
        with self.assertRaises(AppError) as caught:
            service.resync("intervals")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.message, INTERVALS_API_KEY_ERROR)
        self.assertFalse(self.intervals_gate.is_resetting())

    def test_garmin_without_configuration_uses_existing_message(self):
        self.garmin_service.configured = lambda: False
        with self.assertRaises(AppError) as caught:
            self.service.resync("garmin")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(
            caught.exception.message,
            "Garmin ist nicht konfiguriert oder nicht verfügbar.",
        )
        self.assertFalse(self.garmin_gate.is_resetting())

    def test_gate_competition_returns_without_kv_or_provider_writes(self):
        self.assertTrue(self.intervals_gate.begin_reset())
        try:
            result = self.service.resync("intervals", "contended-operation")
        finally:
            self.intervals_gate.end_reset()

        self.assertEqual(result, {"status": "already_running", "source": "intervals"})
        self.assertEqual(self.intervals_calls, [])
        self.assertEqual(self.competition_calls, [])
        self.assertIsNone(self._get_value("intervals", "running"))
        self.assertIsNone(self._get_value("intervals", "status"))

    def test_intervals_and_competitions_share_operation_and_never_push(self):
        token = OPERATION_CONTEXT.set({"operation_id": "parent", "trigger": "chat"})
        try:
            result = self.service.resync("intervals", "shared-operation")
            restored = OPERATION_CONTEXT.get()
        finally:
            OPERATION_CONTEXT.reset(token)

        self.assertEqual(
            self.intervals_calls,
            [
                (
                    ("Vollständiger Resync",),
                    {"activity_days": -1, "operation_id": "shared-operation"},
                )
            ],
        )
        self.assertEqual(
            self.competition_calls,
            [{"reason": "Vollständiger Resync", "push_local": False}],
        )
        self.assertEqual(
            self.observer.calls,
            [
                (
                    "intervals",
                    "competitions",
                    "Vollständiger Resync",
                    "shared-operation",
                )
            ],
        )
        self.assertEqual(self.observer.scopes[0].result, self.competition_result)
        self.assertEqual(self.intervals_gate.operation_entries, 1)
        self.assertEqual(restored, {"operation_id": "parent", "trigger": "chat"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["competitions"], self.competition_result)
        self.assertEqual(self._get_value("intervals", "running"), "0")
        self.assertEqual(self._get_value("intervals", "status"), "")
        self.assertEqual(self._get_value("intervals", "last_at"), NOW)
        self.assertEqual(self._get_value("intervals", "error"), "")
        self.assertFalse(self.intervals_gate.is_resetting())

    def test_garmin_receives_full_days_reason_and_operation_id(self):
        result = self.service.resync("garmin", "garmin-operation")

        self.assertEqual(
            self.garmin_calls,
            [
                {
                    "days": -1,
                    "operation_id": "garmin-operation",
                    "reason": "Vollständiger Resync",
                }
            ],
        )
        self.assertEqual(result["records"], 20)
        self.assertEqual(self._get_value("garmin", "running"), "0")
        self.assertEqual(self._get_value("garmin", "status"), "")
        self.assertEqual(self._get_value("garmin", "last_at"), NOW)
        self.assertFalse(self.garmin_gate.is_resetting())

    def test_failure_is_redacted_bounded_and_restores_context_and_gate(self):
        self.intervals_error = RuntimeError("api-secret" + "x" * 1100)
        token = OPERATION_CONTEXT.set({"operation_id": "outer", "trigger": "chat"})
        try:
            with self.assertRaisesRegex(RuntimeError, "api-secret"):
                self.service.resync("intervals", "failed-operation")
            restored = OPERATION_CONTEXT.get()
        finally:
            OPERATION_CONTEXT.reset(token)

        error = self._get_value("intervals", "error")
        self.assertEqual(len(error), 1000)
        self.assertNotIn("api-secret", error)
        self.assertEqual(self._get_value("intervals", "running"), "0")
        self.assertEqual(self._get_value("intervals", "status"), "")
        self.assertEqual(restored, {"operation_id": "outer", "trigger": "chat"})
        self.assertFalse(self.intervals_gate.is_resetting())
        self.assertEqual(
            self.logger.exceptions[0][1]["extra"]["context"]["provider"],
            "intervals",
        )
        self.assertEqual(self.logger.events[-1][2]["event"], "operation_failed")

    def test_gate_and_context_are_restored_when_status_cleanup_fails(self):
        class FailingStatusCleanupRepository:
            def get(self, db, key):
                return self_base.get(db, key)

            def set(self, db, key, value):
                if key == PROVIDER_RESYNC_KEYS["intervals"]["status"] and value == "":
                    raise RuntimeError("status cleanup failed")
                self_base.set(db, key, value)

        self_base = self.key_values
        service = self._service(key_values=FailingStatusCleanupRepository())
        token = OPERATION_CONTEXT.set({"operation_id": "outer", "trigger": "chat"})
        try:
            with self.assertRaisesRegex(RuntimeError, "status cleanup failed"):
                service.resync("intervals", "cleanup-operation")
            restored = OPERATION_CONTEXT.get()
        finally:
            OPERATION_CONTEXT.reset(token)

        self.assertEqual(self._get_value("intervals", "running"), "0")
        self.assertEqual(restored, {"operation_id": "outer", "trigger": "chat"})
        self.assertFalse(self.intervals_gate.is_resetting())


if __name__ == "__main__":
    unittest.main()
