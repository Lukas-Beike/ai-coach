from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.config import load_config
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.sync.daily import DailySyncMarkerService
from backend.sync.intervals import (
    IntervalsSnapshotReader,
    IntervalsSnapshotService,
    IntervalsSyncJournal,
    IntervalsSyncRuntime,
    IntervalsSyncService,
    IntervalsSyncStatus,
    IntervalsSyncWorkflow,
)
from backend.sync.performance import PerformanceRefreshFollowupService
from backend.sync.state import SyncStateRepository
from backend.sync.status import SyncOperationStateWriter

NOW = "2026-09-20T12:00:00+00:00"


class RecordingObserver:
    def __init__(self, events):
        self.events = events
        self.calls = []

    @contextmanager
    def observe(self, provider, area, reason="background", operation_id=None):
        self.calls.append((provider, area, reason, operation_id))
        self.events.append("observer.enter")
        scope = SimpleNamespace(operation_id=operation_id or "observed-id", result=None)
        try:
            yield scope
        finally:
            self.events.append(("observer.exit", scope.result))


class RecordingGate:
    def __init__(self, events):
        self.events = events

    @contextmanager
    def operation(self):
        self.events.append("gate.enter")
        try:
            yield
        finally:
            self.events.append("gate.exit")


class IntervalsSyncServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.database_manager = DatabaseManager(
            root / "intervals-flow.sqlite", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.database_manager.close)
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.sync_state = SyncStateRepository(
            self.database_manager,
            self.key_values,
            SnapshotRepository(),
            lambda: NOW,
        )
        self.config = load_config(root, root, {"INTERVALS_API_KEY": "fake-key"})
        self.reader = Mock(spec=IntervalsSnapshotReader)
        self.snapshot_service = Mock(spec=IntervalsSnapshotService)
        self.daily_markers = Mock(spec=DailySyncMarkerService)
        self.followup = Mock(spec=PerformanceRefreshFollowupService)
        self.status_writer = Mock(spec=SyncOperationStateWriter)
        self.events = []
        self.observer = RecordingObserver(self.events)
        self.gate = RecordingGate(self.events)
        self.lock = threading.Lock()
        self.logger = Mock(spec=logging.Logger)
        self.snapshot = {
            "synced_at": NOW,
            "recent_activities": [{"id": "activity"}],
            "recent_wellness": [{"id": "wellness"}],
            "upcoming_calendar": [{"id": "event"}],
        }
        self.reader.fetch_snapshot.return_value = self.snapshot
        self.snapshot_service.store_snapshot.return_value = (
            self.snapshot,
            {"imported": 0, "updated": 0, "conflicts": 0},
        )
        self.snapshot_service.seed_workout_library.return_value = (2, None, 3)
        self.snapshot_service.record_window.return_value = (
            [(date(2026, 9, 14), date(2026, 9, 20))],
            {"activities": {"complete": True}},
        )
        self.followup.enqueue_after_sync.return_value = {"id": "performance-job"}
        self.service = self.make_service()

    def make_service(self, *, config=None, monotonic=None, wait_seconds=120.0):
        clock = monotonic or (lambda: 0.0)
        status = IntervalsSyncStatus(self.database_manager, self.key_values)
        return IntervalsSyncService(
            config or self.config,
            IntervalsSyncWorkflow(
                self.reader,
                self.snapshot_service,
                self.sync_state,
                self.daily_markers,
                {"intervals": 42},
                -1,
            ),
            self.followup,
            status,
            IntervalsSyncJournal(
                status,
                self.status_writer,
                lambda value: value.replace("secret", "[REDACTED]"),
                self.logger,
                lambda: NOW,
            ),
            IntervalsSyncRuntime(
                self.lock,
                self.observer,
                self.gate,
                monotonic=clock,
                wait_seconds=wait_seconds,
            ),
        )

    def get_value(self, key):
        with self.database_manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def set_value(self, key, value):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def test_success_owns_gate_status_persistence_and_followup(self):
        result = self.service.sync(
            "manual refresh", activity_days=7, wait_for_performance=True
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["activities"], 1)
        self.assertEqual(result["performance_refresh_job_id"], "performance-job")
        self.assertEqual(self.events[0:2], ["observer.enter", "gate.enter"])
        self.assertEqual(self.events[-2], "gate.exit")
        self.assertEqual(self.events[-1][0], "observer.exit")
        self.assertEqual(self.events[-1][1], result)
        self.reader.fetch_snapshot.assert_called_once_with(activity_days=7)
        self.snapshot_service.store_snapshot.assert_called_once_with(
            self.snapshot, 7, None
        )
        self.daily_markers.mark.assert_called_once_with("intervals")
        self.followup.enqueue_after_sync.assert_called_once_with("manual refresh")
        self.followup.wait.assert_called_once_with("performance-job", cancel_event=None)
        self.assertEqual(
            [call.args[1:4] for call in self.status_writer.write.call_args_list],
            [
                ("running", "fetching", 10),
                ("running", "storing", 75),
                ("completed", "complete", 100),
            ],
        )
        self.assertEqual(self.get_value("sync_running"), "0")
        self.assertEqual(self.get_value("sync_status"), "")
        self.assertFalse(self.lock.locked())

    def test_historical_sync_forwards_end_and_cancel_without_followup(self):
        cancel_event = threading.Event()
        end_date = date(2026, 8, 31)

        result = self.service.sync(
            "backfill",
            activity_days=5,
            end_date=end_date,
            cancel_event=cancel_event,
        )

        self.assertEqual(result["status"], "ok")
        self.reader.fetch_snapshot.assert_called_once_with(
            activity_days=5, end_date=end_date, cancel_event=cancel_event
        )
        self.daily_markers.mark.assert_not_called()
        self.followup.enqueue_after_sync.assert_not_called()

    def test_already_running_returns_without_mutating_owner_lock(self):
        self.lock.acquire()
        self.addCleanup(self.lock.release)

        result = self.service.sync("manual", activity_days=7)

        self.assertEqual(result, {"status": "already_running"})
        self.reader.fetch_snapshot.assert_not_called()
        self.assertTrue(self.lock.locked())

    def test_wait_for_existing_returns_new_snapshot_and_waits_for_performance(self):
        self.set_value("last_sync_at", "old")
        self.set_value("last_sync_activity_days", "14")
        self.lock.acquire()
        calls = 0

        def monotonic():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.set_value("last_sync_at", "new")
                self.lock.release()
            return float(calls)

        service = self.make_service(monotonic=monotonic, wait_seconds=10)
        result = service.sync(
            "manual",
            activity_days=7,
            wait_for_existing=True,
            wait_for_performance=True,
        )

        self.assertEqual(
            result,
            {
                "status": "ok",
                "waited_for_existing": True,
                "synced_at": "new",
                "activity_days": 14,
            },
        )
        self.followup.wait.assert_called_once_with(cancel_event=None)

    def test_wait_for_existing_redacts_persisted_error_before_raising(self):
        self.set_value("last_sync_at", "unchanged")
        self.set_value("last_sync_error", "secret provider detail")
        self.lock.acquire()
        calls = 0

        def monotonic():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.lock.release()
            return float(calls)

        service = self.make_service(monotonic=monotonic)
        with self.assertRaises(AppError) as raised:
            service.sync("manual", activity_days=7, wait_for_existing=True)

        self.assertEqual(raised.exception.reason, "provider_refresh_failed")
        self.assertIn("[REDACTED] provider detail", raised.exception.message)
        self.assertNotIn("secret", raised.exception.message)

    def test_cancellation_before_lock_has_no_provider_or_status_side_effect(self):
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(AppError) as raised:
            self.service.sync("manual", activity_days=7, cancel_event=cancel_event)

        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.reader.fetch_snapshot.assert_not_called()
        self.status_writer.write.assert_not_called()
        self.assertFalse(self.lock.locked())

    def test_provider_failure_records_redacted_error_and_releases_lock(self):
        self.reader.fetch_snapshot.side_effect = RuntimeError("secret outage")

        with self.assertRaisesRegex(RuntimeError, "secret outage"):
            self.service.sync("scheduled", activity_days=7)

        self.assertEqual(self.get_value("last_sync_error"), "[REDACTED] outage")
        failure = self.status_writer.write.call_args_list[-1]
        self.assertEqual(failure.args[1:4], ("error", "error", 100))
        self.assertEqual(failure.args[-1], "secret outage")
        self.logger.error.assert_called_once()
        self.assertEqual(self.get_value("sync_running"), "0")
        self.assertFalse(self.lock.locked())

    def test_restart_resumes_persisted_operation_identity_and_start_time(self):
        self.set_value("sync_running", "1")
        self.set_value("sync_operation_id", "resumed-operation")
        self.set_value("sync_operation_started_at", "before-restart")

        self.service.sync("startup", activity_days=7)

        self.assertEqual(
            self.status_writer.write.call_args_list[0].args[0], "resumed-operation"
        )
        self.assertEqual(self.get_value("sync_operation_started_at"), "before-restart")
        self.assertEqual(self.get_value("sync_running"), "0")

    def test_missing_api_key_fails_before_lock_and_provider_io(self):
        root = Path(self.temporary_directory.name)
        service = self.make_service(config=load_config(root, root, {}))

        with self.assertRaises(AppError) as raised:
            service.sync("manual", activity_days=7)

        self.assertEqual(raised.exception.status, 503)
        self.reader.fetch_snapshot.assert_not_called()
        self.assertFalse(self.lock.locked())


if __name__ == "__main__":
    unittest.main()
