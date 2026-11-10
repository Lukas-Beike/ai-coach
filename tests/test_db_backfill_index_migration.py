"""Schema version 26: the backfill-continuation index of sync jobs, upgraded in place.

Release 1.13.44 wrote v21, the 2.0.0 candidates v22 to v24, release 2.0.3 v25; each
upgrades to v26, which adds ``idx_sync_jobs_backfill_end``. No row changes; the
lookup of ``has_backfill_continuation`` reads the index instead of scanning the
table; a failure rolls back to the unchanged release and a restart changes nothing.
Temporary databases and synthetic rows only.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from support import connect
from test_db_strength_sets_migration import populate

from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V25
from backend.sync.jobs import BACKFILL_CONTINUATION_SQL

RELEASES = (21, 22, 23, 24, 25)
INDEX = "idx_sync_jobs_backfill_end"
STAMP = "2026-11-01T00:00:00+00:00"
JOBS = (
    ("job-a", "garmin", "historical_backfill", "backfill", "2026-10-31"),
    ("job-b", "garmin", "historical_backfill", "backfill", "2026-10-24"),
    ("job-c", "wahoo", "historical_backfill", "backfill", "2026-10-31"),
    ("job-d", "garmin", "historical_backfill", "athlete", "2026-10-31"),
    ("job-e", "garmin", "refresh", "coach", None),
)


def add_jobs(db: sqlite3.Connection) -> None:
    for job_id, provider, job_type, requested_by, end_date in JOBS:
        payload = json.dumps({} if end_date is None else {"end_date": end_date})
        db.execute(
            "INSERT INTO sync_jobs(id, provider, type, status, payload, requested_by, "
            "created_at, updated_at) VALUES (?, ?, ?, 'completed', ?, ?, ?, ?)",
            (job_id, provider, job_type, payload, requested_by, STAMP, STAMP),
        )
    db.execute(
        "INSERT INTO sync_job_items(id, job_id, item_key, operation, payload_hash, "
        "status, created_at, updated_at) VALUES ('item-a', 'job-a', 'k', 'fetch', "
        "'hash', 'completed', ?, ?)",
        (STAMP, STAMP),
    )


def table_rows(db: sqlite3.Connection) -> list[str]:
    # Detail sets gain columns in the earlier steps; the step under test adds none.
    return [
        line
        for line in db.iterdump()
        if line.startswith("INSERT INTO") and "activity_detail_sets" not in line
    ]


def has_continuation(
    db: sqlite3.Connection, provider: str, end_date: str, exclude: str = ""
) -> bool:
    row = db.execute(
        BACKFILL_CONTINUATION_SQL,
        (provider, "historical_backfill", end_date, STAMP, exclude),
    ).fetchone()
    return row is not None


class BackfillIndexMigrationTests(unittest.TestCase):
    def populated(self, release: int) -> sqlite3.Connection:
        db = connect()
        self.addCleanup(db.close)
        populate(db, release)
        add_jobs(db)
        db.commit()
        return db

    def test_every_release_upgrades_with_all_rows_kept_and_the_index_built(
        self,
    ) -> None:
        for release in RELEASES:
            with self.subTest(release=release):
                db = self.populated(release)
                self.assertIsNone(
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name = ?", (INDEX,)
                    ).fetchone()
                )
                before = table_rows(db)
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertEqual(CURRENT_SCHEMA_VERSION, 26)
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(table_rows(db), before)
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM sync_jobs").fetchone()[0],
                    len(JOBS),
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM sync_job_items").fetchone()[0], 1
                )
                self.assertIsNotNone(
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name = ?", (INDEX,)
                    ).fetchone()
                )

    def test_upgraded_schema_equals_a_fresh_schema(self) -> None:
        fresh = connect()
        self.addCleanup(fresh.close)
        initialize_schema(fresh)
        expected = database_schema_signature(fresh)
        for release in RELEASES:
            with self.subTest(release=release):
                db = self.populated(release)
                migrate_schema(db)
                self.assertEqual(database_schema_signature(db), expected)

    def test_the_lookup_answers_the_same_and_reads_the_index(self) -> None:
        for release in RELEASES:
            with self.subTest(release=release):
                db = self.populated(release)
                migrate_schema(db)
                self.assertTrue(has_continuation(db, "garmin", "2026-10-31"))
                self.assertFalse(
                    has_continuation(db, "garmin", "2026-10-31", exclude="job-a")
                )
                self.assertFalse(has_continuation(db, "wahoo", "2026-10-24"))
                self.assertFalse(has_continuation(db, "garmin", "2026-01-01"))
                plan = " ".join(
                    str(row[3])
                    for row in db.execute(
                        f"EXPLAIN QUERY PLAN {BACKFILL_CONTINUATION_SQL}",
                        ("garmin", "historical_backfill", "2026-10-31", STAMP, ""),
                    )
                )
                self.assertIn(INDEX, plan)

    def test_a_failing_upgrade_leaves_every_release_unchanged(self) -> None:
        def failing_last_step(connection: Any) -> None:
            migrations._upgrade_v25_to_v26(connection)
            raise RuntimeError("injected migration failure")

        for release in RELEASES:
            with self.subTest(release=release):
                db = self.populated(release)
                before = list(db.iterdump())
                steps = {SHAPE_SCHEMA_V25: (SHAPE_CURRENT, failing_last_step)}
                with (
                    mock.patch.dict(migrations.UPGRADE_STEPS, steps),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], release
                )

    def test_a_restart_with_the_same_build_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for release in RELEASES:
                path = Path(root) / f"restart-{release}.db"
                self.copy_to_file(self.populated(release), path)
                dumps = [self.migrate_file(path) for _ in range(2)]
                self.assertEqual(dumps[0], dumps[1], release)

    @staticmethod
    def copy_to_file(source: sqlite3.Connection, path: Path) -> None:
        target = connect(path)
        try:
            source.backup(target)
        finally:
            target.close()

    @staticmethod
    def migrate_file(path: Path) -> list[str]:
        db = connect(path)
        try:
            migrate_schema(db)
            db.commit()
            return list(db.iterdump())
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
