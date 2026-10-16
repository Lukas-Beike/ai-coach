from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

from activity_row_support import SnapshotActivityRows

from backend.activities.duplicate_service import DuplicateActivityService
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND


class _Manager:
    def __init__(self) -> None:
        self.db = Mock()
        self.db.execute.return_value.fetchall.return_value = []
        self.transactions = 0

    @contextmanager
    def unit_of_work(self):
        self.transactions += 1
        yield self.db

    def reader(self):
        return self.unit_of_work()

    read_snapshot = reader


class _Snapshots:
    def __init__(self, snapshot):
        self.payload = json.dumps(snapshot)
        self.saved = []

    def latest_payload(self, db):
        return self.payload

    def latest_snapshot(self, db):
        return json.loads(self.payload)

    def save(self, db, snapshot, created_at):
        self.saved.append((snapshot, created_at))
        self.payload = json.dumps(snapshot)


class _Intervals:
    def __init__(self):
        self.deleted = []

    def delete_activity(self, activity_id):
        self.deleted.append(activity_id)


class _Events:
    def __init__(self):
        self.published = []

    def publish(self, event, payload):
        self.published.append((event, payload))


def _snapshot():
    activities = [
        {
            "id": "wahoo-1",
            "type": "Ride",
            "source": "Wahoo",
            "start_date_local": "2026-09-20T07:00:00",
            "moving_time": 7200,
            "distance": 60000,
        },
        {
            "id": "garmin-1",
            "type": "Ride",
            "source": "Garmin",
            "start_date_local": "2026-09-20T07:03:00",
            "moving_time": 7180,
            "distance": 59800,
        },
    ]
    return {
        "synced_at": "2026-09-20T10:00:00+00:00",
        "recent_activities": activities,
        "raw_provider_data": {"activities": activities},
    }


class DuplicateActivityServiceTests(unittest.TestCase):
    def setUp(self):
        self.manager = _Manager()
        self.snapshots = _Snapshots(_snapshot())
        self.intervals = _Intervals()
        self.events = _Events()
        self.service = DuplicateActivityService(
            self.manager,
            self.snapshots,
            self.snapshots,
            SnapshotActivityRows(self.snapshots),
            lambda: "2026-09-20T11:00:00+00:00",
            self.events,
        )

    def test_delete_updates_remote_then_snapshot_and_publishes(self):
        result = self.service.delete(
            {
                "canonical_id": "wahoo-1",
                "duplicate_id": "garmin-1",
                "snapshot_synced_at": "2026-09-20T10:00:00+00:00",
            },
            self.intervals,
        )

        self.assertEqual(self.intervals.deleted, ["garmin-1"])
        self.assertEqual(len(self.snapshots.saved), 1)
        saved, created_at = self.snapshots.saved[0]
        self.assertEqual(created_at, "2026-09-20T11:00:00+00:00")
        self.assertEqual(saved["synced_at"], created_at)
        self.assertEqual(
            [row["id"] for row in saved["recent_activities"]],
            ["wahoo-1"],
        )
        self.assertEqual(
            [row["id"] for row in saved["raw_provider_data"]["activities"]],
            ["wahoo-1"],
        )
        self.assertEqual(
            self.events.published,
            [
                (
                    "provider",
                    {"provider": "intervals", "status": "duplicate_deleted"},
                )
            ],
        )
        self.assertEqual(
            result,
            {
                "status": "deleted",
                "deleted_activity_id": "garmin-1",
                "kept_activity_id": "wahoo-1",
                "kept_source": "Wahoo",
            },
        )
        self.assertEqual(self.manager.transactions, 2)

    def test_stale_confirmation_has_no_side_effects(self):
        with self.assertRaises(AppError) as raised:
            self.service.delete(
                {
                    "canonical_id": "wahoo-1",
                    "duplicate_id": "old-garmin",
                    "snapshot_synced_at": "2026-09-20T10:00:00+00:00",
                },
                self.intervals,
            )

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.intervals.deleted, [])
        self.assertEqual(self.snapshots.saved, [])
        self.assertEqual(self.events.published, [])

    def test_remote_failure_does_not_mutate_snapshot_or_publish(self):
        def fail(_activity_id):
            raise RuntimeError("provider failed")

        self.intervals.delete_activity = fail
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            self.service.delete(
                {
                    "canonical_id": "wahoo-1",
                    "duplicate_id": "garmin-1",
                    "snapshot_synced_at": "2026-09-20T10:00:00+00:00",
                },
                self.intervals,
            )

        self.assertEqual(self.snapshots.saved, [])
        self.assertEqual(self.events.published, [])

    def test_delete_tombstones_the_canonical_records_in_the_snapshot_transaction(self):
        self.manager.db.execute.return_value.fetchall.return_value = [
            {"activity_id": "activity-garmin-1"}
        ]
        self.service.delete(
            {
                "canonical_id": "wahoo-1",
                "duplicate_id": "garmin-1",
                "snapshot_synced_at": "2026-09-20T10:00:00+00:00",
            },
            self.intervals,
        )

        updates = [
            call.args[0].split()[1]
            for call in self.manager.db.execute.call_args_list
            if call.args[0].startswith("UPDATE")
        ]
        self.assertEqual(
            updates, ["activity_records", "provider_records", "activity_sessions"]
        )
        self.assertEqual(self.manager.transactions, 2)


class _SqliteManager:
    """Runs each unit of work on a real temporary SQLite connection and commits it."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    @contextmanager
    def unit_of_work(self):
        yield self.db
        self.db.commit()

    def reader(self):
        return self.unit_of_work()

    read_snapshot = reader


class MergedDuplicateDeleteTests(unittest.TestCase):
    """Deleting a merged duplicate must write a schema-valid tombstone in one transaction."""

    STAMP = "2026-09-20T10:00:00+00:00"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = sqlite3.connect(Path(temporary.name) / "canonical.db")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys = ON")
        initialize_schema(self.db)
        self.db.commit()
        self.snapshots = _Snapshots(_snapshot())
        self.intervals = _Intervals()
        self.events = _Events()
        self.service = DuplicateActivityService(
            _SqliteManager(self.db),
            self.snapshots,
            self.snapshots,
            SnapshotActivityRows(self.snapshots),
            lambda: "2026-09-20T11:00:00+00:00",
            self.events,
        )
        self.keep_id = self.seed("wahoo-1", ProviderId.WAHOO)
        self.duplicate_id = self.seed("garmin-1", ProviderId.INTERVALS)
        self.assertTrue(
            canonical_store.merge_activity_session(
                self.db,
                activity_id=self.duplicate_id,
                into=self.keep_id,
                now=self.STAMP,
            )
        )

    def seed(self, source_id: str, provider: ProviderId) -> str:
        record = ActivityRecord(
            activity_id="unused",
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=source_id,
                recorded_by=RecordingOrigin.UNKNOWN,
                retrieved_at=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
                label=None,
            ),
            sport=Sport.RIDE,
            environment=Environment.OUTDOOR,
            started_at=datetime(2026, 9, 20, 7, 0, tzinfo=UTC),
            duration_s=3600.0,
            distance_m=30000.0,
            load=50.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
            avg_hr=140.0,
            avg_power=210.0,
            name="Synthetic ride",
        )
        canonical_store.upsert_activity_record(
            self.db,
            record,
            local_date=date(2026, 9, 20),
            mapper_version=1,
            fetched_at=self.STAMP,
            now=self.STAMP,
        )
        canonical_store.upsert_provider_record(
            self.db,
            provider=provider.value,
            record_kind=ACTIVITY_RECORD_KIND,
            source_record_id=source_id,
            payload={"id": source_id},
            mapper_version=1,
            fetched_at=self.STAMP,
            now=self.STAMP,
        )
        row = self.db.execute(
            "SELECT activity_id FROM activity_records "
            "WHERE provider = ? AND provider_activity_id = ?",
            (provider.value, source_id),
        ).fetchone()
        return str(row[0])

    def test_confirmed_delete_tombstones_the_merged_duplicate_session(self):
        result = self.service.delete(
            {
                "canonical_id": "wahoo-1",
                "duplicate_id": "garmin-1",
                "snapshot_synced_at": "2026-09-20T10:00:00+00:00",
            },
            self.intervals,
        )

        self.assertEqual(result["deleted_activity_id"], "garmin-1")
        self.assertEqual(self.intervals.deleted, ["garmin-1"])
        self.assertEqual(
            self.db.execute(
                "SELECT state, merged_into FROM activity_sessions WHERE activity_id = ?",
                (self.duplicate_id,),
            ).fetchone(),
            ("deleted", None),
        )
        self.assertEqual(
            self.db.execute(
                "SELECT state FROM activity_records WHERE provider_activity_id = ?",
                ("garmin-1",),
            ).fetchone(),
            ("deleted",),
        )


if __name__ == "__main__":
    unittest.main()
