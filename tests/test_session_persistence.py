"""Linked Wahoo and Garmin sessions survive a restart and a backup restore."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from test_session_linking import (
    FIRST,
    GARMIN_ID,
    SECOND,
    WAHOO_ID,
    LinkingCase,
    garmin_ride,
    wahoo_workout,
)

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db import DatabaseManager, row_factory
from backend.db.bootstrap import initialize_application_database
from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_table_reader import CanonicalTableReader

STAMP = "2026-09-20T11:00:00+00:00"
STATE_SQL = {
    "sessions": (
        "SELECT primary_provider_activity_id AS source, state, merged_into, link_kind "
        "FROM activity_sessions ORDER BY primary_provider_activity_id"
    ),
    "records": (
        "SELECT provider_activity_id AS source, state, activity_id "
        "FROM activity_records ORDER BY provider_activity_id"
    ),
}


def _states(db: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        name: [tuple(dict(row).values()) for row in db.execute(sql).fetchall()]
        for name, sql in STATE_SQL.items()
    }


class LinkedSessionPersistenceTests(LinkingCase):
    def setUp(self) -> None:
        super().setUp()
        self._ingest_wahoo([wahoo_workout()], FIRST)
        self._ingest_garmin([garmin_ride()], SECOND)
        self.path: Path = self.manager.path

    def state(self) -> dict[str, list[tuple[object, ...]]]:
        with self.manager.reader() as db:
            return _states(db)

    def assert_linked(self, states: dict[str, list[tuple[object, ...]]]) -> None:
        sessions = {row[0]: row for row in states["sessions"]}
        self.assertEqual(sessions[WAHOO_ID][1:3], ("active", None))
        self.assertEqual(sessions[GARMIN_ID][1], "duplicate")
        self.assertEqual(len(states["records"]), 2)

    @staticmethod
    def served(db: sqlite3.Connection) -> set[str]:
        return {row.activity_id for row in CanonicalTableReader().activities(db)}

    def test_linked_state_survives_a_restart(self) -> None:
        before = self.state()
        self.assert_linked(before)
        with self.manager.reader() as db:
            served_before = self.served(db)
        self.manager.close()

        reopened = DatabaseManager(self.path, sqlite3, row_factory=row_factory)
        self.addCleanup(reopened.close)
        with reopened.unit_of_work() as db:
            initialize_application_database(
                db,
                key_values=KeyValueRepository(lambda: STAMP),
                now=STAMP,
                current_time=datetime(2026, 9, 20, 12, tzinfo=UTC),
                default_profile_json="{}",
                provider_resync_keys=(),
                retention_days=-1,
            )
        with reopened.reader() as db:
            after = _states(db)
            served = self.served(db)

        self.assertEqual(after, before)
        self.assertEqual(served, served_before)

    def test_backup_restore_keeps_the_linked_state(self) -> None:
        before = self.state()
        with self.manager.reader() as db:
            served_before = self.served(db)
        root = self.path.parent
        config = DatabaseBackupConfig(
            database_path=self.path,
            data_dir=root,
            maximum_bytes=10_000_000,
            minimum_free_bytes=10,
            time_limit_seconds=5,
            monotonic=lambda: 10.0,
            disk_usage=lambda _path: SimpleNamespace(free=100_000_000),
        )
        data = DatabaseBackupService(
            self.manager, MagicMock(), config, Mock()
        ).read_bytes()
        target = root / "restored.db"
        target.write_bytes(data)
        restored = DatabaseManager(target, sqlite3, row_factory=row_factory)
        self.addCleanup(restored.close)

        with restored.reader() as db:
            after = _states(db)
            served = self.served(db)

        self.assertEqual(after, before)
        self.assert_linked(after)
        self.assertEqual(served, served_before)


if __name__ == "__main__":
    unittest.main()
