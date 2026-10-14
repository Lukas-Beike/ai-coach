"""Focused tests for persistent sync-job queue orchestration."""

import dataclasses
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from provider_runtime_fakes import ACME_ID, acme_descriptor

from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.providers.descriptors import DEFAULT_PROVIDER_DESCRIPTORS
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.jobs import JobValidationError, SyncJobStore, validate_job_request
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.queue import SyncJobQueueService
from backend.sync.queue_assembly import (
    SyncJobQueueAssembly,
    SyncQueuePersistence,
    SyncQueuePolicy,
    SyncQueueWorker,
)


class SyncQueueFixtureMixin:
    """Shared queue fixture: a temporary sync-job database and mocked owners."""

    now = "2026-09-20T12:00:00+00:00"

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "sync-queue.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.executescript(
                """
                CREATE TABLE sync_jobs (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, type TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, requested_by TEXT NOT NULL,
                    attempts INTEGER NOT NULL, progress_total INTEGER NOT NULL,
                    progress_completed INTEGER NOT NULL, error_class TEXT,
                    available_at TEXT, started_at TEXT, finished_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE sync_job_items (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, item_key TEXT NOT NULL,
                    operation TEXT NOT NULL, payload_hash TEXT NOT NULL, remote_id TEXT,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL, error_class TEXT,
                    error_detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(job_id, item_key),
                    FOREIGN KEY(job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE kv (
                    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL
                );
                """
            )
        self.identifiers = iter(f"job-{index}" for index in range(1, 100))
        self.store = SyncJobStore(
            self.manager, lambda: self.now, lambda: next(self.identifiers)
        )
        self.publisher = Mock(spec=StateEventBuffer)
        self.maintenance_gate = MaintenanceGate()
        self.wake_event = threading.Event()
        self.daily_sync_markers = Mock()
        self.service = SyncJobQueueService(
            self.store,
            self.publisher,
            self.maintenance_gate,
            self.wake_event,
            all_sync_days=-1,
            daily_sync_markers=self.daily_sync_markers,
        )


class SyncJobQueueServiceTests(SyncQueueFixtureMixin, unittest.TestCase):
    def _set_job_status(self, job_id, status):
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE sync_jobs SET status=? WHERE id=?", (status, job_id))

    def test_enqueue_persists_wakes_and_publishes_safe_created_event(self):
        result = self.service.enqueue("garmin", payload={"reason": "manual"})

        self.assertEqual(result["provider"], "garmin")
        self.assertEqual(result["status"], "queued")
        self.assertTrue(self.wake_event.is_set())
        self.publisher.publish.assert_called_once_with(
            "job",
            {
                "job_id": result["id"],
                "provider": "garmin",
                "type": "refresh",
                "status": "queued",
                "progress": {"completed": 0, "total": 1},
            },
        )

    def test_deduplicated_performance_job_does_not_publish_or_wake_again(self):
        first = self.service.enqueue(
            "intervals", "performance_refresh", {"reason": "manual"}
        )
        self.wake_event.clear()
        self.publisher.publish.reset_mock()

        second = self.service.enqueue(
            "intervals", "performance_refresh", {"reason": "scheduled"}
        )

        self.assertEqual(second["id"], first["id"])
        self.assertFalse(self.wake_event.is_set())
        self.publisher.publish.assert_not_called()

    def test_enqueue_maps_request_and_store_validation_errors(self):
        invalid_request = self._app_error(lambda: self.service.enqueue("unsupported"))
        invalid_operation = self._app_error(
            lambda: self.service.enqueue(
                "garmin",
                item_operations=[
                    {"item_key": "duplicate", "operation": "refresh"},
                    {"item_key": "duplicate", "operation": "refresh"},
                ],
            )
        )

        for error in (invalid_request, invalid_operation):
            self.assertEqual(error.status, 400)
            self.assertEqual(error.reason, "invalid_job_request")
        self.assertEqual(self.service.list(), [])
        self.assertFalse(self.wake_event.is_set())
        self.publisher.publish.assert_not_called()

    def test_maintenance_rejection_does_not_persist_publish_or_wake(self):
        with self.maintenance_gate.restore():
            error = self._app_error(lambda: self.service.enqueue("garmin"))

        self.assertEqual(error.status, 503)
        self.assertEqual(error.reason, "maintenance")
        self.assertEqual(self.service.list(), [])
        self.assertFalse(self.wake_event.is_set())
        self.publisher.publish.assert_not_called()

    def test_state_list_active_and_pending_performance_job(self):
        performance = self.service.enqueue(
            "intervals", "performance_refresh", {"reason": "manual"}
        )
        weather = self.service.enqueue("weather", payload={"force": True})

        self.assertEqual(
            self.service.state(performance["id"])["payload"], {"reason": "manual"}
        )
        self.assertEqual(
            {job["id"] for job in self.service.list()},
            {performance["id"], weather["id"]},
        )
        self.assertTrue(self.service.active("weather"))
        self.assertFalse(self.service.active("calendar"))
        self.assertEqual(
            self.service.pending_performance_job_id("intervals"), performance["id"]
        )
        self.assertIsNone(self.service.pending_performance_job_id("garmin"))

        error = self._app_error(lambda: self.service.state("missing"))
        self.assertEqual(error.status, 404)
        self.assertEqual(error.message, "Synchronisationsjob nicht gefunden.")
        self.assertEqual(error.reason, "sync_job_not_found")

    def test_resume_wakes_only_when_interrupted_jobs_were_resumed(self):
        self.assertEqual(self.service.resume_interrupted(), 0)
        self.assertFalse(self.wake_event.is_set())

        job = self.service.enqueue("garmin")
        self.wake_event.clear()
        self._set_job_status(job["id"], "running")

        self.assertEqual(self.service.resume_interrupted(), 1)
        self.assertTrue(self.wake_event.is_set())
        self.assertEqual(self.service.state(job["id"])["status"], "queued")

    def test_scheduled_refresh_records_attempt_for_supported_provider_only(self):
        self.service.enqueue("garmin", "refresh", {"days": 2}, requested_by="scheduler")
        self.daily_sync_markers.mark_attempt.assert_called_once_with("garmin")

        self.daily_sync_markers.reset_mock()
        self.service.enqueue("intervals", "refresh", {"days": 2}, requested_by="user")
        self.service.enqueue("weather", "refresh", {}, requested_by="scheduler")
        self.daily_sync_markers.mark_attempt.assert_not_called()

    def test_resolve_validates_payload_missing_state_and_success(self):
        invalid_payload = self._app_error(
            lambda: self.service.resolve("missing", {"action": "continue"})
        )
        self.assertEqual(invalid_payload.status, 400)
        self.assertEqual(invalid_payload.reason, "invalid_job_resolution")

        missing = self._app_error(
            lambda: self.service.resolve("missing", {"action": "retry"})
        )
        self.assertEqual(missing.status, 404)
        self.assertEqual(missing.reason, "sync_job_not_found")

        queued = self.service.enqueue("garmin")
        state_error = self._app_error(
            lambda: self.service.resolve(queued["id"], {"action": "retry"})
        )
        self.assertEqual(state_error.status, 409)
        self.assertEqual(state_error.reason, "invalid_job_resolution")

        self._set_job_status(queued["id"], "failed")
        self.wake_event.clear()
        self.publisher.publish.reset_mock()
        resolved = self.service.resolve(queued["id"], {"action": "RETRY"})

        self.assertEqual(resolved["status"], "queued")
        self.assertEqual(resolved["attempts"], 0)
        self.assertTrue(self.wake_event.is_set())
        self.publisher.publish.assert_not_called()

    def test_test_only_provider_is_queued_through_its_declaring_registry(self):
        registry = ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, acme_descriptor()))
        store = SyncJobStore(
            self.manager,
            lambda: self.now,
            lambda: next(self.identifiers),
            registry=registry,
        )
        service = SyncJobQueueService(
            store,
            self.publisher,
            self.maintenance_gate,
            self.wake_event,
            all_sync_days=-1,
            daily_sync_markers=self.daily_sync_markers,
            registry=registry,
        )

        result = service.enqueue(
            ACME_ID, "refresh", {"reason": "scheduled"}, requested_by="startup"
        )

        self.assertEqual(result["provider"], ACME_ID)
        self.assertEqual(result["status"], "queued")
        self.daily_sync_markers.mark_attempt.assert_called_once_with(ACME_ID)

    def test_test_only_provider_is_rejected_by_the_default_registry(self):
        error = self._app_error(
            lambda: self.service.enqueue(
                ACME_ID, "refresh", {"reason": "scheduled"}, requested_by="startup"
            )
        )

        self.assertEqual(error.status, 400)
        self.assertEqual(error.reason, "invalid_job_request")
        self.assertEqual(self.service.list(), [])
        self.daily_sync_markers.mark_attempt.assert_not_called()

    @staticmethod
    def _app_error(action):
        with unittest.TestCase().assertRaises(AppError) as caught:
            action()
        return caught.exception


class SyncQueueAssemblyRegistryTests(SyncQueueFixtureMixin, unittest.TestCase):
    def _assembly(self, registry=DEFAULT_PROVIDER_REGISTRY):
        return SyncJobQueueAssembly(
            dependencies=SyncJobQueueAssembly.Inputs(
                persistence=SyncQueuePersistence(
                    database_manager=lambda: self.manager,
                    now=lambda: self.now,
                    current_time=lambda: None,
                    uuid_factory=lambda: "unused",
                ),
                worker=SyncQueueWorker(
                    event_buffer=self.publisher,
                    maintenance_gate=self.maintenance_gate,
                    wake_event=lambda: self.wake_event,
                    daily_sync_marker_service=lambda: self.daily_sync_markers,
                ),
                policy=SyncQueuePolicy(
                    all_sync_days=-1,
                    redact_text=str,
                    logger=Mock(),
                    retry_base_seconds=1,
                    retry_max_seconds=2,
                    registry=registry,
                ),
            )
        )

    def test_assembly_forwards_policy_registry_to_store_and_service(self):
        registry = ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, acme_descriptor()))
        job = self._assembly(registry).service().enqueue(ACME_ID, "refresh", {})

        self.assertEqual(job["provider"], ACME_ID)
        with self.assertRaises(AppError) as caught:
            self._assembly().service().enqueue(ACME_ID, "refresh", {})
        self.assertEqual(caught.exception.reason, "invalid_job_request")


class RefreshJobGateTests(unittest.TestCase):
    def test_provider_without_refresh_job_type_rejects_refresh_requests(self):
        descriptor = dataclasses.replace(
            acme_descriptor(), job_types=frozenset({"plan_push"})
        )
        registry = ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, descriptor))

        with self.assertRaisesRegex(JobValidationError, "Unsupported job type."):
            validate_job_request(ACME_ID, "refresh", {}, registry=registry)


if __name__ == "__main__":
    unittest.main()
