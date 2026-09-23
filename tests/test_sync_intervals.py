"""Temporary-SQLite tests for post-fetch Intervals persistence."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.sync.intervals import IntervalsSnapshotService
from backend.sync.state import SyncStateRepository

NOW = "2026-09-20T08:00:00+00:00"
TODAY = date(2026, 9, 20)


class TrackingDatabaseManager(DatabaseManager):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.depth = 0
        self.connections: list[Any] = []

    @contextmanager
    def unit_of_work(self):
        with super().unit_of_work() as db:
            self.depth += 1
            self.connections.append(db)
            try:
                yield db
            finally:
                self.depth -= 1


class FakePlannedReconciler:
    def __init__(self, manager: TrackingDatabaseManager, fail: bool = False):
        self.manager = manager
        self.fail = fail
        self.calls: list[tuple[Any, Any, Any]] = []

    def reconcile(
        self,
        events: list[Any],
        *,
        calendar_start: str | None = None,
        calendar_end: str | None = None,
    ) -> dict[str, int]:
        with self.manager.unit_of_work() as db:
            self.calls.append((db, events, (calendar_start, calendar_end)))
            db.execute("INSERT INTO reconciled_test_rows(value) VALUES ('written')")
            if self.fail:
                raise RuntimeError("reconciliation failed")
        return {"imported": len(events), "updated": 0, "conflicts": 0}


class FakeLibraryRefresh:
    def __init__(self, manager: TrackingDatabaseManager, result: Any = None):
        self.manager = manager
        self.result = result if result is not None else {"workouts": 2}
        self.calls: list[dict[str, Any]] = []

    def refresh(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.manager.depth:
            raise AssertionError("remote library refresh ran inside a DB UOW")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeWorkoutLibrary:
    def __init__(self, entries: list[dict[str, Any]] | None = None):
        self.entries = entries or []

    def list(self) -> list[dict[str, Any]]:
        return self.entries


class IntervalsSnapshotServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = TrackingDatabaseManager(
            Path(self.temporary_directory.name) / "intervals.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.snapshot_rows = SnapshotRepository()
        self.sync_state = SyncStateRepository(
            self.manager, self.key_values, self.snapshot_rows, lambda: NOW
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute("CREATE TABLE reconciled_test_rows(value TEXT NOT NULL)")
        self.reconciler = FakePlannedReconciler(self.manager)
        self.refresh = FakeLibraryRefresh(self.manager)
        self.library = FakeWorkoutLibrary([{"id": "local-1"}])
        self.service = self.make_service()

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def make_service(
        self,
        *,
        reconciler: Any = None,
        refresh: Any = None,
        library: Any = None,
    ) -> IntervalsSnapshotService:
        return IntervalsSnapshotService(
            self.manager,
            self.key_values,
            self.sync_state,
            reconciler or self.reconciler,
            refresh or self.refresh,
            library or self.library,
            lambda value: value,
            lambda: datetime(2026, 9, 20, 8, tzinfo=timezone.utc),
            date(2026, 9, 1),
            3,
            -1,
        )

    def get_value(self, key: str) -> str | None:
        with self.manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def set_value(self, key: str, value: str) -> None:
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    @staticmethod
    def snapshot(**overrides: Any) -> dict[str, Any]:
        return {
            "synced_at": NOW,
            "upcoming_calendar": [{"id": "remote-event"}],
            "provider_sync": {
                "calendar_window": {"start": "2026-09-21", "end": "2026-09-30"},
                "pagination": {"activities": {"next": "cursor"}},
            },
            **overrides,
        }

    def test_current_snapshot_saves_full_sync_and_reconciles_initial_calendar(self):
        result, planned_import = self.service.store_snapshot(self.snapshot(), 14, None)

        self.assertEqual(result["synced_at"], NOW)
        self.assertEqual(planned_import, {"imported": 1, "updated": 0, "conflicts": 0})
        self.assertEqual(self.get_value("last_sync_at"), NOW)
        self.assertEqual(self.get_value("last_sync_activity_days"), "14")
        self.assertEqual(self.get_value("planned_units_initial_import_at"), NOW)
        self.assertEqual(self.reconciler.calls[0][1], [{"id": "remote-event"}])
        self.assertEqual(self.reconciler.calls[0][2], ("2026-09-21", "2026-09-30"))
        self.assertEqual(self.sync_state.latest_snapshot(), result)

    def test_historical_snapshot_merges_then_saves_without_changing_full_sync(self):
        current = self.snapshot(
            synced_at="current", raw_provider_data={"activities": [{"id": "current"}]}
        )
        self.sync_state.save_snapshot(current, activity_days=7)
        historical = self.snapshot(
            synced_at="historical",
            raw_provider_data={"activities": [{"id": "historical"}]},
        )

        result, planned_import = self.service.store_snapshot(
            historical, 30, date(2026, 8, 31)
        )

        self.assertEqual(result["synced_at"], "current")
        self.assertEqual(
            [item["id"] for item in result["raw_provider_data"]["activities"]],
            ["current", "historical"],
        )
        self.assertEqual(result["historical_sync"]["synced_at"], "historical")
        self.assertEqual(planned_import, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.get_value("last_sync_at"), "current")
        self.assertEqual(self.get_value("last_performance_refresh_at"), "current")
        self.assertEqual(self.reconciler.calls, [])

    def test_pending_repair_defers_import_and_does_not_write_marker(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO sync_jobs(id, provider, type, status, payload, requested_by, created_at, updated_at) "
                "VALUES ('repair', 'intervals', 'plan_push', 'queued', '{\"repair\":true}', 'test', ?, ?)",
                (NOW, NOW),
            )

        _, planned_import = self.service.store_snapshot(self.snapshot(), 14, None)

        self.assertEqual(
            planned_import,
            {"imported": 0, "updated": 0, "conflicts": 0, "deferred_for_repair": True},
        )
        self.assertEqual(self.reconciler.calls, [])
        self.assertIsNone(self.get_value("planned_units_initial_import_at"))

    def test_reconcile_and_import_marker_share_nested_connection_and_commit(self):
        self.service.store_snapshot(self.snapshot(), 14, None)

        self.assertIs(self.manager.connections[-2], self.manager.connections[-1])
        self.assertIs(self.reconciler.calls[0][0], self.manager.connections[-1])
        with self.manager.reader() as db:
            count = db.execute(
                "SELECT count(*) AS count FROM reconciled_test_rows"
            ).fetchone()["count"]
        self.assertEqual(count, 1)
        self.assertEqual(self.get_value("planned_units_initial_import_at"), NOW)

    def test_reconcile_failure_rolls_back_nested_writes_and_import_marker(self):
        failing = FakePlannedReconciler(self.manager, fail=True)
        service = self.make_service(reconciler=failing)

        with self.assertRaisesRegex(RuntimeError, "reconciliation failed"):
            service.store_snapshot(self.snapshot(), 14, None)

        with self.manager.reader() as db:
            count = db.execute(
                "SELECT count(*) AS count FROM reconciled_test_rows"
            ).fetchone()["count"]
        self.assertEqual(count, 0)
        self.assertIsNone(self.get_value("planned_units_initial_import_at"))

    def test_already_imported_calendar_skips_reconciliation(self):
        self.set_value("planned_units_initial_import_at", "earlier")

        _, planned_import = self.service.store_snapshot(self.snapshot(), 14, None)

        self.assertEqual(planned_import, {"imported": 0, "updated": 0, "conflicts": 0})
        self.assertEqual(self.reconciler.calls, [])

    def test_library_initial_refresh_succeeds_without_holding_database_unit(self):
        cancel_event = threading.Event()

        result = self.service.seed_workout_library("manual refresh", cancel_event)

        self.assertEqual(result, (2, None, 1))
        self.assertEqual(
            self.refresh.calls,
            [
                {
                    "reason": "Initialer Intervals.icu-Sync (manual refresh)",
                    "cancel_event": cancel_event,
                }
            ],
        )

    def test_library_refresh_is_skipped_when_marker_exists(self):
        self.set_value("last_library_sync_at", NOW)

        result = self.service.seed_workout_library("manual", None)

        self.assertEqual(result, (0, None, 1))
        self.assertEqual(self.refresh.calls, [])

    def test_library_refresh_failure_is_redacted_truncated_and_recorded(self):
        refresh = FakeLibraryRefresh(self.manager, RuntimeError("x" * 1200))
        service = IntervalsSnapshotService(
            self.manager,
            self.key_values,
            self.sync_state,
            self.reconciler,
            refresh,
            self.library,
            lambda value: f"safe:{value}",
            lambda: datetime(2026, 9, 20, 8, tzinfo=timezone.utc),
            date(2026, 9, 1),
            3,
            -1,
        )

        imported, error, count = service.seed_workout_library("scheduled", None)

        self.assertEqual((imported, count), (0, 1))
        self.assertEqual(len(error), 1000)
        self.assertTrue(error.startswith("safe:"))
        self.assertEqual(
            refresh.calls,
            [{"reason": "Initialer Intervals.icu-Sync (scheduled)"}],
        )
        self.assertEqual(self.get_value("last_library_sync_error"), error)

    def test_library_cancellation_propagates_without_recording_error(self):
        cancellation = AppError(499, "cancelled", reason="chat_cancelled")
        refresh = FakeLibraryRefresh(self.manager, cancellation)
        service = self.make_service(refresh=refresh)

        with self.assertRaises(AppError) as raised:
            service.seed_workout_library("manual", threading.Event())

        self.assertIs(raised.exception, cancellation)
        self.assertIsNone(self.get_value("last_library_sync_error"))

    def test_current_window_records_activity_wellness_and_compact_pagination(self):
        pagination = {"activities": {"next": "a"}, "wellness": 2}
        windows, returned_pagination = self.service.record_window(
            5, None, self.snapshot(provider_sync={"pagination": pagination})
        )

        self.assertEqual(
            windows,
            [(date(2026, 9, 16), date(2026, 9, 18)), (date(2026, 9, 19), TODAY)],
        )
        self.assertEqual(returned_pagination, pagination)
        for stream in ("activities", "wellness"):
            cursor = self.sync_state.cursor("intervals", stream)
            self.assertEqual(cursor["cursor"], TODAY.isoformat())
            self.assertEqual(cursor["high_water_mark"], NOW)
        self.assertIsNone(self.sync_state.cursor("intervals", "historical")["cursor"])
        self.assertEqual(self.get_value("last_sync_window_start"), "2026-09-16")
        self.assertEqual(self.get_value("last_sync_window_end"), TODAY.isoformat())
        self.assertEqual(self.get_value("last_sync_activity_days"), "5")
        self.assertEqual(
            self.get_value("last_sync_pagination"),
            '{"activities":{"next":"a"},"wellness":2}',
        )

    def test_historical_window_records_oldest_cursor(self):
        windows, _ = self.service.record_window(5, date(2026, 9, 15), self.snapshot())

        self.assertEqual(
            windows,
            [
                (date(2026, 9, 11), date(2026, 9, 13)),
                (date(2026, 9, 14), date(2026, 9, 15)),
            ],
        )
        self.assertEqual(
            self.sync_state.cursor("intervals", "historical")["cursor"],
            "2026-09-11",
        )
        self.assertEqual(
            self.sync_state.cursor("intervals", "activities")["cursor"],
            "2026-09-15",
        )

    def test_all_days_window_starts_at_configured_earliest_date(self):
        windows, _ = self.service.record_window(
            -1, None, self.snapshot(provider_sync={})
        )

        self.assertEqual(windows[0], (date(2026, 9, 1), date(2026, 9, 3)))
        self.assertEqual(windows[-1], (date(2026, 9, 19), TODAY))
        self.assertEqual(self.get_value("last_sync_window_start"), "2026-09-01")
        self.assertEqual(self.get_value("last_sync_window_end"), TODAY.isoformat())
        self.assertEqual(self.get_value("last_sync_pagination"), "{}")


if __name__ == "__main__":
    unittest.main()
