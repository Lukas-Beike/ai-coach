from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.status import SyncOperationStateWriter, SyncPublicStateService

NOW = "2026-09-20T12:00:00+00:00"


class SyncOperationStateWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "status.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.events = Mock()
        self.writer = SyncOperationStateWriter(
            self.manager,
            self.key_values,
            self.events,
            lambda value: value.replace("SECRET", "[redacted]"),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def get_value(self, key: str) -> str | None:
        with self.manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def test_write_persists_bounded_state_before_publishing(self) -> None:
        observed: dict[str, str | None] = {}

        def publish(_event, _payload):
            observed["status"] = self.get_value("sync_operation_status")

        self.events.publish.side_effect = publish

        self.writer.write("operation-1", "running", "fetching", 125, "Reading")

        self.assertEqual(self.get_value("sync_operation_id"), "operation-1")
        self.assertEqual(self.get_value("sync_operation_status"), "running")
        self.assertEqual(self.get_value("sync_operation_phase"), "fetching")
        self.assertEqual(self.get_value("sync_operation_progress"), "100")
        self.assertEqual(self.get_value("sync_operation_message"), "Reading")
        self.assertEqual(observed, {"status": "running"})
        self.events.publish.assert_called_once_with(
            "sync",
            {
                "operation_id": "operation-1",
                "status": "running",
                "phase": "fetching",
                "progress": 100,
            },
        )

    def test_error_is_redacted_and_truncated_without_entering_event(self) -> None:
        self.writer.write(
            "operation-2",
            "error",
            "error",
            -4,
            "Failed",
            "SECRET" + ("x" * 1100),
        )

        persisted = self.get_value("last_sync_error")
        self.assertEqual(len(persisted or ""), 1000)
        self.assertNotIn("SECRET", persisted or "")
        payload = self.events.publish.call_args.args[1]
        self.assertEqual(payload["progress"], 0)
        self.assertNotIn("error", payload)

    def test_persistence_failure_does_not_publish(self) -> None:
        with (
            patch.object(
                self.key_values,
                "set",
                side_effect=sqlite3.OperationalError("synthetic storage failure"),
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            self.writer.write("operation-3", "running", "fetching", 10, "Reading")

        self.events.publish.assert_not_called()


class SyncPublicStateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "public-status.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.profile = Mock()
        self.profile.get.return_value = {"name": "Athlete"}
        self.freshness = Mock()
        self.freshness.current.return_value = [
            {"provider": "intervals", "state": "fresh"}
        ]
        self.garmin = Mock()
        self.garmin.core_error_entries.return_value = []
        self.maintenance = MaintenanceGate()
        self.jobs = Mock()
        self.jobs.list.return_value = [{"id": "job-1", "status": "pending"}]
        self.versions = Mock()
        self.versions.versions.return_value = {"chat": "9:2"}
        self.intervals_lock = threading.Lock()
        self.service = SyncPublicStateService(
            SimpleNamespace(
                garmin_tokenstore=str(Path(self.temporary_directory.name) / "tokens")
            ),
            self.manager,
            self.key_values,
            self.freshness,
            self.profile,
            self.garmin,
            self.maintenance,
            self.jobs,
            self.versions,
            self.intervals_lock,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def set_values(self, **values: str) -> None:
        with self.manager.unit_of_work() as db:
            for key, value in values.items():
                self.key_values.set(db, key, value)

    def test_state_preserves_public_fields_and_explicit_empty_overrides(self) -> None:
        self.set_values(
            sync_running="0",
            sync_operation_status="partial",
            sync_operation_phase="reconciling",
            sync_operation_progress="145",
            sync_operation_id="operation-7",
            sync_operation_message="Partial refresh",
            sync_operation_started_at="started-at",
            sync_operation_finished_at="finished-at",
            last_sync_error="safe error",
        )
        freshness: list[dict[str, object]] = []
        jobs: list[dict[str, object]] = []

        actual = self.service.state(freshness=freshness, jobs=jobs)

        self.assertEqual(
            actual,
            {
                "status": "partial",
                "phase": "reconciling",
                "progress": 100,
                "operation_id": "operation-7",
                "running": False,
                "message": "Partial refresh",
                "started_at": "started-at",
                "finished_at": "finished-at",
                "last_error": "safe error",
                "state_versions": {"chat": "9:2"},
                "provider_freshness": freshness,
                "maintenance": {"active": False, "running_operations": 0},
                "jobs": jobs,
            },
        )
        self.freshness.current.assert_not_called()
        self.jobs.list.assert_not_called()

    def test_state_derives_running_freshness_and_jobs_from_owners(self) -> None:
        self.set_values(sync_running="0")
        self.intervals_lock.acquire()
        try:
            actual = self.service.state()
        finally:
            self.intervals_lock.release()

        self.assertTrue(actual["running"])
        self.assertEqual(actual["status"], "running")
        self.assertEqual(actual["phase"], "running")
        self.assertEqual(
            actual["provider_freshness"], self.freshness.current.return_value
        )
        self.assertEqual(actual["jobs"], self.jobs.list.return_value)
        self.profile.get.assert_called_once_with()
        self.garmin.core_error_entries.assert_called_once_with()
        self.freshness.current.assert_called_once_with(
            profile={"name": "Athlete"},
            garmin_has_core_error=False,
            garmin_tokenstore_exists=False,
        )
        self.jobs.list.assert_called_once_with()

    def test_browser_state_is_bounded_and_uses_stored_status_fallback(self) -> None:
        self.set_values(
            sync_operation_message="Sync in progress",
            sync_status="Saved status",
        )
        projected = self.service.browser_state(freshness=[], jobs=[])

        self.assertEqual(
            projected,
            {
                "status": "Saved status",
                "phase": "idle",
                "progress": 0,
                "operation_id": None,
                "running": False,
                "message": "Sync in progress",
                "started_at": None,
                "finished_at": None,
                "last_error": None,
                "jobs": [],
            },
        )

        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM kv WHERE key = 'sync_status'")
        fallback = self.service.browser_state(freshness=[], jobs=[])
        self.assertEqual(fallback["status"], "Sync in progress")


if __name__ == "__main__":
    unittest.main()
