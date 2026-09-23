from __future__ import annotations

import json
import unittest
from contextlib import contextmanager

from backend.activities.duplicate_service import DuplicateActivityService
from backend.errors import AppError


class _Manager:
    def __init__(self) -> None:
        self.db = object()
        self.transactions = 0

    @contextmanager
    def unit_of_work(self):
        self.transactions += 1
        yield self.db


class _Snapshots:
    def __init__(self, snapshot):
        self.payload = json.dumps(snapshot)
        self.saved = []

    def latest_payload(self, db):
        return self.payload

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


if __name__ == "__main__":
    unittest.main()
