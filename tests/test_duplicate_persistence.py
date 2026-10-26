"""Merged duplicate sessions and deleted copies survive restart and backup/restore."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from duplicate_support import GARMIN_ID, WAHOO_ID, ZONE, DuplicateCase

from backend.activities.duplicate_inspection import DuplicateInspector
from backend.activities.duplicate_service import DuplicateActivityService
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager, row_factory
from backend.db.bootstrap import initialize_application_database
from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_table_reader import CanonicalTableReader

DELETED_AT = "2026-09-20T11:00:00+00:00"
STATE_SQL = {
    "sessions": (
        "SELECT primary_provider_activity_id AS source, state, merged_into, link_kind "
        "FROM activity_sessions ORDER BY primary_provider_activity_id"
    ),
    "records": (
        "SELECT provider_activity_id AS source, state, activity_id "
        "FROM activity_records ORDER BY provider_activity_id"
    ),
    "provider_records": (
        "SELECT source_record_id AS source, state FROM provider_records "
        "ORDER BY source_record_id"
    ),
}


def _states(db: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        name: [tuple(dict(row).values()) for row in db.execute(sql).fetchall()]
        for name, sql in STATE_SQL.items()
    }


class PersistenceTests(DuplicateCase):
    def setUp(self) -> None:
        super().setUp()
        self.wahoo_session, self.garmin_session = self.seed_pair()
        # A heuristic link, as the sync writes it, plus a deleted Garmin-provider copy.
        self.merge(self.garmin_session, self.wahoo_session)
        self.seed("garmin-direct", provider=ProviderId.GARMIN)
        self.service = DuplicateActivityService(
            self.manager, self.inspector, lambda: DELETED_AT, Mock()
        )

    @staticmethod
    def restart_bootstrap(manager: DatabaseManager) -> None:
        """Same-build startup runs the application bootstrap on the populated file."""
        with manager.unit_of_work() as db:
            initialize_application_database(
                db,
                key_values=KeyValueRepository(lambda: DELETED_AT),
                now=DELETED_AT,
                current_time=datetime(2026, 9, 20, 12, tzinfo=UTC),
                default_profile_json="{}",
                provider_resync_keys=(),
                retention_days=-1,
            )

    def state(self) -> dict[str, list[tuple[object, ...]]]:
        with self.manager.reader() as db:
            return _states(db)

    def delete_copy(self) -> None:
        self.service.delete(
            {
                "canonical_id": WAHOO_ID,
                "duplicate_id": GARMIN_ID,
                "snapshot_synced_at": (self.inspector.latest() or {})[
                    "snapshot_synced_at"
                ],
            },
            Mock(),
        )

    def test_merged_state_survives_a_restart(self) -> None:
        before = self.state()
        self.manager.close()

        reopened = DatabaseManager(self.path, sqlite3, row_factory=row_factory)
        self.addCleanup(reopened.close)
        self.restart_bootstrap(reopened)
        with reopened.reader() as db:
            after = _states(db)

        self.assertEqual(after, before)
        merged = [row for row in after["sessions"] if row[0] == GARMIN_ID]
        self.assertEqual(merged[0][1:3], ("duplicate", self.wahoo_session))

    def test_a_deleted_copy_stays_deleted_after_a_restart(self) -> None:
        self.delete_copy()
        before = self.state()
        self.manager.close()

        reopened = DatabaseManager(self.path, sqlite3, row_factory=row_factory)
        self.addCleanup(reopened.close)
        self.restart_bootstrap(reopened)
        inspector = DuplicateInspector(reopened, CanonicalTableReader(), lambda: ZONE)
        with reopened.reader() as db:
            after = _states(db)
            served = {r.activity_id for r in CanonicalTableReader().activities(db)}

        self.assertEqual(after, before)
        self.assertIn((GARMIN_ID, "deleted", None, "single"), after["sessions"])
        self.assertEqual(served, {WAHOO_ID, "garmin-direct"})
        self.assertIsNone(inspector.latest())

    def test_backup_restore_keeps_merged_state_and_tombstones(self) -> None:
        for label, change in (("merged", None), ("deleted", self.delete_copy)):
            with self.subTest(label):
                if change is not None:
                    change()
                before = self.state()
                restored_path = self.backup_to_file(label)
                restored = DatabaseManager(
                    restored_path, sqlite3, row_factory=row_factory
                )
                self.addCleanup(restored.close)
                with restored.reader() as db:
                    after = _states(db)
                    served = {
                        r.activity_id for r in CanonicalTableReader().activities(db)
                    }

                self.assertEqual(after, before)
                expected = {WAHOO_ID, "garmin-direct"}
                self.assertEqual(
                    served, expected | ({GARMIN_ID} if label == "merged" else set())
                )

    def backup_to_file(self, name: str) -> Path:
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
        target = root / f"restored-{name}.db"
        target.write_bytes(data)
        return target


if __name__ == "__main__":
    unittest.main()
