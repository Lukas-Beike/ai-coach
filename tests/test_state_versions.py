from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.athlete.profile import ProfileService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import (
    KeyValueRepository,
    ProfileRepository,
    SnapshotRepository,
)
from backend.db.schema import initialize_schema
from backend.http_api.state_versions import StateVersionService
from backend.sync.state import SyncStateRepository

NOW = "2026-09-20T12:00:00+00:00"


class TrackingDatabaseManager(DatabaseManager):
    def __init__(self, path: Path) -> None:
        super().__init__(path, sqlite3, row_factory=row_factory)
        self.reader_calls = 0
        self.unit_of_work_calls = 0

    def reader(self):
        self.reader_calls += 1
        return super().reader()

    def unit_of_work(self):
        self.unit_of_work_calls += 1
        return super().unit_of_work()


class StateVersionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = TrackingDatabaseManager(
            Path(self.temporary_directory.name) / "versions.sqlite"
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.snapshot_repository = SnapshotRepository()
        self.sync_state = SyncStateRepository(
            self.manager, self.key_values, self.snapshot_repository, lambda: NOW
        )
        self.profile = ProfileService(
            self.manager, ProfileRepository(self.key_values), self.key_values
        )
        self.service = StateVersionService(
            self.manager, self.key_values, self.snapshot_repository, self.profile
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def test_versions_preserve_exact_public_markers_and_read_scope(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(id, role, content, created_at) VALUES "
                "(4, 'user', 'hello', '2026-09-10'), "
                "(9, 'assistant', 'ready', '2026-09-11')"
            )
            db.executemany(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    ("w1", "l1", '{"name":"Easy"}', "2026-09-15"),
                    ("w2", "l2", '{"name":"Tempo"}', "2026-09-16"),
                    (
                        "w3",
                        "l3",
                        '{"name":"Planned","date":"2026-09-19"}',
                        "2026-09-19",
                    ),
                ),
            )
            db.executemany(
                "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    (
                        "p1",
                        "pl1",
                        "{}",
                        "2026-09-12",
                        "2026-09-17",
                    ),
                    (
                        "p2",
                        "pl2",
                        "{}",
                        "2026-09-13",
                        "2026-09-18",
                    ),
                ),
            )
            db.executemany(
                "INSERT INTO athlete_checkins(checkin_date, created_at, updated_at) "
                "VALUES (?, ?, ?)",
                (
                    ("2026-09-18", "2026-09-18T08:00:00", "2026-09-18T08:00:00"),
                    ("2026-09-19", "2026-09-19T08:00:00", "2026-09-19T08:00:00"),
                ),
            )
            db.execute(
                "INSERT INTO activity_feedback(activity_id, created_at, updated_at) "
                "VALUES ('a1', '2026-09-14T08:00:00', '2026-09-20T09:00:00')"
            )
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES "
                "('last_performance_refresh_at', 'performance-at', ?), "
                "('last_garmin_sync_at', 'garmin-at', ?), "
                "('last_external_calendar_sync_at', 'calendar-at', ?), "
                "('profile', ?, ?)",
                (
                    NOW,
                    NOW,
                    NOW,
                    json.dumps({"name": "Athlete", "timezone": "Europe/Berlin"}),
                    NOW,
                ),
            )
        self.sync_state.save_view(
            {"synced_at": "intervals-at", "recent_activities": [{}, {}, {}]}
        )
        profile = self.profile.get()
        expected_profile = hashlib.sha256(
            json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]

        self.manager.reader_calls = 0
        self.manager.unit_of_work_calls = 0
        actual = self.service.versions()

        self.assertEqual(
            actual,
            {
                "activities": "intervals-at:3",
                "performance": "performance-at",
                "garmin": "garmin-at",
                "chat": "9:2",
                "library": "2026-09-16:2",
                "checkins": "2026-09-19T08:00:00:2",
                "activity_feedback": "2026-09-20T09:00:00:1",
                "profile": expected_profile,
                "plan": "intervals-at:calendar-at:2026-09-16:2026-09-18:2026-09-19T08:00:00",
            },
        )
        self.assertEqual(self.manager.reader_calls, 1)
        self.assertEqual(self.manager.unit_of_work_calls, 0)

    def test_versions_keep_empty_snapshot_and_marker_fallbacks(self) -> None:
        self.manager.reader_calls = 0
        self.manager.unit_of_work_calls = 0
        actual = self.service.versions()

        self.assertEqual(
            set(actual),
            {
                "activities",
                "performance",
                "garmin",
                "chat",
                "library",
                "checkins",
                "activity_feedback",
                "profile",
                "plan",
            },
        )
        self.assertEqual(actual["activities"], ":0")
        self.assertEqual(actual["performance"], "")
        self.assertEqual(actual["garmin"], "")
        self.assertEqual(actual["chat"], "0:0")
        self.assertEqual(actual["library"], ":0")
        self.assertEqual(actual["checkins"], ":0")
        self.assertEqual(actual["activity_feedback"], ":0")
        self.assertEqual(actual["plan"], "::::")
        self.assertEqual(self.manager.reader_calls, 1)
        self.assertEqual(self.manager.unit_of_work_calls, 0)


if __name__ == "__main__":
    unittest.main()
