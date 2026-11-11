from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from provider_runtime_fakes import ACME_ID, acme_descriptor, fake_binding
from support import temp_database

from backend.db import row_factory
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID
from backend.sync.full_resync import (
    PROVIDER_RESYNC_KEYS,
    FullProviderResyncService,
    FullResyncOperationJournal,
    FullResyncStateStore,
    resync_field_keys,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import OPERATION_CONTEXT
from backend.sync.provider_registry import ProviderRegistry
from backend.sync.provider_resync_assembly import full_resync_handlers
from backend.sync.provider_runtime import ProviderRuntimeRegistry

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
        database_path = (
            Path(self.enterContext(tempfile.TemporaryDirectory()))
            / "full-resync.sqlite3"
        )
        with closing(sqlite3.connect(database_path)) as db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.commit()
        self.database = temp_database(
            self, path=database_path, row_factory=row_factory, persist_connections=False
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.garmin_gate = RecordingResyncGate("Garmin")
        self.garmin_service = SimpleNamespace(
            configured=lambda: True, sync=self._garmin_sync
        )
        self.competition_service = SimpleNamespace(sync=self._competition_sync)
        self.observer = RecordingObserver()
        self.logger = RecordingLogger()
        self.garmin_calls = []
        self.competition_calls = []
        self.competition_result = {"status": "ok", "imported": 2}
        self.garmin_result = {"status": "ok", "records": 20}
        self.service = self._service()

    def _garmin_sync(self, **kwargs):
        self.garmin_calls.append(kwargs)
        return self.garmin_result

    def _competition_sync(self, **kwargs):
        self.competition_calls.append(kwargs)
        return self.competition_result

    def _service(
        self,
        *,
        config=None,
        key_values=None,
        operation_id_factory=None,
        after_resync=None,
    ):
        operation_journal = FullResyncOperationJournal(
            self.observer,
            self.logger,
            lambda value: value.replace("api-secret", "[redacted]"),
            lambda: NOW,
            lambda: 10.0,
            operation_id_factory or (lambda: "generated-operation"),
        )
        gates = {GARMIN_ID: self.garmin_gate}
        handlers = full_resync_handlers(
            garmin_service=self.garmin_service,
            all_sync_days=-1,
        )
        return FullProviderResyncService(
            handlers,
            FullResyncStateStore(
                self.database,
                key_values or self.key_values,
                PROVIDER_RESYNC_KEYS,
            ),
            operation_journal,
            gates=gates,
            **({"after_resync": after_resync} if after_resync else {}),
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
        self._set_value("garmin", "running", "0")
        self._set_value("garmin", "status", "stale progress")
        self._set_value("garmin", "last_at", NOW)
        self._set_value("garmin", "error", "prior failure")

        state = self.service.state("garmin")
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

        self._set_value("garmin", "running", "1")
        self.assertEqual(self.service.state("garmin")["status"], "stale progress")

    def test_state_reads_all_values_through_one_reader(self):
        with patch.object(
            self.database, "reader", wraps=self.database.reader
        ) as reader:
            self.service.state("garmin")

        reader.assert_called_once_with()

    def test_state_reuses_caller_owned_database_connection(self):
        with (
            self.database.unit_of_work() as db,
            patch.object(self.database, "reader") as reader,
        ):
            self.service.state("garmin", db)

        reader.assert_not_called()

    def test_unknown_provider_uses_application_error_contract(self):
        with self.assertRaises(AppError) as caught:
            self.service.resync("unknown")
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.message, "Unbekannte Anbindung.")

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

    def _wait_for_outcome(self, service, provider="garmin"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            outcome = service.progress(provider)["outcome"]
            if outcome is not None:
                return outcome
            time.sleep(0.01)
        self.fail("the background resync did not finish")

    def _blocking_garmin_sync(self):
        """Make the Garmin read outlast the caller, until the test releases it."""
        started = threading.Event()
        release = threading.Event()

        def sync(**kwargs):
            self.garmin_calls.append(kwargs)
            started.set()
            release.wait(5)
            return self.garmin_result

        self.garmin_service.sync = sync
        return started, release

    def test_a_resync_longer_than_the_request_is_accepted_and_later_reported_done(self):
        started, release = self._blocking_garmin_sync()

        accepted = self.service.start("garmin", "op-1")

        self.assertEqual(
            accepted,
            {"status": "started", "source": "garmin", "operation_id": "op-1"},
        )
        self.assertTrue(started.wait(5))
        running = self.service.progress("garmin")
        self.assertTrue(running["running"])
        self.assertIsNone(running["outcome"])
        self.assertIsNone(running["last_resync_at"])

        release.set()
        outcome = self._wait_for_outcome(self.service)

        self.assertEqual(outcome, {"operation_id": "op-1", "status": "ok"})
        done = self.service.progress("garmin")
        self.assertFalse(done["running"])
        self.assertEqual(done["last_resync_at"], NOW)
        self.assertIsNone(done["last_error"])

    def test_a_repeated_start_runs_no_second_resync(self):
        started, release = self._blocking_garmin_sync()
        self.service.start("garmin", "op-1")
        self.assertTrue(started.wait(5))

        repeated = self.service.start("garmin", "op-2")
        self.assertEqual(
            repeated,
            {"status": "already_running", "source": "garmin", "operation_id": "op-1"},
        )
        release.set()
        self._wait_for_outcome(self.service)

        self.assertEqual([call["operation_id"] for call in self.garmin_calls], ["op-1"])
        self.assertEqual(self.service.start("garmin", "op-3")["status"], "started")
        self._wait_for_outcome(self.service)

    def test_start_reports_a_missing_configuration_before_any_thread_runs(self):
        self.garmin_service.configured = lambda: False

        with self.assertRaises(AppError) as caught:
            self.service.start("garmin", "op-1")

        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.garmin_calls, [])
        self.assertIsNone(self.service.progress("garmin")["outcome"])

    def test_a_partial_resync_is_not_recorded_as_complete(self):
        self.garmin_result = {"status": "partial", "records": 7}

        result = self.service.resync("garmin", "op-1")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"], 7)
        self.assertNotIn("resynced_at", result)
        self.assertIsNone(self._get_value("garmin", "last_at"))
        self.assertEqual(
            self._get_value("garmin", "error"),
            "Teilweise geladen. Bitte erneut starten.",
        )
        self.assertEqual(self._get_value("garmin", "running"), "0")

    def test_a_partial_resync_keeps_the_last_complete_time_and_reports_partial(self):
        self.service.resync("garmin", "op-1")
        self.garmin_result = {"status": "partial"}

        self.service.start("garmin", "op-2")
        outcome = self._wait_for_outcome(self.service)

        self.assertEqual(outcome, {"operation_id": "op-2", "status": "partial"})
        self.assertEqual(self._get_value("garmin", "last_at"), NOW)

    def test_a_contended_garmin_read_is_a_failed_resync_without_a_completion_time(self):
        self.garmin_result = {"status": "already_running"}

        self.service.start("garmin", "op-1")
        outcome = self._wait_for_outcome(self.service)

        self.assertEqual(
            outcome,
            {"operation_id": "op-1", "status": "failed", "reason": "already_running"},
        )
        self.assertIsNone(self._get_value("garmin", "last_at"))
        self.assertIn("läuft bereits", self._get_value("garmin", "error"))
        self.assertFalse(self.garmin_gate.is_resetting())

    def test_a_failed_background_resync_keeps_the_error_and_ends_the_run(self):
        self.garmin_service.sync = Mock(side_effect=AppError(502, "Garmin down"))

        self.service.start("garmin", "op-1")
        outcome = self._wait_for_outcome(self.service)

        self.assertEqual(outcome["status"], "failed")
        state = self.service.progress("garmin")
        self.assertFalse(state["running"])
        self.assertEqual(state["last_error"], "Garmin down")
        self.assertEqual(self.service.start("garmin", "op-2")["status"], "started")
        self._wait_for_outcome(self.service)

    def test_the_derived_passes_run_before_the_background_resync_ends(self):
        seen = []
        service = self._service(
            after_resync=lambda job: seen.append(service.progress("garmin")["running"])
        )

        service.start("garmin", "op-1")
        self._wait_for_outcome(service)

        self.assertEqual(seen, [True])

    def test_a_finished_resync_requests_the_derived_passes_after_the_gate_ends(self):
        requested = []
        gate_state = []

        def after_resync(job):
            requested.append(dict(job))
            gate_state.append(self.garmin_gate.is_resetting())

        service = self._service(after_resync=after_resync)

        service.resync("garmin", "garmin-operation")

        self.assertEqual(requested, [{"provider": "garmin", "type": "refresh"}])
        self.assertEqual(gate_state, [False])

    def test_a_partial_resync_requests_the_derived_passes(self):
        requested = []
        service = self._service(after_resync=requested.append)
        self.garmin_service.sync = Mock(return_value={"status": "partial"})

        result = service.resync("garmin")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(requested, [{"provider": "garmin", "type": "refresh"}])

    def test_a_failed_resync_requests_no_derived_pass(self):
        requested = []
        service = self._service(after_resync=requested.append)
        self.garmin_service.sync = Mock(side_effect=AppError(502, "Garmin down"))

        with self.assertRaises(AppError):
            service.resync("garmin")

        self.assertEqual(requested, [])

    def test_an_already_running_resync_requests_no_derived_pass(self):
        requested = []
        service = self._service(after_resync=requested.append)
        self.garmin_gate.begin_reset()

        result = service.resync("garmin")

        self.assertEqual(result["status"], "already_running")
        self.assertEqual(requested, [])

    def test_gate_and_context_are_restored_when_status_cleanup_fails(self):
        class FailingStatusCleanupRepository:
            def get(self, db, key):
                return self_base.get(db, key)

            def set(self, db, key, value):
                if key == PROVIDER_RESYNC_KEYS["garmin"]["status"] and value == "":
                    raise RuntimeError("status cleanup failed")
                self_base.set(db, key, value)

        self_base = self.key_values
        service = self._service(key_values=FailingStatusCleanupRepository())
        token = OPERATION_CONTEXT.set({"operation_id": "outer", "trigger": "chat"})
        try:
            with self.assertRaisesRegex(RuntimeError, "status cleanup failed"):
                service.resync("garmin", "cleanup-operation")
            restored = OPERATION_CONTEXT.get()
        finally:
            OPERATION_CONTEXT.reset(token)

        self.assertEqual(self._get_value("garmin", "running"), "0")
        self.assertEqual(restored, {"operation_id": "outer", "trigger": "chat"})
        self.assertFalse(self.garmin_gate.is_resetting())


ACME_KEYS = (
    "acme_full_resync_running",
    "acme_full_resync_status",
    "acme_full_resync_at",
    "acme_full_resync_error",
)


class AcmeFullResyncHandler:
    """Test-only handler for the provider that is registered only in tests."""

    def __init__(self, *, configured=True, read_status=None):
        self._configured = configured
        self._read_status = read_status
        self.calls = []
        self.status_during_run = None

    def configured(self):
        return self._configured

    def not_configured_error(self):
        return AppError(503, "Acme ist nicht konfiguriert.", reason="not_configured")

    def run(self, operation_id, observer):
        self.calls.append((operation_id, observer))
        if self._read_status is not None:
            self.status_during_run = self._read_status()
        return {"activities": 3}


class RegisteredOnlyProviderResyncTests(unittest.TestCase):
    def setUp(self):
        database_path = (
            Path(self.enterContext(tempfile.TemporaryDirectory()))
            / "registered-resync.sqlite3"
        )
        with closing(sqlite3.connect(database_path)) as db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.commit()
        self.database = temp_database(
            self, path=database_path, row_factory=row_factory, persist_connections=False
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.observer = RecordingObserver()
        self.logger = RecordingLogger()
        self.gate = RecordingResyncGate(ACME_ID)
        self.handler = AcmeFullResyncHandler(
            read_status=lambda: self._stored(ACME_KEYS[1])
        )

    def _stored(self, key):
        with self.database.reader() as db:
            return self.key_values.get(db, key)

    def _runtime(self, *, with_handler=True):
        if not with_handler:
            return ProviderRuntimeRegistry(
                ProviderRegistry([acme_descriptor()]), [fake_binding(ACME_ID)]
            )
        descriptor = replace(acme_descriptor(), resync_keys=ACME_KEYS)
        binding = replace(
            fake_binding(ACME_ID),
            gate=self.gate,
            full_resync=lambda: self.handler,
        )
        return ProviderRuntimeRegistry(ProviderRegistry([descriptor]), [binding])

    def _service(self, runtime):
        return FullProviderResyncService(
            runtime.resync_handlers(),
            FullResyncStateStore(
                self.database,
                self.key_values,
                resync_field_keys(runtime.static.resync_key_map()),
            ),
            FullResyncOperationJournal(
                self.observer,
                self.logger,
                lambda value: value,
                lambda: NOW,
                lambda: 10.0,
                lambda: "generated-operation",
            ),
            gates={ACME_ID: self.gate},
            registry=runtime.static,
        )

    def test_registered_provider_runs_full_resync_through_its_handler(self):
        service = self._service(self._runtime())

        result = service.resync(ACME_ID, "acme-operation")

        self.assertEqual(
            result,
            {
                "status": "ok",
                "source": ACME_ID,
                "resynced_at": NOW,
                "activities": 3,
            },
        )
        self.assertEqual(self.handler.calls, [("acme-operation", self.observer)])
        self.assertEqual(
            self.handler.status_during_run,
            "Acme mock: vollständiger Resync läuft…",
        )
        self.assertEqual(self._stored("acme_full_resync_running"), "0")
        self.assertEqual(self._stored("acme_full_resync_status"), "")
        self.assertEqual(self._stored("acme_full_resync_at"), NOW)
        self.assertEqual(self._stored("acme_full_resync_error"), "")
        state = service.state(ACME_ID)
        self.assertEqual(
            list(state), ["running", "status", "last_resync_at", "last_error"]
        )
        self.assertEqual(state["last_resync_at"], NOW)
        self.assertFalse(self.gate.is_resetting())
        self.assertEqual(self.logger.events[-1][2]["event"], "operation_completed")

    def test_registered_provider_without_handler_is_rejected_like_unknown_provider(
        self,
    ):
        service = self._service(self._runtime(with_handler=False))

        with self.assertRaises(AppError) as caught:
            service.resync(ACME_ID)
        self.assertEqual(
            (caught.exception.status, caught.exception.message),
            (400, "Unbekannte Anbindung."),
        )
        with self.assertRaises(AppError) as caught:
            service.state(ACME_ID)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.handler.calls, [])
        self.assertFalse(self.gate.is_resetting())
        self.assertIsNone(self._stored("acme_full_resync_running"))

    def test_unconfigured_handler_error_is_raised_before_gate_reset(self):
        self.handler = AcmeFullResyncHandler(configured=False)
        service = self._service(self._runtime())

        with self.assertRaises(AppError) as caught:
            service.resync(ACME_ID)
        self.assertEqual(caught.exception.message, "Acme ist nicht konfiguriert.")
        self.assertEqual(caught.exception.reason, "not_configured")
        self.assertEqual(self.handler.calls, [])
        self.assertFalse(self.gate.is_resetting())


if __name__ == "__main__":
    unittest.main()
