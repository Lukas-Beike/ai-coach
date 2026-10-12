"""GarminSnapshotWriter: one write path for the legacy snapshot and canonical rows.

Temporary SQLite and mocked providers only. No Garmin account or token is used.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.performance.morning_battery_service import MorningBatteryStore
from backend.sync.canonical_ingest import CanonicalIngestCounters
from backend.sync.garmin_snapshot_writer import (
    GARMIN_SNAPSHOT_KEY,
    GarminSnapshotWriter,
)

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-10-10T08:00:00+00:00"


def payload(**extra: Any) -> dict[str, Any]:
    return {
        "synced_at": "2026-10-10T08:00:00",
        "activities": [
            {
                "activityId": 910010,
                "activityName": "Rübe Ride",
                "activityType": {"typeKey": "cycling"},
                "startTimeLocal": "2026-10-08 07:15:00",
                "distance": 20000.0,
                "duration": 3600.0,
            }
        ],
        **extra,
    }


class WriterFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "writer.db")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        initialize_schema(self.db)
        self.db.commit()
        self.key_values = KeyValueRepository(lambda: NOW)
        self.zone_provider = Mock(return_value=ZONE)
        self.writer = GarminSnapshotWriter(self.key_values, self.zone_provider)

    def stored_snapshot(self) -> str:
        stored = self.key_values.get(self.db, GARMIN_SNAPSHOT_KEY)
        if stored is None:
            self.fail("garmin_snapshot was not stored")
        return stored


class WriteTests(WriterFixture):
    def test_write_returns_canonical_counters_and_stores_the_snapshot(self) -> None:
        counters = self.writer.write(self.db, payload())
        self.assertIsInstance(counters, CanonicalIngestCounters)
        self.assertEqual(counters.written, 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0], 1
        )

    def test_legacy_snapshot_is_compact_json_with_unicode_kept(self) -> None:
        value = payload()
        self.writer.write(self.db, value)
        stored = self.stored_snapshot()
        self.assertEqual(
            stored, json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
        self.assertIn("Rübe", stored)

    def test_sync_time_is_read_in_the_zone_from_the_provider(self) -> None:
        self.writer.write(self.db, payload())
        self.zone_provider.assert_called_once_with()
        fetched_at = self.db.execute("SELECT fetched_at FROM provider_records").fetchone()[0]
        self.assertEqual(fetched_at, "2026-10-10T08:00:00+02:00")

    def test_payload_without_a_sync_time_still_stores_the_legacy_snapshot(self) -> None:
        value = payload()
        del value["synced_at"]
        counters = self.writer.write(self.db, value)
        self.assertEqual(counters, CanonicalIngestCounters())
        self.assertIsNotNone(self.stored_snapshot())

    def test_repeated_writes_never_delete_canonical_activities(self) -> None:
        self.writer.write(self.db, payload())
        self.writer.write(self.db, payload(activities=[]))
        state = self.db.execute("SELECT state FROM activity_records").fetchone()[0]
        self.assertEqual(state, "active")


class BodyBatteryPathTests(WriterFixture):
    def test_body_battery_persist_goes_through_the_same_write_function(self) -> None:
        spy = Mock(wraps=self.writer)
        store = MorningBatteryStore(
            Mock(unit_of_work=lambda: self._uow()), self.key_values, spy
        )
        store.persist(
            date(2026, 10, 9),
            None,
            {"status": "ready", "sleep_date": "2026-10-09", "morning": {"value": 80}},
            None,
        )
        spy.write.assert_called_once()
        stored = json.loads(self.stored_snapshot())
        self.assertEqual(stored["morning_body_battery"]["sleep_date"], "2026-10-09")

    def _uow(self):
        from contextlib import contextmanager

        @contextmanager
        def unit_of_work():
            yield self.db
            self.db.commit()

        return unit_of_work()


if __name__ == "__main__":
    unittest.main()
