"""The morning Body Battery record is derived from canonical data.

The refresh stores the fetched night and Body Battery samples, then derives the
before-sleep and after-waking levels from the canonical NIGHT period and the
BODY_BATTERY levels in the same unit of work. The result equals the record built
from the fetched payloads. A temporary database and synthetic Garmin payloads
only; no account, network or real data is used.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from support import temp_database

from backend.db import canonical_store, garmin_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.performance import morning_battery
from backend.performance.morning_battery_service import METHOD_ID, MorningBatteryStore
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
        self.manager = temp_database(
            self, "morning.db", row_factory=row_factory, schema=True
        )
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
        stored = self.store.current()
        assert stored is not None
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

    def test_values_are_derived_observations_not_view_entries(self) -> None:
        # #1686: the Garmin state view keeps only the refresh bookkeeping.
        records = levels(
            (SLEEP_START - timedelta(minutes=10), 38),
            (SLEEP_END + timedelta(minutes=20), 82),
        )
        self.persist(sleep_payload(), records)
        with self.manager.reader() as db:
            view = garmin_store.read_state(db)["morning_body_battery"]
            rows = canonical_store.derived_observation_rows(db, METHOD_ID)
        # Only the levels leave the view; the sleep bounds stay bookkeeping.
        for key in ("before_sleep", "morning"):
            self.assertNotIn(key, view)
        self.assertEqual(view["sleep_end_at"], SLEEP_END.isoformat())
        self.assertEqual(
            {(row["metric"], row["value"]) for row in rows},
            {("body_battery_before_sleep", 38.0), ("morning_body_battery", 82.0)},
        )

    def test_a_later_refresh_retires_the_nights_earlier_values(self) -> None:
        self.persist(
            sleep_payload(),
            levels(
                (SLEEP_START - timedelta(minutes=10), 38),
                (SLEEP_END + timedelta(minutes=20), 82),
            ),
        )
        stored = self.persist(
            sleep_payload(),
            levels(
                (SLEEP_START - timedelta(minutes=5), 36),
                (SLEEP_END + timedelta(minutes=10), 84),
            ),
        )
        with self.manager.reader() as db:
            rows = canonical_store.derived_observation_rows(db, METHOD_ID)
        self.assertEqual(
            (36, 84), (stored["before_sleep"]["value"], stored["morning"]["value"])
        )
        self.assertEqual(2, len(rows))

    def test_without_a_night_the_record_is_not_available(self) -> None:
        stored = self.persist({}, levels((SLEEP_END, 80)))
        self.assertEqual(stored["status"], "not_available_today")
        self.assertIsNone(stored["morning"])

    def test_a_night_without_samples_keeps_its_sleep_bounds(self) -> None:
        stored = self.persist(
            sleep_payload(), levels((SLEEP_END + timedelta(hours=3), 80))
        )
        self.assertEqual(stored["status"], "not_available_today")
        self.assertIsNone(stored["morning"])
        self.assertEqual(stored["sleep_end_at"], SLEEP_END.isoformat())

    def test_a_dropped_value_and_a_failed_retry_retire_the_nights_values(self) -> None:
        self.persist(sleep_payload(), levels((SLEEP_START - timedelta(minutes=10), 38)))
        failed = morning_battery.morning_body_battery_record(
            CHECKIN, {}, [], attempted_at=ATTEMPTED_AT
        )
        failed["error"] = {"message": "Garmin nicht erreichbar"}
        self.store.persist(CHECKIN, None, failed, [], {})
        stored = self.store.current()
        assert stored is not None
        with self.manager.reader() as db:
            rows = canonical_store.derived_observation_rows(db, METHOD_ID)
        self.assertEqual([], rows)
        self.assertIsNone(stored["before_sleep"])
        self.assertEqual({"message": "Garmin nicht erreichbar"}, stored["error"])

    def test_a_record_stored_before_derived_values_keeps_its_inline_values(
        self,
    ) -> None:
        legacy = {
            "sleep_date": CHECKIN.isoformat(),
            "status": "ready",
            "before_sleep": {"observed_at": "2026-10-24T21:50:00+00:00", "value": 38},
            "morning": {"observed_at": "2026-10-25T05:20:00+00:00", "value": 82},
        }
        with self.manager.unit_of_work() as db:
            GarminSnapshotWriter(
                KeyValueRepository(lambda: NOW), lambda: ZONE
            ).write_refresh(
                db,
                fetched_at=NOW,
                sections={},
                view={"morning_body_battery": legacy},
                windows={},
                allowed=frozenset(),
            )
        self.assertEqual(legacy, self.store.current())

    def test_the_stored_night_projects_a_canonical_night_period(self) -> None:
        self.persist(sleep_payload(), levels((SLEEP_END, 80)))
        with self.manager.reader() as db:
            (period,) = CanonicalTableReader().sleep_periods(db)
        self.assertEqual((period.start, period.end), (SLEEP_START, SLEEP_END))
        self.assertEqual(period.kind.value, "night")


if __name__ == "__main__":
    unittest.main()
