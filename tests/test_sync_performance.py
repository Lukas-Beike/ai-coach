from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from backend.config import load_config
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import COACH_ABORTED_ERROR, INTERVALS_API_KEY_ERROR, AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.performance import (
    PerformanceRefreshFollowupService,
    PerformanceRefreshService,
)
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository

NOW = "2026-09-20T12:00:00+00:00"


class ConnectSpy:
    def __init__(self):
        self.connect_count = 0

    def connect(self, *args, **kwargs):
        self.connect_count += 1
        return sqlite3.connect(*args, **kwargs)


class RecordingMaintenanceGate(MaintenanceGate):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.failure = None

    @contextmanager
    def operation(self):
        self.events.append("maintenance.enter")
        if self.failure is not None:
            raise self.failure
        try:
            with super().operation():
                yield
        finally:
            self.events.append("maintenance.exit")


class RecordingRefreshTracker:
    def __init__(self, events):
        self.events = events
        self.failure = None
        self.finishes = []

    def start(self, provider, area, operation_id, trigger):
        self.events.append(("observer.start", provider, area))
        if self.failure is not None:
            raise self.failure
        return "refresh-id"

    def finish(self, refresh_id, status, phase, *, error_code=None):
        self.events.append(("observer.finish", status, phase))
        self.finishes.append((refresh_id, status, phase, error_code))


class RecordingProviderResyncGate(ProviderResyncGate):
    def __init__(self, events):
        super().__init__("Intervals.icu")
        self.events = events
        self.failure = None

    @contextmanager
    def operation(self):
        self.events.append("provider_gate.enter")
        if self.failure is not None:
            raise self.failure
        try:
            with super().operation():
                yield
        finally:
            self.events.append("provider_gate.exit")


class PerformanceRefreshServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.backend = ConnectSpy()
        self.database_manager = DatabaseManager(
            root / "performance.sqlite", self.backend, row_factory=row_factory
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.snapshot_repository = SnapshotRepository()
        self.sync_state = SyncStateRepository(
            self.database_manager,
            self.key_values,
            self.snapshot_repository,
            lambda: NOW,
        )
        self.config = load_config(root, root, {"INTERVALS_API_KEY": "fake-key"})
        self.lock = threading.Lock()
        self.events = Mock()
        self.logger = Mock(spec=logging.Logger)
        self.operation_events = []
        self.maintenance_gate = RecordingMaintenanceGate(self.operation_events)
        self.refresh_tracker = RecordingRefreshTracker(self.operation_events)
        self.observer = SyncOperationObserver(
            self.refresh_tracker, self.maintenance_gate, self.logger
        )
        self.observer_scopes = []
        observe = self.observer.observe

        @contextmanager
        def capture_observe(*args, **kwargs):
            with observe(*args, **kwargs) as scope:
                self.observer_scopes.append(scope)
                yield scope

        self.observer.observe = capture_observe
        self.provider_resync_gate = RecordingProviderResyncGate(self.operation_events)
        self.provider = Mock()
        self.service = self.make_service()

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def make_service(
        self,
        *,
        config=None,
        provider=None,
        events=None,
        lock=None,
        logger=None,
        redactor=None,
        observer=None,
        provider_resync_gate=None,
    ):
        return PerformanceRefreshService(
            config or self.config,
            self.database_manager,
            self.sync_state,
            self.key_values,
            provider or self.provider,
            events or self.events,
            redactor or (lambda text: text),
            logger or self.logger,
            observer or self.observer,
            provider_resync_gate or self.provider_resync_gate,
            lock if lock is not None else self.lock,
        )

    def seed_snapshot(self):
        snapshot = {
            "synced_at": "2026-09-20T10:00:00+00:00",
            "athlete": {"id": "old-athlete"},
            "recent_activities": [{"id": "activity-1"}],
            "recent_wellness": [{"id": "wellness-old"}],
            "raw_provider_data": {
                "athlete": {"id": "old-athlete"},
                "activities": [{"id": "activity-1"}],
                "wellness": [],
            },
            "provider_sync": {"pagination": {"activities": {"cursor": "old"}}},
        }
        self.sync_state.save_snapshot(snapshot)
        return snapshot

    def get_value(self, key):
        with self.database_manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def performance_response(self):
        return {
            "synced_at": "2026-09-20T11:00:00+00:00",
            "athlete": {"id": "new-athlete"},
            "recent_wellness": [{"id": "wellness-new"}],
            "raw_provider_data": {
                "athlete": {"id": "new-athlete"},
                "wellness": [{"id": "wellness-new"}],
            },
        }

    def test_missing_api_key_raises_app_error_without_acquiring_lock(self):
        service = self.make_service(
            config=load_config(
                Path(self.temporary_directory.name),
                Path(self.temporary_directory.name),
                {},
            )
        )

        with self.assertRaises(AppError) as raised:
            service.refresh()

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(str(raised.exception), INTERVALS_API_KEY_ERROR)
        self.assertEqual(
            self.operation_events,
            [
                "maintenance.enter",
                ("observer.start", "intervals", "performance"),
                "provider_gate.enter",
                "provider_gate.exit",
                ("observer.finish", "error", "failed"),
                "maintenance.exit",
            ],
        )
        self.assertFalse(self.lock.locked())
        self.provider.fetch_performance_snapshot.assert_not_called()

    def test_busy_returns_already_running_without_changing_markers(self):
        self.lock.acquire()
        try:
            self.assertEqual(self.service.refresh(), {"status": "already_running"})
            self.assertEqual(
                self.observer_scopes[-1].result, {"status": "already_running"}
            )
            self.assertIsNone(self.get_value("performance_refresh_running"))
            self.provider.fetch_performance_snapshot.assert_not_called()
        finally:
            self.lock.release()

    def test_success_fetches_latest_and_atomically_merges_saves_and_publishes(self):
        original = self.seed_snapshot()
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "last_performance_error", "old error")

        self.provider.fetch_performance_snapshot.return_value = (
            self.performance_response()
        )
        latest_connections = []
        save_connections = []
        original_latest = self.sync_state.latest_snapshot
        original_save = self.sync_state.save_snapshot

        def tracked_latest():
            latest_connections.append(self.database_manager._unit_of_work.get())
            return original_latest()

        def tracked_save(snapshot, update_full_sync=True, activity_days=None):
            save_connections.append(self.database_manager._unit_of_work.get())
            return original_save(snapshot, update_full_sync, activity_days)

        self.sync_state.latest_snapshot = tracked_latest
        self.sync_state.save_snapshot = tracked_save
        connection_count = self.backend.connect_count

        result = self.service.refresh()

        self.assertEqual(
            result, {"status": "ok", "refreshed_at": "2026-09-20T11:00:00+00:00"}
        )
        self.assertEqual(self.observer_scopes[-1].result, result)
        self.provider.fetch_performance_snapshot.assert_called_once_with(original)
        merged = self.sync_state.latest_snapshot()
        self.assertEqual(merged["athlete"], {"id": "new-athlete"})
        self.assertEqual(merged["recent_activities"], [{"id": "activity-1"}])
        self.assertEqual(merged["recent_wellness"][0], {"id": "wellness-new"})
        self.assertEqual(self.get_value("last_performance_error"), "")
        self.assertEqual(self.get_value("last_sync_at"), original["synced_at"])
        self.assertEqual(
            self.get_value("last_performance_refresh_at"), merged["synced_at"]
        )
        self.assertEqual(self.get_value("performance_refresh_running"), "0")
        self.events.publish.assert_called_once_with(
            "provider",
            {"provider": "intervals", "area": "performance", "status": "ready"},
        )
        self.assertIsNone(latest_connections[0])
        self.assertIsNotNone(latest_connections[1])
        self.assertEqual(save_connections, [latest_connections[1]])
        self.assertEqual(self.backend.connect_count, connection_count)
        self.assertFalse(self.lock.locked())

    def test_observer_and_resync_gate_wrap_the_inner_refresh_in_order(self):
        self.provider.fetch_performance_snapshot.side_effect = lambda existing: (
            self.operation_events.append("provider.fetch")
            or self.performance_response()
        )

        self.service.refresh()

        self.assertEqual(
            self.operation_events,
            [
                "maintenance.enter",
                ("observer.start", "intervals", "performance"),
                "provider_gate.enter",
                "provider.fetch",
                "provider_gate.exit",
                ("observer.finish", "success", "complete"),
                "maintenance.exit",
            ],
        )

    def test_observer_start_and_gate_failures_propagate_without_lock_leaks(self):
        observer_error = RuntimeError("observer unavailable")
        self.refresh_tracker.failure = observer_error
        with self.assertRaisesRegex(RuntimeError, "observer unavailable"):
            self.service.refresh()
        self.assertEqual(
            self.operation_events,
            [
                "maintenance.enter",
                ("observer.start", "intervals", "performance"),
                "maintenance.exit",
            ],
        )
        self.assertFalse(self.lock.locked())
        self.provider.fetch_performance_snapshot.assert_not_called()

        self.operation_events.clear()
        self.refresh_tracker.failure = None
        gate_error = AppError(409, "resync active")
        self.provider_resync_gate.failure = gate_error
        with self.assertRaisesRegex(AppError, "resync active"):
            self.service.refresh()
        self.assertEqual(
            self.operation_events,
            [
                "maintenance.enter",
                ("observer.start", "intervals", "performance"),
                "provider_gate.enter",
                ("observer.finish", "error", "failed"),
                "maintenance.exit",
            ],
        )
        self.assertFalse(self.lock.locked())
        self.provider.fetch_performance_snapshot.assert_not_called()

    def test_maintenance_observer_failure_propagates_before_gate(self):
        maintenance_error = AppError(503, "maintenance active")
        self.maintenance_gate.failure = maintenance_error

        with self.assertRaisesRegex(AppError, "maintenance active"):
            self.service.refresh()

        self.assertEqual(self.operation_events, ["maintenance.enter"])
        self.assertFalse(self.lock.locked())
        self.provider.fetch_performance_snapshot.assert_not_called()

    def test_running_marker_is_set_before_provider_io_and_cleared_after_success(self):
        self.provider.fetch_performance_snapshot.side_effect = lambda existing: (
            self._check_running_and_return(existing)
        )

        self.service.refresh()

        self.assertEqual(self.get_value("performance_refresh_running"), "0")

    def test_running_uses_single_flight_lock_not_stale_persisted_marker(self):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "performance_refresh_running", "1")

        self.assertFalse(self.service.running())
        self.assertEqual(self.get_value("performance_refresh_running"), "1")

    def _check_running_and_return(self, existing):
        self.assertTrue(self.service.running())
        self.assertEqual(self.get_value("performance_refresh_running"), "1")
        self.assertIsNone(self.database_manager._unit_of_work.get())
        return self.performance_response()

    def test_concurrent_refresh_is_single_flight(self):
        entered_provider = threading.Event()
        release_provider = threading.Event()
        results = []
        errors = []

        def fetch(_existing):
            entered_provider.set()
            if not release_provider.wait(5):
                raise TimeoutError("test did not release provider")
            return self.performance_response()

        self.provider.fetch_performance_snapshot.side_effect = fetch

        def run_refresh():
            try:
                results.append(self.service.refresh())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        worker = threading.Thread(target=run_refresh)
        worker.start()
        self.assertTrue(entered_provider.wait(5))
        self.assertEqual(self.service.refresh(), {"status": "already_running"})
        release_provider.set()
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(
            results, [{"status": "ok", "refreshed_at": "2026-09-20T11:00:00+00:00"}]
        )
        self.assertFalse(self.lock.locked())

    def test_failure_is_redacted_truncated_persisted_and_logged_safely(self):
        secret_message = "credential=SECRET " + ("x" * 1100)
        self.provider.fetch_performance_snapshot.side_effect = RuntimeError(
            secret_message
        )
        service = self.make_service(
            redactor=lambda text: text.replace("SECRET", "[redacted]")
        )

        with self.assertRaisesRegex(RuntimeError, "SECRET"):
            service.refresh()

        persisted = self.get_value("last_performance_error")
        self.assertEqual(len(persisted), 1000)
        self.assertNotIn("SECRET", persisted)
        self.assertEqual(self.get_value("performance_refresh_running"), "0")
        self.assertFalse(self.lock.locked())
        logged = self.logger.error.call_args.kwargs["exc_info"][1]
        self.assertEqual(str(logged), persisted)
        self.assertNotIn("SECRET", str(logged))

    def test_provider_storage_and_event_failures_reset_marker_and_release_lock(self):
        cases = ("provider", "storage", "event")
        for failure in cases:
            with self.subTest(failure=failure):
                self.provider.fetch_performance_snapshot.reset_mock()
                self.provider.fetch_performance_snapshot.side_effect = None
                self.events.publish.side_effect = None
                if failure == "provider":
                    self.provider.fetch_performance_snapshot.side_effect = RuntimeError(
                        "provider down"
                    )
                else:
                    self.provider.fetch_performance_snapshot.return_value = (
                        self.performance_response()
                    )
                service = self.make_service()
                storage_patch = (
                    patch.object(
                        self.snapshot_repository,
                        "save",
                        side_effect=OSError("disk unavailable"),
                    )
                    if failure == "storage"
                    else patch.object(
                        self.snapshot_repository,
                        "save",
                        wraps=self.snapshot_repository.save,
                    )
                )
                with storage_patch:
                    if failure == "event":
                        self.events.publish.side_effect = RuntimeError(
                            "event buffer unavailable"
                        )
                    expected_error = OSError if failure == "storage" else RuntimeError
                    with self.assertRaises(expected_error):
                        service.refresh()

                self.assertEqual(self.get_value("performance_refresh_running"), "0")
                self.assertFalse(self.lock.locked())
                self.assertTrue(self.get_value("last_performance_error"))

    def test_save_failure_rolls_back_snapshot_and_performance_marker(self):
        original = self.seed_snapshot()
        self.provider.fetch_performance_snapshot.return_value = (
            self.performance_response()
        )
        save_original = self.snapshot_repository.save
        with (
            patch.object(
                self.snapshot_repository,
                "save",
                side_effect=lambda *args, **kwargs: self._save_then_fail(
                    save_original, *args, **kwargs
                ),
            ),
            self.assertRaisesRegex(OSError, "disk unavailable"),
        ):
            self.service.refresh()

        self.assertEqual(self.sync_state.latest_snapshot(), original)
        self.assertIsNone(self.get_value("last_performance_refresh_at"))
        self.assertEqual(self.get_value("last_performance_error"), "disk unavailable")
        self.assertEqual(self.get_value("performance_refresh_running"), "0")
        self.assertFalse(self.lock.locked())

    def _save_then_fail(self, original, *args, **kwargs):
        original(*args, **kwargs)
        raise OSError("disk unavailable")


class FakeClock:
    def __init__(self, database_manager, after_sleep=None):
        self.database_manager = database_manager
        self.after_sleep = after_sleep
        self.now = 0.0
        self.sleeps = []
        self.open_transactions_during_sleep = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.open_transactions_during_sleep.append(
            self.database_manager._unit_of_work.get()
        )
        self.now += seconds
        if self.after_sleep is not None:
            self.after_sleep()


class PerformanceRefreshFollowupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.database_manager = DatabaseManager(
            root / "performance-followup.sqlite", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.database_manager.close)
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.config = load_config(root, root, {"INTERVALS_API_KEY": "fake-key"})
        self.queue = Mock(spec=SyncJobQueueService)
        self.queue.pending_performance_job_id.return_value = None
        self.performance_refresh = Mock(spec=PerformanceRefreshService)
        self.performance_refresh.running.return_value = False
        self.logger = Mock(spec=logging.Logger)
        self.clock = FakeClock(self.database_manager)
        self.service = self.make_service()

    def make_service(
        self,
        *,
        config=None,
        wait_seconds=120.0,
        poll_seconds=1.0,
        clock=None,
    ):
        active_clock = clock or self.clock
        return PerformanceRefreshFollowupService(
            config or self.config,
            self.queue,
            self.performance_refresh,
            self.database_manager,
            self.key_values,
            self.logger,
            monotonic=active_clock.monotonic,
            sleep=active_clock.sleep,
            wait_seconds=wait_seconds,
            poll_seconds=poll_seconds,
        )

    def set_value(self, key, value):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def app_error(self, callback):
        with self.assertRaises(AppError) as raised:
            callback()
        return raised.exception

    def test_enqueue_skips_without_api_key_or_while_refresh_is_running(self):
        no_key = self.make_service(
            config=load_config(
                Path(self.temporary_directory.name),
                Path(self.temporary_directory.name),
                {},
            )
        )
        self.assertIsNone(no_key.enqueue_after_sync("complete"))
        self.queue.enqueue.assert_not_called()

        self.performance_refresh.running.return_value = True
        self.assertIsNone(self.service.enqueue_after_sync("complete"))
        self.queue.enqueue.assert_not_called()

    def test_enqueue_uses_scheduler_and_existing_reason_envelope(self):
        expected = {"id": "job-1", "status": "queued"}
        self.queue.enqueue.return_value = expected

        result = self.service.enqueue_after_sync("Intervals-Aktualisierung")

        self.assertIs(result, expected)
        self.queue.enqueue.assert_called_once_with(
            "intervals",
            "performance_refresh",
            {
                "reason": "Automatische Folgeaktualisierung nach "
                "Intervals-Aktualisierung"
            },
            requested_by="scheduler",
        )

    def test_enqueue_queue_failure_is_swallowed_and_logged_without_exception(self):
        self.queue.enqueue.side_effect = RuntimeError("SECRET provider detail")

        self.assertIsNone(self.service.enqueue_after_sync("sync"))

        self.logger.warning.assert_called_once_with(
            "Automatic Intervals performance refresh could not be queued",
            extra={"event": "automatic_performance_refresh_queue_failed"},
        )
        self.assertNotIn("SECRET", repr(self.logger.warning.call_args))

    def test_wait_returns_completed_explicit_job_without_pending_lookup(self):
        completed = {"id": "job-1", "status": "completed", "result": {"ok": True}}
        self.queue.state.return_value = completed

        self.assertEqual(self.service.wait("job-1"), completed)

        self.queue.state.assert_called_once_with("job-1")
        self.queue.pending_performance_job_id.assert_not_called()
        self.assertEqual(self.clock.sleeps, [])

    def test_wait_follows_pending_job_to_completed(self):
        completed = {"id": "pending-1", "status": "completed"}
        self.queue.pending_performance_job_id.return_value = "pending-1"
        self.queue.state.return_value = completed

        self.assertEqual(self.service.wait(), completed)

        self.queue.pending_performance_job_id.assert_called_once_with()
        self.queue.state.assert_called_once_with("pending-1")

    def test_wait_maps_failed_and_partial_jobs_to_provider_refresh_error(self):
        for status in ("failed", "partial"):
            with self.subTest(status=status):
                self.queue.state.return_value = {"id": "job-1", "status": status}
                error = self.app_error(lambda: self.service.wait("job-1"))
                self.assertEqual(error.status, 503)
                self.assertEqual(error.reason, "provider_refresh_failed")
                self.assertEqual(
                    error.message,
                    "Die aktuelle Intervals.icu-Leistungsaktualisierung ist fehlgeschlagen.",
                )

    def test_wait_returns_idle_when_no_job_or_markers_exist(self):
        self.assertIsNone(self.service.wait())
        self.queue.pending_performance_job_id.assert_called_once_with()
        self.assertEqual(self.clock.sleeps, [])

    def test_wait_respects_running_marker_then_returns_idle(self):
        self.set_value("performance_refresh_running", "1")
        self.clock.after_sleep = lambda: self.set_value(
            "performance_refresh_running", "0"
        )

        self.assertIsNone(self.service.wait())

        self.assertEqual(self.clock.sleeps, [1.0])
        self.assertEqual(self.clock.open_transactions_during_sleep, [None])

    def test_wait_raises_on_last_error_unless_running_marker_is_active(self):
        self.set_value("last_performance_error", "sanitized previous error")
        error = self.app_error(self.service.wait)
        self.assertEqual(error.status, 503)
        self.assertEqual(error.reason, "provider_refresh_failed")

        self.set_value("last_performance_error", "")
        self.set_value("performance_refresh_running", "1")
        self.clock.after_sleep = lambda: self.set_value(
            "performance_refresh_running", "0"
        )
        self.assertIsNone(self.service.wait())

    def test_wait_times_out_with_bounded_sleeps_and_no_open_database_unit(self):
        self.set_value("performance_refresh_running", "1")
        service = self.make_service(wait_seconds=2.5, poll_seconds=2.0)

        error = self.app_error(service.wait)

        self.assertEqual(error.status, 503)
        self.assertEqual(error.reason, "provider_busy")
        self.assertEqual(
            error.message,
            "Die aktuelle Intervals.icu-Leistungsaktualisierung ist noch nicht abgeschlossen.",
        )
        self.assertEqual(self.clock.sleeps, [2.0, 0.5])
        self.assertTrue(all(0 < delay <= 2.0 for delay in self.clock.sleeps))
        self.assertEqual(sum(self.clock.sleeps), 2.5)
        self.assertEqual(self.clock.open_transactions_during_sleep, [None, None])

    def test_wait_cancellation_is_checked_before_first_poll(self):
        cancel_event = threading.Event()
        cancel_event.set()

        error = self.app_error(lambda: self.service.wait(cancel_event=cancel_event))

        self.assertEqual(error.status, 499)
        self.assertEqual(error.message, COACH_ABORTED_ERROR)
        self.assertEqual(error.reason, "chat_cancelled")
        self.queue.pending_performance_job_id.assert_not_called()

    def test_wait_cancellation_is_checked_again_after_sleep_before_poll(self):
        self.set_value("performance_refresh_running", "1")
        cancel_event = threading.Event()
        self.clock.after_sleep = cancel_event.set

        error = self.app_error(lambda: self.service.wait(cancel_event=cancel_event))

        self.assertEqual(error.status, 499)
        self.assertEqual(error.reason, "chat_cancelled")
        self.queue.pending_performance_job_id.assert_called_once_with()
        self.assertEqual(self.clock.sleeps, [1.0])


if __name__ == "__main__":
    unittest.main()
