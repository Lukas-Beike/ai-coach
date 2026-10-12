"""Dual write during Intervals.icu and Garmin ingest: atomicity, idempotence and deletion.

Each test uses a temporary SQLite file through the real DatabaseManager and the
real sync services. Remote planned-unit reconciliation and Garmin dependencies are
replaced by small fakes. No provider account, network or real data directory is used.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.bootstrap import initialize_application_database
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.sync.garmin import GarminSyncStateService
from backend.sync.garmin_snapshot_writer import (
    GARMIN_SNAPSHOT_KEY,
    GarminSnapshotWriter,
)
from backend.sync.intervals import IntervalsSnapshotService
from backend.sync.state import SyncStateRepository

NOW = "2026-09-20T08:00:00+00:00"
SECRET = "synthetic-secret-value"
SIGNED_URL = "https://files.invalid/ride.fit?X-Amz-Signature=synthetic-signature"
ZONE = ZoneInfo("Europe/Berlin")


def activity(identifier: str, *, kind: str = "Ride", day: str = "2026-09-10") -> dict[str, Any]:
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


class DualWriteFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database_path = Path(self.temporary.name) / "dual.db"
        self.manager = DatabaseManager(self.database_path, sqlite3, row_factory=row_factory)
        self.addCleanup(self.close_manager)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.sync_state = SyncStateRepository(
            self.manager, self.key_values, SnapshotRepository(), lambda: NOW
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

    def close_manager(self) -> None:
        self.manager.close()

    def count(self, table: str) -> int:
        with self.manager.reader() as db:
            return int(db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

    def value(self, key: str) -> str | None:
        with self.manager.reader() as db:
            return self.key_values.get(db, key)

    def activity_states(self) -> dict[str, str]:
        with self.manager.reader() as db:
            return {
                row["provider_activity_id"]: row["state"]
                for row in db.execute(
                    "SELECT provider_activity_id, state FROM activity_records"
                ).fetchall()
            }

    def provider_payload_text(self) -> str:
        with self.manager.reader() as db:
            return "\n".join(
                row["payload"] for row in db.execute("SELECT payload FROM provider_records")
            )


class IntervalsDualWriteTests(DualWriteFixture):
    def setUp(self) -> None:
        super().setUp()
        # Test double: the service only calls ``reconcile`` on it.
        self.reconciler: Any = FakePlannedReconciler()
        self.service = self.make_service()

    def make_service(self) -> IntervalsSnapshotService:
        # Same positional arguments as the sync test harness.
        return IntervalsSnapshotService(
            self.manager,
            self.key_values,
            self.sync_state,
            self.reconciler,
            Mock(),
            Mock(list=Mock(return_value=[])),
            lambda value: value,
            lambda: datetime(2026, 9, 20, 8, tzinfo=UTC),
            date(2026, 9, 1),
            3,
            3,
        )

    def test_failure_in_a_canonical_write_rolls_back_the_legacy_snapshot(self) -> None:
        for function in ("upsert_provider_record", "upsert_activity_record"):
            with self.subTest(function=function):
                with patch.object(
                    canonical_store, function, side_effect=RuntimeError("boom")
                ), self.assertRaises(RuntimeError):
                    self.service.store_snapshot(
                        intervals_snapshot([activity("i-1")]), 3, None
                    )
                self.assertIsNone(self.sync_state.latest_snapshot())
                self.assertIsNone(self.value("last_sync_at"))
                self.assertEqual(self.count("provider_records"), 0)
                self.assertEqual(self.count("activity_records"), 0)

    def test_successful_store_writes_the_snapshot_and_all_canonical_rows(self) -> None:
        result, _ = self.service.store_snapshot(
            intervals_snapshot([activity("i-1")]), 3, None
        )
        self.assertEqual(self.sync_state.latest_snapshot(), result)
        self.assertEqual(self.count("provider_records"), 1)
        self.assertEqual(self.count("activity_sessions"), 1)
        self.assertEqual(self.count("activity_records"), 1)

    def test_storing_the_same_snapshot_twice_is_idempotent(self) -> None:
        snapshot = intervals_snapshot([activity("i-1")])
        self.service.store_snapshot(snapshot, 3, None)
        with self.manager.reader() as db:
            first = db.execute(
                "SELECT activity_id, payload_hash FROM provider_records p "
                "JOIN activity_records a ON a.provider_activity_id = p.source_record_id"
            ).fetchone()
        self.service.store_snapshot(snapshot, 3, None)
        with self.manager.reader() as db:
            second = db.execute(
                "SELECT activity_id, payload_hash FROM provider_records p "
                "JOIN activity_records a ON a.provider_activity_id = p.source_record_id"
            ).fetchone()
        self.assertEqual(first, second)
        self.assertEqual(self.count("activity_records"), 1)
        self.assertEqual(self.count("activity_sessions"), 1)

    def test_changed_activity_is_updated_in_place_with_a_new_hash(self) -> None:
        self.service.store_snapshot(intervals_snapshot([activity("i-1")]), 3, None)
        with self.manager.reader() as db:
            before = db.execute(
                "SELECT a.activity_id, p.payload_hash FROM provider_records p "
                "JOIN activity_records a ON a.provider_activity_id = p.source_record_id"
            ).fetchone()
        self.service.store_snapshot(
            intervals_snapshot([activity("i-1", kind="Run")]), 3, None
        )
        with self.manager.reader() as db:
            after = db.execute(
                "SELECT a.activity_id, a.sport, p.payload_hash FROM provider_records p "
                "JOIN activity_records a ON a.provider_activity_id = p.source_record_id"
            ).fetchone()
        self.assertEqual(after["activity_id"], before["activity_id"])
        self.assertNotEqual(after["payload_hash"], before["payload_hash"])
        self.assertEqual(after["sport"], "run")
        self.assertEqual(self.count("activity_records"), 1)

    def test_stored_payload_hash_is_the_sha256_of_the_stored_text(self) -> None:
        self.service.store_snapshot(intervals_snapshot([activity("i-1")]), 3, None)
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT payload, payload_hash FROM provider_records"
            ).fetchone()
        text, digest = row["payload"], row["payload_hash"]
        self.assertEqual(digest, hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_secrets_never_reach_the_provider_records(self) -> None:
        self.service.store_snapshot(intervals_snapshot([activity("i-1")]), 3, None)
        text = self.provider_payload_text()
        self.assertNotIn(SECRET, text)
        self.assertNotIn("X-Amz-Signature", text)

    def test_only_a_full_current_fetch_deletes_missing_activities(self) -> None:
        self.service.store_snapshot(
            intervals_snapshot([activity("kept"), activity("gone")]), 3, None
        )

        self.service.store_snapshot(
            intervals_snapshot([activity("kept")], incremental=True), 3, None
        )
        self.assertEqual(self.activity_states()["gone"], "active")

        self.service.store_snapshot(
            intervals_snapshot([activity("kept")]), 3, date(2026, 9, 10)
        )
        self.assertEqual(self.activity_states()["gone"], "active")

        self.service.store_snapshot(intervals_snapshot([activity("kept")]), 3, None)
        self.assertEqual(self.activity_states(), {"kept": "active", "gone": "deleted"})

    def test_restart_with_a_new_manager_keeps_the_canonical_rows(self) -> None:
        self.service.store_snapshot(intervals_snapshot([activity("i-1")]), 3, None)
        self.manager.close()
        restarted = DatabaseManager(self.database_path, sqlite3, row_factory=row_factory)
        self.addCleanup(restarted.close)
        # Same-build startup runs the application bootstrap on the populated file.
        with restarted.unit_of_work() as db:
            initialize_application_database(
                db,
                key_values=self.key_values,
                now=NOW,
                current_time=datetime(2026, 9, 20, 8, tzinfo=UTC),
                default_profile_json="{}",
                provider_resync_keys=(),
                retention_days=3,
                all_sync_days=3,
            )
        with restarted.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS n FROM activity_records").fetchone()["n"], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS n FROM provider_records").fetchone()["n"], 1
            )


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

    def test_failure_in_a_canonical_write_rolls_back_the_garmin_snapshot(self) -> None:
        with patch.object(
            canonical_store, "upsert_activity_record", side_effect=RuntimeError("boom")
        ), self.assertRaises(RuntimeError):
            self.service.persist_payload(
                garmin_payload(garmin_activity(1)), None, date(2026, 9, 20)
            )
        self.assertIsNone(self.value(GARMIN_SNAPSHOT_KEY))
        self.assertIsNone(self.value("last_garmin_sync_at"))
        self.assertEqual(self.count("provider_records"), 0)

    def test_successful_sync_writes_snapshot_and_canonical_rows_together(self) -> None:
        self.service.persist_payload(garmin_payload(garmin_activity(1)), None, date(2026, 9, 20))
        self.assertIsNotNone(self.value(GARMIN_SNAPSHOT_KEY))
        self.assertEqual(self.value("last_garmin_sync_at"), NOW)
        self.assertEqual(self.count("activity_records"), 1)

    def test_garmin_secrets_never_reach_the_provider_records(self) -> None:
        self.service.persist_payload(garmin_payload(garmin_activity(1)), None, date(2026, 9, 20))
        text = self.provider_payload_text()
        self.assertNotIn(SECRET, text)

    def test_sync_and_body_battery_share_one_garmin_write_function(self) -> None:
        original = GarminSnapshotWriter.write
        with patch.object(
            GarminSnapshotWriter, "write", autospec=True, side_effect=original
        ) as spy:
            self.service.persist_payload(
                garmin_payload(garmin_activity(1)), None, date(2026, 9, 20)
            )
            from backend.performance.morning_battery_service import MorningBatteryStore

            store = MorningBatteryStore(self.manager, self.key_values, self.writer)
            store.persist(
                date(2026, 9, 19),
                None,
                {"status": "ready", "sleep_date": "2026-09-19", "morning": {"value": 75}},
                None,
            )
        self.assertEqual(spy.call_count, 2)
        for call in spy.call_args_list:
            self.assertIs(call.args[0], self.writer)


if __name__ == "__main__":
    unittest.main()
