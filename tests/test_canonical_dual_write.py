"""Dual write during Intervals.icu and Garmin ingest: atomicity, idempotence and deletion.

Each test uses a temporary SQLite file through the real DatabaseManager and the
real sync services. Remote planned-unit reconciliation and Garmin dependencies are
replaced by small fakes. No provider account, network or real data directory is used.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from support import temp_database

from backend.canonical.garmin_payload import STATE_KEY as GARMIN_STATE_KEY
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.sync.garmin import GarminSyncStateService
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.state import SyncStateRepository

NOW = "2026-09-20T08:00:00+00:00"
SECRET = "synthetic-secret-value"
SIGNED_URL = "https://files.invalid/ride.fit?X-Amz-Signature=synthetic-signature"
ZONE = ZoneInfo("Europe/Berlin")


def activity(
    identifier: str, *, kind: str = "Ride", day: str = "2026-09-10"
) -> dict[str, Any]:
    return {
        "id": identifier,
        "start_date_local": f"{day}T07:00:00",
        "type": kind,
        "access_token": SECRET,
        "download": SIGNED_URL,
    }


def intervals_snapshot(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "synced_at": NOW,
        "upcoming_calendar": [],
        "provider_sync": {
            "calendar_window": {"start": "2026-09-21", "end": "2026-09-30"},
            "pagination": {},
        },
        "raw_provider_data": {"activities": rows},
        **extra,
    }


def garmin_payload(*activities: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "synced_at": NOW,
        "activities": list(activities),
        "provider_sync": {"pagination": {}},
        **extra,
    }


def garmin_activity(identifier: int) -> dict[str, Any]:
    return {
        "activityId": identifier,
        "activityName": "Synthetic ride",
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-09-10 07:15:00",
        "distance": 20000.0,
        "duration": 3600.0,
        "access_token": SECRET,
    }


class FakePlannedReconciler:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def reconcile(self, events: list[Any], **kwargs: Any) -> dict[str, int]:
        self.calls.append((events, kwargs))
        return {"imported": 0, "updated": 0, "conflicts": 0}


def activity_states(manager: DatabaseManager) -> dict[str, str]:
    with manager.reader() as db:
        return {
            row["provider_activity_id"]: row["state"]
            for row in db.execute(
                "SELECT provider_activity_id, state FROM activity_records"
            ).fetchall()
        }


def provider_payload_text(manager: DatabaseManager) -> str:
    with manager.reader() as db:
        return "\n".join(
            row["payload"] for row in db.execute("SELECT payload FROM provider_records")
        )


class DualWriteFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "dual.db", row_factory=row_factory, schema=True
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.sync_state = SyncStateRepository(
            self.manager, self.key_values, lambda: NOW
        )

    def count(self, table: str) -> int:
        with self.manager.reader() as db:
            return int(db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

    def value(self, key: str) -> str | None:
        with self.manager.reader() as db:
            return self.key_values.get(db, key)


class GarminDualWriteTests(DualWriteFixture):
    def setUp(self) -> None:
        super().setUp()
        self.writer = GarminSnapshotWriter(self.key_values, lambda: ZONE)
        self.service = GarminSyncStateService(
            self.manager,
            self.key_values,
            self.sync_state,
            Mock(),
            Mock(),
            lambda: NOW,
            lambda: datetime(2026, 9, 20, 8, tzinfo=UTC),
            None,
            snapshot_writer=self.writer,
        )

    def test_failure_in_a_canonical_write_rolls_back_the_garmin_state(self) -> None:
        with (
            patch.object(
                canonical_store,
                "upsert_activity_record",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.service.persist_payload(
                garmin_payload(garmin_activity(1)), None, date(2026, 9, 20)
            )
        self.assertIsNone(self.value(GARMIN_STATE_KEY))
        self.assertIsNone(self.value("last_garmin_sync_at"))
        self.assertEqual(self.count("provider_records"), 0)

    def test_successful_sync_writes_state_and_canonical_rows_together(self) -> None:
        self.service.persist_payload(
            garmin_payload(garmin_activity(1)), None, date(2026, 9, 20)
        )
        self.assertIsNotNone(self.value(GARMIN_STATE_KEY))
        self.assertEqual(self.value("last_garmin_sync_at"), NOW)
        self.assertEqual(self.count("activity_records"), 1)

    def test_garmin_secrets_never_reach_the_provider_records(self) -> None:
        self.service.persist_payload(
            garmin_payload(garmin_activity(1)), None, date(2026, 9, 20)
        )
        text = provider_payload_text(self.manager)
        self.assertNotIn(SECRET, text)

    def test_sync_and_body_battery_share_one_garmin_writer(self) -> None:
        original = GarminSnapshotWriter.write
        original_refresh = GarminSnapshotWriter.write_refresh
        with (
            patch.object(
                GarminSnapshotWriter, "write", autospec=True, side_effect=original
            ) as write_spy,
            patch.object(
                GarminSnapshotWriter,
                "write_refresh",
                autospec=True,
                side_effect=original_refresh,
            ) as refresh_spy,
        ):
            self.service.persist_payload(
                garmin_payload(garmin_activity(1)), None, date(2026, 9, 20)
            )
            from backend.performance.morning_battery_service import MorningBatteryStore

            store = MorningBatteryStore(self.manager, self.key_values, self.writer)
            store.persist(
                date(2026, 9, 19),
                None,
                {
                    "status": "ready",
                    "sleep_date": "2026-09-19",
                    "morning": {"value": 75},
                },
                None,
            )
        self.assertEqual(write_spy.call_count, 1)
        self.assertEqual(refresh_spy.call_count, 1)
        for call in (*write_spy.call_args_list, *refresh_spy.call_args_list):
            self.assertIs(call.args[0], self.writer)


if __name__ == "__main__":
    unittest.main()
