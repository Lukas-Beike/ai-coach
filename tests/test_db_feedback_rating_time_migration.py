"""Schema version 18: the rating time of the session RPE, upgraded in place.

A populated release adds ``activity_feedback.session_rpe_rated_at`` as NULL, so
the rating time of earlier feedback stays unknown; every other row stays exactly
as it was. A failure rolls back to the unchanged release, a restart changes
nothing, a v17 backup restores through validation, and a later RPE edit records
its rating time. Temporary databases and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import Mock

from test_db_power_curve_migration import (
    all_rows,
    connect,
    populated_power_curve_database,
)

from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.repositories import ActivityFeedbackRepository
from backend.db.schema import CURRENT_SCHEMA_VERSION, database_schema_is_current
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V17

FIXTURES = Path(__file__).with_name("fixtures")
RELEASED = {
    version: FIXTURES / f"schema_v{version}.sql.txt" for version in range(16, 18)
}
V17_FIXTURE = RELEASED[17]
SESSION = "act_feedback"
STAMP = "2026-10-31T08:00:00+00:00"
LATER = "2026-11-01T09:30:00+00:00"


def populated_feedback_database(db: Any, fixture: Path = V17_FIXTURE) -> Any:
    """A v17 database with a power curve snapshot and rated, linked feedback."""
    populated_power_curve_database(db, fixture)
    db.execute(
        "INSERT INTO activity_sessions(activity_id, primary_provider, "
        "primary_provider_activity_id, started_at, created_at, updated_at) "
        "VALUES (?, 'intervals', 'i1', '2026-10-30T07:00:00+00:00', ?, ?)",
        (SESSION, STAMP, STAMP),
    )
    db.executemany(
        "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, "
        "notes, session_rpe, deviation_reason, created_at, updated_at, provider, "
        "session_id) VALUES (?, ?, '2026-10-30', ?, ?, '', ?, ?, ?, ?)",
        [
            ("i1", "Ride", "fine", 5, STAMP, STAMP, "intervals", SESSION),
            ("w1", "Run", "", 0, STAMP, STAMP, None, None),
            ("g1", "Swim", "note only", None, STAMP, STAMP, "garmin", None),
        ],
    )
    db.commit()
    return db


def rating_times(db: Any) -> dict[str, Any]:
    return {
        row[0]: row[1]
        for row in db.execute(
            "SELECT activity_id, session_rpe_rated_at FROM activity_feedback"
        )
    }


class FeedbackRatingTimeMigrationTests(unittest.TestCase):
    def released(self, fixture: Path = V17_FIXTURE) -> sqlite3.Connection:
        db = connect()
        self.addCleanup(db.close)
        return populated_feedback_database(db, fixture)

    def test_populated_v17_upgrade_keeps_every_row_and_adds_unknown_rating_times(
        self,
    ):
        db = self.released()
        before = all_rows(db)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        after = all_rows(db)
        self.assertEqual(set(after), set(before))
        for table, rows in before.items():
            if table != "activity_feedback":
                self.assertEqual(after[table], rows, table)
        self.assertEqual(
            after["activity_feedback"],
            sorted((*row, None) for row in before["activity_feedback"]),
        )
        self.assertEqual(rating_times(db), {"i1": None, "w1": None, "g1": None})
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_every_released_schema_reaches_the_rating_time_column(self):
        for version, fixture in RELEASED.items():
            with self.subTest(version=version):
                db = connect()
                self.addCleanup(db.close)
                db.executescript(fixture.read_text(encoding="utf-8"))
                migrate_schema(db)
                db.commit()
                self.assertTrue(database_schema_is_current(db))
                columns = [
                    row["name"]
                    for row in db.execute("PRAGMA table_info(activity_feedback)")
                ]
                self.assertEqual(columns[-2:], ["session_id", "session_rpe_rated_at"])

    def test_failure_after_the_step_rolls_back_to_the_unchanged_release(self):
        for version in (17, 16):
            with self.subTest(version=version):
                db = connect()
                self.addCleanup(db.close)
                if version == 17:
                    populated_feedback_database(db)
                else:
                    populated_power_curve_database(db, RELEASED[16])
                before = list(db.iterdump())

                def failing_step(connection):
                    migrations._upgrade_v17_to_v18(connection)
                    raise RuntimeError("injected migration failure")

                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V17: (SHAPE_CURRENT, failing_step)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "upgrade.db"
            with closing(connect(path)) as db:
                populated_feedback_database(db)
                migrate_schema(db)
                db.commit()
                upgraded = list(db.iterdump())
            with closing(connect(path)) as reopened:
                migrate_schema(reopened)
                self.assertEqual(list(reopened.iterdump()), upgraded)

    def test_v17_version_and_shape_must_belong_together(self):
        for version in (CURRENT_SCHEMA_VERSION, 16):
            with self.subTest(version=version):
                db = self.released()
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)

    def test_restore_of_a_populated_v17_backup_upgrades_through_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(connect(path)) as db:
                populated_feedback_database(db)
            DatabaseRestoreValidationService(
                DatabaseRestoreValidationConfig(
                    data_dir=Path(directory),
                    maximum_bytes=10_000_000,
                    app_password="",
                    sqlcipher_available=False,
                    sqlite_backend=sqlite3,
                    configure_cipher=Mock(),
                    row_factory=sqlite3.Row,
                    schema_is_current=database_schema_is_current,
                    migrate_schema=migrate_schema,
                )
            ).validate(path)
            with closing(connect(path)) as db:
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(rating_times(db), {"i1": None, "w1": None, "g1": None})

    def test_upgraded_feedback_records_its_rating_time_only_on_an_rpe_change(self):
        db = self.released()
        migrate_schema(db)
        db.commit()
        repository = ActivityFeedbackRepository(lambda: LATER)
        stored = {row["activity_id"]: row for row in repository.all(db)}
        repository.upsert(db, {**stored["i1"], "notes": "edited"})
        repository.upsert(db, {**stored["w1"], "session_rpe": 4})
        repository.upsert(db, {**stored["g1"], "session_rpe": 3})
        self.assertEqual(rating_times(db), {"i1": None, "w1": LATER, "g1": LATER})
        later = ActivityFeedbackRepository(lambda: "2026-11-02T10:00:00+00:00")
        later.upsert(db, {**stored["w1"], "session_rpe": 4, "notes": "same rating"})
        later.upsert(db, {**stored["g1"], "session_rpe": None, "notes": "kept"})
        self.assertEqual(rating_times(db), {"i1": None, "w1": LATER, "g1": None})


if __name__ == "__main__":
    unittest.main()
