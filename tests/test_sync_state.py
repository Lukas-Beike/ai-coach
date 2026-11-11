from __future__ import annotations

import sqlite3
import unittest

import snapshot_seed
from provider_runtime_fakes import ACME_ID, acme_descriptor
from support import temp_database

from backend.db import row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.sync.provider_registry import ProviderRegistry
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
        self.backend = ConnectSpy()
        self.database_manager = temp_database(
            self,
            "sync-state.sqlite",
            backend=self.backend,
            row_factory=row_factory,
            schema=True,
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.snapshots = SnapshotRepository()
        self.repository = self.make_repository()

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
        self.assertEqual(self.repository.set_sync_period("other", 90, ALL_DAYS), 90)
        with self.database_manager.unit_of_work() as db:
            self.assertEqual(self.key_values.get(db, "other_sync_days"), "90")

    def test_sync_period_uses_injected_registry_and_defaults_for_registered_provider(
        self,
    ):
        repository = SyncStateRepository(
            self.database_manager,
            self.key_values,
            self.snapshots,
            lambda: NOW,
            registry=ProviderRegistry([acme_descriptor()]),
        )
        defaults = {ACME_ID: 14}

        self.assertEqual(repository.sync_period(ACME_ID, defaults, ALL_DAYS), 14)
        self.assertEqual(repository.set_sync_period(ACME_ID, 60, ALL_DAYS), 60)
        self.assertEqual(repository.sync_period(ACME_ID, defaults, ALL_DAYS), 60)
        with self.assertRaises(ValueError):
            repository.set_sync_period(ACME_ID, 61, ALL_DAYS)
        with self.assertRaises(KeyError):
            repository.sync_period("intervals", defaults, ALL_DAYS)

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

    def test_latest_snapshot_returns_the_stored_payload(self):
        self.assertIsNone(self.repository.latest_snapshot())
        snapshot = {"synced_at": NOW, "athlete": {"id": "fake"}}
        snapshot_seed.save_snapshot(self.repository, snapshot)
        self.assertEqual(self.repository.latest_snapshot(), snapshot)


if __name__ == "__main__":
    unittest.main()
