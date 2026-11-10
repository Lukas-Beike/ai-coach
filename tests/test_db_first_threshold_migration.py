"""Schema version 25: first threshold estimate of stream sets, upgraded in place.

Release 1.13.44 wrote v21, the 2.0.0 candidates v22, v23 and v24; each upgrades
to v25, which adds ``dfa_alpha1`` to ``activity_detail_sets``. Every detail row
and every other table stays exactly as it was and carries no estimate (NULL);
the column accepts only a JSON object; a failure rolls back to the unchanged
release and a restart changes nothing. Temporary databases and synthetic rows only.
"""

from __future__ import annotations

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
from backend.db.schema_history import SHAPE_SCHEMA_V24, SHAPE_SCHEMA_V25

RELEASES = (21, 22, 23, 24)
NEW_COLUMN = "dfa_alpha1"
KEY = ("garmin", "g1", "streams")
WHERE = "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?"
ESTIMATE = (
    '{"artifact_share":0.01,"estimate_bpm":152.5,"method":1,'
    '"quality":"good","windows":40}'
)


def detail_rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
    kept = {"hr_source", "power_source", "sensors", "set_source", NEW_COLUMN}
    return [
        {k: v for k, v in dict(row).items() if k not in kept}
        for row in db.execute(
            "SELECT * FROM activity_detail_sets ORDER BY provider, "
            "provider_activity_id, detail_kind"
        )
    ]


def other_rows(db: sqlite3.Connection) -> list[str]:
    return [
        line
        for line in db.iterdump()
        if line.startswith("INSERT INTO") and "activity_detail_sets" not in line
    ]


class FirstThresholdMigrationTests(unittest.TestCase):
    def populated(self, release: int) -> sqlite3.Connection:
        db = connect()
        self.addCleanup(db.close)
        populate(db, release)
        db.commit()
        return db

    def test_every_release_upgrades_with_all_rows_kept_and_no_estimate(self) -> None:
        for release in RELEASES:
            with self.subTest(release=release):
                db = self.populated(release)
                before = detail_rows(db)
                dump = other_rows(db)
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertEqual(CURRENT_SCHEMA_VERSION, 26)
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(detail_rows(db), before)
                self.assertEqual(
                    db.execute(
                        f"SELECT COUNT({NEW_COLUMN}) FROM activity_detail_sets"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(other_rows(db), dump)

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

    def test_the_column_accepts_only_a_json_object(self) -> None:
        db = self.populated(24)
        migrate_schema(db)
        update = f"UPDATE activity_detail_sets SET {NEW_COLUMN} = ? {WHERE}"
        for value in (ESTIMATE, "{}", None):
            db.execute(update, (value, *KEY))
        for invalid in ("[]", "not json", "12"):
            with self.subTest(value=invalid), self.assertRaises(sqlite3.IntegrityError):
                db.execute(update, (invalid, *KEY))

    def test_a_failing_upgrade_leaves_every_release_unchanged(self) -> None:
        def failing_last_step(connection: Any) -> None:
            migrations._upgrade_v24_to_v25(connection)
            raise RuntimeError("injected migration failure")

        for release in RELEASES:
            with self.subTest(release=release):
                db = self.populated(release)
                before = list(db.iterdump())
                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V24: (SHAPE_SCHEMA_V25, failing_last_step)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], release
                )

    def test_a_restart_with_the_same_build_changes_nothing(self) -> None:
        for release in RELEASES:
            with self.subTest(release=release), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "upgrade.db"
                source = self.populated(release)
                target = connect(path)
                source.backup(target)
                try:
                    migrate_schema(target)
                    target.commit()
                    upgraded = list(target.iterdump())
                finally:
                    target.close()
                reopened = connect(path)
                try:
                    migrate_schema(reopened)
                    self.assertEqual(list(reopened.iterdump()), upgraded)
                finally:
                    reopened.close()

    def test_an_estimate_written_after_the_upgrade_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "estimated.db"
            source = self.populated(21)
            target = connect(path)
            source.backup(target)
            try:
                migrate_schema(target)
                target.execute(
                    f"UPDATE activity_detail_sets SET {NEW_COLUMN} = ? {WHERE}",
                    (ESTIMATE, *KEY),
                )
                target.commit()
            finally:
                target.close()
            reopened = connect(path)
            try:
                migrate_schema(reopened)
                self.assertEqual(
                    reopened.execute(
                        f"SELECT {NEW_COLUMN} FROM activity_detail_sets {WHERE}", KEY
                    ).fetchone()[0],
                    ESTIMATE,
                )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
