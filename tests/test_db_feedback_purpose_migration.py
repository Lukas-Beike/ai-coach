"""Schema version 23: the athlete's session purpose marking, upgraded in place.

Release 1.13.44 wrote v21 and the 2.0.0 candidate wrote v22; both upgrade to v23,
which adds ``activity_feedback.purpose``. Every feedback row and every other
table stays exactly as it was and carries no marking; the column accepts only
the five purposes; a failure rolls back to the unchanged release and a restart
changes nothing. Temporary databases and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from support import connect

from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)
from backend.db.schema_history import (
    SHAPE_SCHEMA_V21,
    SHAPE_SCHEMA_V22,
    SHAPE_SCHEMA_V23,
)

FIXTURES = Path(__file__).with_name("fixtures")
RELEASES = {21: "schema_v21.sql.txt", 22: "schema_v22.sql.txt"}
STAMP = "2026-11-08T08:00:00+00:00"
SESSION = "act_marked"
FEEDBACK = (
    ("g1", "Ride", "fine", 5, "garmin", SESSION, STAMP),
    ("w1", "Run", "", 0, None, None, None),
)


def populated(release: int) -> sqlite3.Connection:
    """A released database with a message, a session and two feedback rows."""
    db = connect()
    db.executescript((FIXTURES / RELEASES[release]).read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO messages(role, content, created_at) VALUES ('user', 'Hallo', ?)",
        (STAMP,),
    )
    db.execute(
        "INSERT INTO activity_sessions(activity_id, primary_provider, "
        "primary_provider_activity_id, started_at, created_at, updated_at) "
        "VALUES (?, 'garmin', 'g1', ?, ?, ?)",
        (SESSION, STAMP, STAMP, STAMP),
    )
    db.executemany(
        "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, "
        "notes, session_rpe, deviation_reason, created_at, updated_at, provider, "
        "session_id, session_rpe_rated_at) VALUES (?, ?, '2026-11-07', ?, ?, '', ?, ?, "
        "?, ?, ?)",
        [(a, n, t, r, STAMP, STAMP, p, s, d) for a, n, t, r, p, s, d in FEEDBACK],
    )
    db.commit()
    return db


def feedback_rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute("SELECT * FROM activity_feedback ORDER BY activity_id")
    ]


def other_rows(db: sqlite3.Connection) -> list[str]:
    """Every stored row outside the feedback table, as dump statements."""
    return [
        line
        for line in db.iterdump()
        if line.startswith("INSERT INTO") and "activity_feedback" not in line
    ]


class FeedbackPurposeMigrationTests(unittest.TestCase):
    def test_every_release_upgrades_with_all_rows_kept_and_no_marking(self) -> None:
        for release in RELEASES:
            with self.subTest(release=release):
                db = populated(release)
                self.addCleanup(db.close)
                before = feedback_rows(db)
                dump = other_rows(db)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], release
                )
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertTrue(database_schema_is_current(db))
                after = feedback_rows(db)
                self.assertEqual(
                    [{k: v for k, v in row.items() if k != "purpose"} for row in after],
                    before,
                )
                self.assertEqual([row["purpose"] for row in after], [None, None])
                self.assertEqual(other_rows(db), dump)
                self.assertEqual(
                    db.execute("SELECT content FROM messages").fetchone()[0], "Hallo"
                )

    def test_upgraded_schema_equals_a_fresh_schema(self) -> None:
        fresh = connect()
        self.addCleanup(fresh.close)
        initialize_schema(fresh)
        expected = database_schema_signature(fresh)
        for release in RELEASES:
            with self.subTest(release=release):
                db = populated(release)
                self.addCleanup(db.close)
                migrate_schema(db)
                self.assertEqual(database_schema_signature(db), expected)

    def test_the_marking_accepts_only_the_five_purposes(self) -> None:
        db = populated(22)
        self.addCleanup(db.close)
        migrate_schema(db)
        for purpose in ("training", "race", "commute", "warmup", "cooldown", None):
            db.execute(
                "UPDATE activity_feedback SET purpose = ? WHERE activity_id = 'g1'",
                (purpose,),
            )
        for invalid in ("party", "Race", ""):
            with (
                self.subTest(purpose=invalid),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                db.execute(
                    "UPDATE activity_feedback SET purpose = ? WHERE activity_id = 'g1'",
                    (invalid,),
                )

    def test_a_failing_upgrade_leaves_every_release_unchanged(self) -> None:
        def failing_last_step(connection: Any) -> None:
            migrations._upgrade_v22_to_v23(connection)
            raise RuntimeError("injected migration failure")

        for release in RELEASES:
            with self.subTest(release=release):
                db = populated(release)
                self.addCleanup(db.close)
                before = list(db.iterdump())
                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V22: (SHAPE_SCHEMA_V23, failing_last_step)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], release
                )

    def test_a_failing_first_step_keeps_v21_and_a_retry_succeeds(self) -> None:
        def failing(connection: Any) -> None:
            raise RuntimeError("injected migration failure")

        db = populated(21)
        self.addCleanup(db.close)
        before = list(db.iterdump())
        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {SHAPE_SCHEMA_V21: (SHAPE_SCHEMA_V22, failing)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_a_restart_with_the_same_build_changes_nothing(self) -> None:
        for release in RELEASES:
            with self.subTest(release=release), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "upgrade.db"
                source = populated(release)
                backup = connect(path)
                source.backup(backup)
                source.close()
                try:
                    migrate_schema(backup)
                    backup.commit()
                    upgraded = list(backup.iterdump())
                finally:
                    backup.close()
                reopened = connect(path)
                try:
                    migrate_schema(reopened)
                    self.assertEqual(list(reopened.iterdump()), upgraded)
                    self.assertEqual(
                        reopened.execute("PRAGMA user_version").fetchone()[0],
                        CURRENT_SCHEMA_VERSION,
                    )
                finally:
                    reopened.close()

    def test_a_marking_written_after_the_upgrade_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "marked.db"
            source = populated(21)
            target = connect(path)
            source.backup(target)
            source.close()
            try:
                migrate_schema(target)
                target.execute(
                    "UPDATE activity_feedback SET purpose = 'race' "
                    "WHERE activity_id = 'g1'"
                )
                target.commit()
            finally:
                target.close()
            reopened = connect(path)
            try:
                migrate_schema(reopened)
                self.assertEqual(
                    [row["purpose"] for row in feedback_rows(reopened)], ["race", None]
                )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
