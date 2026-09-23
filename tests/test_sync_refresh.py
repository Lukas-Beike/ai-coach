import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.sync.refresh import (
    ProviderRefreshTracker,
    create_refresh_record,
    finish_refresh_record,
    retry_at,
    sync_job_error_class,
)


class SQLiteDatabaseManager:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE provider_refresh_history (id TEXT PRIMARY KEY, provider TEXT, area TEXT, "
            "operation_id TEXT, trigger TEXT, started_at TEXT, finished_at TEXT, phase TEXT, status TEXT, "
            "error_code TEXT, next_retry_at TEXT)"
        )

    @contextmanager
    def unit_of_work(self):
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


class CommitCheckingEventBuffer(StateEventBuffer):
    def __init__(self, connection):
        super().__init__()
        self.connection = connection

    def publish(self, event, payload=None):
        if self.connection.in_transaction:
            raise AssertionError("state event published before transaction commit")
        return super().publish(event, payload)


class SyncRefreshTests(unittest.TestCase):
    def test_sync_job_error_class_preserves_job_reasons_and_retry_classes(self):
        class ProviderError(Exception):
            def __init__(self, *, reason="", status=None):
                super().__init__(reason)
                self.reason = reason
                self.status = status

        cases = (
            (ProviderError(reason="unsupported_job"), "unsupported_job"),
            (ProviderError(reason="invalid_job_request"), "invalid_job_request"),
            (ProviderError(reason="invalid_job_resolution"), "invalid_job_resolution"),
            (TimeoutError("synthetic timeout"), "network_error"),
            (ProviderError(status=429), "rate_limited"),
            (RuntimeError("synthetic provider failure"), "temporary_error"),
        )
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(sync_job_error_class(error), expected)

    def make_tracker(self, now, *, retention_days=30, max_rows=200):
        manager = SQLiteDatabaseManager()
        self.addCleanup(manager.connection.close)
        events = CommitCheckingEventBuffer(manager.connection)
        identifiers = iter(f"refresh-{index}" for index in range(10))
        tracker = ProviderRefreshTracker(
            manager,
            events,
            lambda: now[0],
            lambda: next(identifiers),
            retention_days=retention_days,
            max_rows=max_rows,
        )
        return manager, events, tracker

    def test_retry_at_is_bounded_and_stops_for_configuration_errors(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        retry = retry_at(
            [{"status": "error", "error_code": "timeout"}],
            current_error_code="timeout",
            now=now,
            base_seconds=10,
            max_seconds=25,
        )
        self.assertEqual(retry, "2026-01-01T00:00:20+00:00")
        self.assertIsNone(
            retry_at(
                [],
                current_error_code="auth_required",
                now=now,
                base_seconds=10,
                max_seconds=25,
            )
        )

    def test_refresh_records_use_caller_owned_connection(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE provider_refresh_history (id TEXT, provider TEXT, area TEXT, operation_id TEXT, "
            "trigger TEXT, started_at TEXT, phase TEXT, status TEXT, finished_at TEXT, error_code TEXT, next_retry_at TEXT)"
        )
        create_refresh_record(
            db,
            refresh_id="refresh-1",
            provider="garmin",
            area="data",
            operation_id="op-1",
            trigger="test",
            started_at="2026-01-01T00:00:00+00:00",
        )
        provider_area = finish_refresh_record(
            db,
            refresh_id="refresh-1",
            finished_at="2026-01-01T00:01:00+00:00",
            phase="complete",
            status="success",
            error_code=None,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            base_seconds=10,
            max_seconds=25,
        )
        self.assertEqual(provider_area, ("garmin", "data"))
        self.assertEqual(
            db.execute("SELECT status FROM provider_refresh_history").fetchone()[0],
            "success",
        )
        self.assertIsNone(
            db.execute("SELECT next_retry_at FROM provider_refresh_history").fetchone()[
                0
            ]
        )
        db.close()

    def test_success_clears_retry_timestamp_after_previous_error(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE provider_refresh_history (id TEXT, provider TEXT, area TEXT, operation_id TEXT, "
            "trigger TEXT, started_at TEXT, phase TEXT, status TEXT, finished_at TEXT, error_code TEXT, next_retry_at TEXT)"
        )
        db.execute(
            "INSERT INTO provider_refresh_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "old",
                "garmin",
                "data",
                "op-old",
                "test",
                "2026-01-01T00:00:00+00:00",
                "complete",
                "error",
                "2026-01-01T00:01:00+00:00",
                "timeout",
                "2026-01-01T00:02:00+00:00",
            ),
        )
        create_refresh_record(
            db,
            refresh_id="refresh-2",
            provider="garmin",
            area="data",
            operation_id="op-2",
            trigger="test",
            started_at="2026-01-01T00:03:00+00:00",
        )
        finish_refresh_record(
            db,
            refresh_id="refresh-2",
            finished_at="2026-01-01T00:04:00+00:00",
            phase="complete",
            status="success",
            error_code=None,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            base_seconds=10,
            max_seconds=25,
        )
        self.assertIsNone(
            db.execute(
                "SELECT next_retry_at FROM provider_refresh_history WHERE id='refresh-2'"
            ).fetchone()[0]
        )
        db.close()

    def test_tracker_start_commits_running_record_and_publishes_loading(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        manager, events, tracker = self.make_tracker(now)

        refresh_id = tracker.start("garmin", "data", "op-1", "manual")

        self.assertEqual(refresh_id, "refresh-0")
        row = manager.connection.execute(
            "SELECT provider, area, operation_id, trigger, started_at, phase, status "
            "FROM provider_refresh_history WHERE id=?",
            (refresh_id,),
        ).fetchone()
        self.assertEqual(
            tuple(row),
            (
                "garmin",
                "data",
                "op-1",
                "manual",
                "2026-01-01T00:00:00+00:00",
                "queued",
                "running",
            ),
        )
        self.assertEqual(
            events.since()["events"][0]["data"],
            {
                "provider": "garmin",
                "area": "data",
                "status": "loading",
                "refresh_id": refresh_id,
            },
        )

    def test_tracker_finish_maps_statuses_and_sets_retry_from_finish_time(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        manager, events, tracker = self.make_tracker(now)
        partial_id = tracker.start("intervals", "activities", "op-1", "manual")
        now[0] += timedelta(minutes=1)
        tracker.finish(partial_id, "partial", "partial_data")

        partial = manager.connection.execute(
            "SELECT finished_at, phase, status, next_retry_at FROM provider_refresh_history WHERE id=?",
            (partial_id,),
        ).fetchone()
        self.assertEqual(
            tuple(partial),
            ("2026-01-01T00:01:00+00:00", "partial_data", "partial", None),
        )
        self.assertEqual(events.since()["events"][-1]["data"]["status"], "degraded")

        error_id = tracker.start("intervals", "activities", "op-2", "manual")
        now[0] += timedelta(minutes=1)
        tracker.finish(error_id, "error", "failed", error_code="network_error")
        error = manager.connection.execute(
            "SELECT finished_at, phase, status, error_code, next_retry_at "
            "FROM provider_refresh_history WHERE id=?",
            (error_id,),
        ).fetchone()
        self.assertEqual(
            tuple(error),
            (
                "2026-01-01T00:02:00+00:00",
                "failed",
                "error",
                "network_error",
                "2026-01-01T00:17:00+00:00",
            ),
        )
        self.assertEqual(events.since()["events"][-1]["data"]["status"], "error")

        success_id = tracker.start("garmin", "data", "op-3", "manual")
        tracker.finish(success_id, "success", "complete")
        self.assertEqual(events.since()["events"][-1]["data"]["status"], "ready")

    def test_tracker_finish_unknown_id_publishes_no_event(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        _, events, tracker = self.make_tracker(now)

        tracker.finish("missing", "success", "complete")

        self.assertEqual(events.since()["events"], [])

    def test_tracker_cleanup_enforces_retention_cutoff(self):
        now = [datetime(2026, 1, 10, tzinfo=timezone.utc)]
        manager, _, tracker = self.make_tracker(now, retention_days=2, max_rows=10)
        manager.connection.execute(
            "INSERT INTO provider_refresh_history "
            "(id, provider, area, operation_id, trigger, started_at, phase, status) "
            "VALUES ('expired', 'garmin', 'data', 'expired', 'test', ?, 'complete', 'success')",
            ("2026-01-07T00:00:00+00:00",),
        )
        manager.connection.execute(
            "INSERT INTO provider_refresh_history "
            "(id, provider, area, operation_id, trigger, started_at, phase, status) "
            "VALUES ('recent', 'garmin', 'data', 'recent', 'test', ?, 'complete', 'success')",
            ("2026-01-09T00:00:00+00:00",),
        )
        manager.connection.commit()

        tracker.start("garmin", "data", "op-new", "manual")

        ids = {
            row[0]
            for row in manager.connection.execute(
                "SELECT id FROM provider_refresh_history"
            ).fetchall()
        }
        self.assertEqual(ids, {"recent", "refresh-0"})

    def test_tracker_cleanup_enforces_row_limit(self):
        now = [datetime(2026, 1, 10, tzinfo=timezone.utc)]
        manager, _, tracker = self.make_tracker(now, max_rows=2)
        for refresh_id, started_at in (
            ("older", "2026-01-07T00:00:00+00:00"),
            ("newer", "2026-01-08T00:00:00+00:00"),
            ("newest", "2026-01-09T00:00:00+00:00"),
        ):
            manager.connection.execute(
                "INSERT INTO provider_refresh_history "
                "(id, provider, area, operation_id, trigger, started_at, phase, status) "
                "VALUES (?, 'garmin', 'data', ?, 'test', ?, 'complete', 'success')",
                (refresh_id, refresh_id, started_at),
            )
        manager.connection.commit()

        tracker.start("garmin", "data", "op-new", "manual")

        ids = {
            row[0]
            for row in manager.connection.execute(
                "SELECT id FROM provider_refresh_history"
            ).fetchall()
        }
        self.assertEqual(ids, {"newest", "refresh-0"})

    def test_error_code_preserves_provider_classifications(self):
        cases = (
            (AppError(429, "busy"), "rate_limited"),
            (AppError(503, "busy", reason="rate_limit_exceeded"), "rate_limited"),
            (AppError(403, "denied"), "auth_required"),
            (AppError(502, "HTTP 401 response"), "auth_required"),
            (AppError(400, "invalid input"), "invalid_configuration"),
            (AppError(503, "configuration missing"), "invalid_configuration"),
            (
                AppError(503, "offline", reason="not_configured"),
                "invalid_configuration",
            ),
            (
                AppError(503, "offline", reason="provider_network_error"),
                "network_error",
            ),
            (TimeoutError("timed out"), "network_error"),
            (AppError(502, "provider failed"), "provider_error"),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__, expected=expected):
                self.assertEqual(ProviderRefreshTracker.error_code(error), expected)


if __name__ == "__main__":
    unittest.main()
