"""GarminSnapshotWriter: one write path for the Garmin element rows and canonical rows.

Temporary SQLite and mocked providers only. No Garmin account or token is used.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from backend.db import garmin_store
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.performance.morning_battery_service import MorningBatteryStore
from backend.providers.garmin import merge_weight_snapshots
from backend.sync.canonical_ingest import CanonicalIngestCounters
from backend.sync.garmin import activity_deletion_window
from backend.sync.garmin_snapshot_writer import (
    ANALYSIS_SOURCES,
    NUTRITION_SOURCES,
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


class WriteTests(WriterFixture):
    def test_write_returns_canonical_counters_and_stores_the_activity(self) -> None:
        counters = self.writer.write(self.db, payload())
        self.assertIsInstance(counters, CanonicalIngestCounters)
        self.assertEqual(counters.written, 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0], 1
        )

    def test_sections_are_stored_per_element_and_state_stays_small(self) -> None:
        value = payload(
            sleep=[{"calendarDate": "2026-10-08", "note": "Rübe"}],
            hrv=[{"calendarDate": "2026-10-08"}, {"calendarDate": "2026-10-09"}],
            custom_marker="kept",
        )
        self.writer.write(self.db, value)
        ids = sorted(
            row[0]
            for row in self.db.execute(
                "SELECT source_record_id FROM provider_records "
                "WHERE record_kind = 'health'"
            )
        )
        self.assertEqual(ids, ["hrv/2026-10-08", "hrv/2026-10-09", "sleep/2026-10-08"])
        state = garmin_store.read_state(self.db)
        self.assertEqual(state["custom_marker"], "kept")
        self.assertNotIn("sleep", state)
        view = garmin_store.read_view(self.db, {"sleep"})
        self.assertEqual(view["sleep"][0]["note"], "Rübe")

    def test_a_repeated_write_changes_no_row(self) -> None:
        value = payload(sleep=[{"calendarDate": "2026-10-08"}])
        self.writer.write(self.db, value)
        before = self.db.total_changes
        self.writer.write(self.db, value)
        # Only the state value and coverage bookkeeping may be touched.
        rows = self.db.execute(
            "SELECT COUNT(*) FROM provider_records WHERE record_kind = 'health'"
        ).fetchone()[0]
        self.assertEqual(rows, 1)
        self.assertLessEqual(self.db.total_changes - before, 4)

    def test_a_delta_leaves_sections_it_does_not_mention(self) -> None:
        self.writer.write(self.db, payload(sleep=[{"calendarDate": "2026-10-08"}]))
        self.writer.write(self.db, payload(hrv=[{"calendarDate": "2026-10-09"}]))
        self.assertEqual(
            garmin_store.section_names(self.db), frozenset({"sleep", "hrv"})
        )

    def test_sync_time_is_read_in_the_zone_from_the_provider(self) -> None:
        self.writer.write(self.db, payload())
        self.zone_provider.assert_called_once_with()
        fetched_at = self.db.execute(
            "SELECT fetched_at FROM provider_records"
        ).fetchone()[0]
        self.assertEqual(fetched_at, "2026-10-10T08:00:00+02:00")

    def test_payload_without_a_sync_time_still_stores_state(self) -> None:
        value = payload()
        del value["synced_at"]
        counters = self.writer.write(self.db, value)
        self.assertEqual(counters, CanonicalIngestCounters())
        self.assertNotIn("activities", garmin_store.read_state(self.db))

    def test_repeated_writes_never_delete_canonical_activities(self) -> None:
        self.writer.write(self.db, payload())
        self.writer.write(self.db, payload(activities=[]))
        state = self.db.execute("SELECT state FROM activity_records").fetchone()[0]
        self.assertEqual(state, "active")


def garmin_activity(identifier: int) -> dict[str, Any]:
    return {**payload()["activities"][0], "activityId": identifier}


def activity_states(db: sqlite3.Connection) -> dict[str, str]:
    return {
        row["provider_activity_id"]: row["state"]
        for row in db.execute(
            "SELECT provider_activity_id, state FROM activity_records"
        )
    }


class ActivityWindowTests(WriterFixture):
    def refresh(self, ids: list[int], windows: dict[str, Any]) -> None:
        self.writer.write_refresh(
            self.db,
            fetched_at=NOW,
            sections={"activities": [garmin_activity(item) for item in ids]},
            view={},
            windows=windows,
            allowed=ANALYSIS_SOURCES,
        )

    def test_a_complete_refresh_tombstones_the_activity_garmin_no_longer_returns(
        self,
    ) -> None:
        window = {"activities": (date(2026, 10, 1), date(2026, 10, 10))}
        self.refresh([1, 2], window)
        self.refresh([1], window)
        self.assertEqual(activity_states(self.db), {"1": "active", "2": "deleted"})

    def test_an_incomplete_refresh_deletes_no_activity(self) -> None:
        self.refresh([1, 2], {})
        self.refresh([1], {})
        self.assertEqual(activity_states(self.db), {"1": "active", "2": "active"})

    def test_a_complete_sync_tombstones_the_activity_garmin_no_longer_returns(
        self,
    ) -> None:
        sync = {
            "errors": [],
            "provider_sync": {
                "read_window": {"start": "2026-10-01", "end": "2026-10-10"},
                "pagination": {"activities": {"complete": True}},
            },
        }
        for ids in ([1, 2], [1]):
            value = payload(activities=[garmin_activity(item) for item in ids], **sync)
            counters = self.writer.write(
                self.db, value, deletion_window=activity_deletion_window(value)
            )
        self.assertEqual(counters.deleted, 1)
        self.assertEqual(activity_states(self.db), {"1": "active", "2": "deleted"})


class WeightWindowTests(WriterFixture):
    WINDOW = (date(2026, 10, 8), date(2026, 10, 9))

    def refresh(self, weighed: dict[str, int], window: Any) -> None:
        envelope = merge_weight_snapshots(
            [
                {
                    "dailyWeightSummaries": [
                        {
                            "summaryDate": day,
                            "latestWeight": {"calendarDate": day, "weight": grams},
                        }
                        for day, grams in weighed.items()
                    ]
                }
            ],
            garmin_store.read_view(self.db, {"weight"}).get("weight", []),
            window=window,
        )
        self.writer.write_refresh(
            self.db,
            fetched_at=NOW,
            sections={"weight": envelope},
            view={},
            windows={} if window is None else {"weight": window},
            allowed=NUTRITION_SOURCES,
        )

    def states(self) -> dict[str, str]:
        return {
            row["observed_on"]: row["state"]
            for row in self.db.execute(
                "SELECT observed_on, state FROM observations WHERE metric = 'weight'"
            )
        }

    def test_a_complete_window_retires_the_deleted_weigh_in_only(self) -> None:
        self.refresh(
            {"2026-10-01": 79000, "2026-10-08": 80000, "2026-10-09": 81900}, None
        )
        self.refresh({"2026-10-08": 80000}, self.WINDOW)

        self.assertEqual(
            self.states(),
            {"2026-10-01": "active", "2026-10-08": "active", "2026-10-09": "retired"},
        )
        rows = self.db.execute(
            "SELECT COUNT(*) FROM provider_records WHERE source_record_id LIKE 'weight/%'"
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_an_incomplete_refresh_retires_nothing(self) -> None:
        self.refresh({"2026-10-08": 80000, "2026-10-09": 81900}, None)
        self.refresh({"2026-10-08": 80000}, None)

        self.assertEqual(
            self.states(), {"2026-10-08": "active", "2026-10-09": "active"}
        )


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
        spy.write_refresh.assert_called_once()
        stored = garmin_store.read_state(self.db)
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
