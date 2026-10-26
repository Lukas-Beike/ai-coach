"""The morning Body Battery record is derived from canonical data.

The refresh stores the fetched night and Body Battery samples, then derives the
before-sleep and after-waking levels from the canonical NIGHT period and the
BODY_BATTERY levels in the same unit of work. The result equals the record built
from the fetched payloads. A temporary database and synthetic Garmin payloads
only; no account, network or real data is used.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import DatabaseManager, garmin_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.performance import morning_battery
from backend.performance.morning_battery_service import MorningBatteryStore
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

NOW = "2026-10-25T07:00:00+00:00"
CHECKIN = date(2026, 10, 25)
ZONE = ZoneInfo("Europe/Berlin")
SLEEP_START = datetime(2026, 10, 24, 21, 30, tzinfo=UTC)
SLEEP_END = datetime(2026, 10, 25, 5, 15, tzinfo=UTC)
ATTEMPTED_AT = "2026-10-25T06:00:00+00:00"


def epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def sleep_payload() -> dict[str, Any]:
    return {
        "dailySleepDTO": {
            "calendarDate": CHECKIN.isoformat(),
            "sleepStartTimestampGMT": epoch_ms(SLEEP_START),
            "sleepEndTimestampGMT": epoch_ms(SLEEP_END),
            "sleepTimeSeconds": 26_000,
        },
        "sleepMovement": [{"startGMT": "ignored"}],
    }


def levels(*pairs: tuple[datetime, int]) -> list[dict[str, Any]]:
    return [
        {
            "calendarDate": CHECKIN.isoformat(),
            "charged": 60,
            "drained": 40,
            "bodyBatteryValuesArray": [
                [epoch_ms(moment), level] for moment, level in pairs
            ],
        }
    ]


class MorningBatteryCanonicalTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "morning.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        key_values = KeyValueRepository(lambda: NOW)
        writer = GarminSnapshotWriter(key_values, lambda: ZONE)
        self.store = MorningBatteryStore(
            self.manager, key_values, writer, CanonicalTableReader()
        )

    def persist(self, sleep: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
        record = morning_battery.morning_body_battery_record(
            CHECKIN, sleep, records, attempted_at=ATTEMPTED_AT
        )
        self.store.persist(CHECKIN, None, record, records, sleep)
        with self.manager.reader() as db:
            stored = garmin_store.read_state(db)["morning_body_battery"]
        return stored

    def test_canonical_record_equals_the_payload_record(self) -> None:
        records = levels(
            (SLEEP_START - timedelta(hours=5), 70),
            (SLEEP_START - timedelta(hours=1), 41),
            (SLEEP_START - timedelta(minutes=10), 38),
            (SLEEP_END + timedelta(minutes=20), 82),
            (SLEEP_END + timedelta(minutes=50), 80),
            (SLEEP_END + timedelta(hours=2), 79),
        )
        expected = morning_battery.morning_body_battery_record(
            CHECKIN, sleep_payload(), records, attempted_at=ATTEMPTED_AT
        )
        stored = self.persist(sleep_payload(), records)
        self.assertEqual(stored, {**expected, "attempts": 1})
        self.assertEqual(stored["status"], "ready")
        self.assertEqual(stored["before_sleep"]["value"], 38)
        self.assertEqual(stored["morning"]["value"], 82)

    def test_without_a_night_the_record_is_not_available(self) -> None:
        stored = self.persist({}, levels((SLEEP_END, 80)))
        self.assertEqual(stored["status"], "not_available_today")
        self.assertIsNone(stored["morning"])

    def test_the_stored_night_projects_a_canonical_night_period(self) -> None:
        self.persist(sleep_payload(), levels((SLEEP_END, 80)))
        with self.manager.reader() as db:
            (period,) = CanonicalTableReader().sleep_periods(db)
        self.assertEqual((period.start, period.end), (SLEEP_START, SLEEP_END))
        self.assertEqual(period.kind.value, "night")


if __name__ == "__main__":
    unittest.main()
