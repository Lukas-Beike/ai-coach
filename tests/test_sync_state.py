from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.sync.state import SyncStateRepository

NOW = "2026-09-20T12:00:00+00:00"
DEFAULTS = {"intervals": 90, "garmin": 30}
ALL_DAYS = -1


class ConnectSpy:
    def __init__(self):
        self.connect_count = 0

    def connect(self, *args, **kwargs):
        self.connect_count += 1
        return sqlite3.connect(*args, **kwargs)


class SyncStateRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.backend = ConnectSpy()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "sync-state.sqlite",
            self.backend,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.snapshots = SnapshotRepository()
        self.repository = self.make_repository()

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def make_repository(self, key_values=None):
        return SyncStateRepository(
            self.database_manager,
            key_values or self.key_values,
            self.snapshots,
            lambda: NOW,
        )

    def test_sync_period_defaults_clamps_and_all_days(self):
        self.assertEqual(
            self.repository.sync_period("intervals", DEFAULTS, ALL_DAYS), 90
        )
        self.assertEqual(self.repository.sync_period("garmin", DEFAULTS, ALL_DAYS), 30)

        self.repository.set_sync_period("intervals", ALL_DAYS, ALL_DAYS)
        self.assertEqual(
            self.repository.sync_period("intervals", DEFAULTS, ALL_DAYS), ALL_DAYS
        )
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "garmin_sync_days", "1000")
            self.key_values.set(db, "intervals_sync_days", "broken")
        self.assertEqual(self.repository.sync_period("garmin", DEFAULTS, ALL_DAYS), 90)
        self.assertEqual(
            self.repository.sync_period("intervals", DEFAULTS, ALL_DAYS), 90
        )

    def test_set_sync_period_persists_valid_values_and_rejects_invalid_values(self):
        for source, value in (
            ("intervals", 365),
            ("garmin", ALL_DAYS),
            ("garmin", "42"),
        ):
            with self.subTest(source=source, value=value):
                self.assertEqual(
                    self.repository.set_sync_period(source, value, ALL_DAYS),
                    int(value),
                )
                self.assertEqual(
                    self.repository.sync_period(source, DEFAULTS, ALL_DAYS), int(value)
                )

        for source, value in (
            ("intervals", 366),
            ("garmin", 0),
            ("garmin", 91),
            ("intervals", "bad"),
        ):
            with (
                self.subTest(source=source, value=value),
                self.assertRaises(ValueError),
            ):
                self.repository.set_sync_period(source, value, ALL_DAYS)
        with self.assertRaises(KeyError):
            self.repository.sync_period("other", DEFAULTS, ALL_DAYS)
        self.assertEqual(
            self.repository.set_sync_period("other", 90, ALL_DAYS), 90
        )
        with self.database_manager.unit_of_work() as db:
            self.assertEqual(self.key_values.get(db, "other_sync_days"), "90")

    def test_cursor_defaults_and_update_use_existing_cursor_contract(self):
        self.assertEqual(
            self.repository.cursor("garmin", "data"),
            {
                "provider": "garmin",
                "stream": "data",
                "cursor": None,
                "high_water_mark": None,
                "updated_at": None,
            },
        )
        self.repository.update_cursor("g" * 40, "d" * 80, "c" * 130, "h" * 130)
        self.assertEqual(
            self.repository.cursor("g" * 40, "d" * 80),
            {
                "provider": "g" * 40,
                "stream": "d" * 80,
                "cursor": "c" * 120,
                "high_water_mark": "h" * 120,
                "updated_at": NOW,
            },
        )
        self.repository.update_cursor("garmin", "data", "next")
        self.assertEqual(
            self.repository.cursor("garmin", "data")["high_water_mark"], ""
        )

    def test_reads_reuse_outer_unit_of_work_connection(self):
        connect_count = self.backend.connect_count
        with self.database_manager.unit_of_work():
            self.assertEqual(
                self.repository.sync_period("intervals", DEFAULTS, ALL_DAYS), 90
            )
            self.repository.cursor("garmin", "data")
            self.assertIsNone(self.repository.latest_snapshot())
            self.assertEqual(self.backend.connect_count, connect_count)

    def test_latest_and_save_snapshot_full_and_performance_state(self):
        self.assertIsNone(self.repository.latest_snapshot())
        full = {"synced_at": "2026-09-20T10:00:00+00:00", "athlete": {"id": "fake"}}
        self.repository.save_snapshot(full, activity_days=45)
        self.assertEqual(self.repository.latest_snapshot(), full)
        with self.database_manager.reader() as db:
            self.assertEqual(self.key_values.get(db, "last_sync_at"), full["synced_at"])
            self.assertEqual(self.key_values.get(db, "last_sync_error"), "")
            self.assertEqual(self.key_values.get(db, "last_sync_activity_days"), "45")

        performance = {
            "synced_at": "2026-09-20T11:00:00+00:00",
            "athlete": {"id": "fake"},
        }
        self.repository.save_snapshot(performance, update_full_sync=False)
        self.assertEqual(self.repository.latest_snapshot(), performance)
        with self.database_manager.reader() as db:
            self.assertEqual(self.key_values.get(db, "last_sync_at"), full["synced_at"])
            self.assertEqual(
                self.key_values.get(db, "last_performance_refresh_at"),
                performance["synced_at"],
            )
            rows = db.execute("SELECT payload FROM snapshots ORDER BY id").fetchall()
        self.assertEqual(
            [json.loads(row["payload"]) for row in rows], [full, performance]
        )

    def test_snapshot_save_rolls_back_when_status_update_fails(self):
        class FailingKeyValues(KeyValueRepository):
            def set(self, db, key, value):
                if key == "last_sync_error":
                    raise RuntimeError("forced status write failure")
                super().set(db, key, value)

        failing_repository = self.make_repository(FailingKeyValues(lambda: NOW))
        with self.assertRaisesRegex(RuntimeError, "forced status write failure"):
            failing_repository.save_snapshot(
                {"synced_at": NOW, "athlete": {"id": "fake"}}, activity_days=7
            )
        self.assertIsNone(self.repository.latest_snapshot())
        with self.database_manager.reader() as db:
            for key in ("last_sync_at", "last_sync_error", "last_sync_activity_days"):
                self.assertIsNone(self.key_values.get(db, key))

    def test_save_view_preserves_sync_status_markers(self):
        full = {"synced_at": "2026-09-20T10:00:00+00:00", "athlete": {"id": "fake"}}
        self.repository.save_snapshot(full, activity_days=45)

        view = {"recent_activities": [{"id": "local-view"}]}
        self.repository.save_view(view)

        self.assertEqual(self.repository.latest_snapshot(), view)
        with self.database_manager.reader() as db:
            self.assertEqual(self.key_values.get(db, "last_sync_at"), full["synced_at"])
            self.assertEqual(self.key_values.get(db, "last_sync_activity_days"), "45")
            rows = db.execute(
                "SELECT payload, created_at FROM snapshots ORDER BY id"
            ).fetchall()
        self.assertEqual(json.loads(rows[-1]["payload"]), view)
        self.assertEqual(rows[-1]["created_at"], NOW)


if __name__ == "__main__":
    unittest.main()
