"""A restored release v13 backup upgrades and keeps its activity notes.

Temporary database and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db.migrations import migrate_schema
from backend.db.schema import CURRENT_SCHEMA_VERSION, database_schema_is_current

V13_FIXTURE = Path(__file__).with_name("fixtures") / "schema_v13.sql.txt"


def service(data_dir: Path) -> DatabaseRestoreValidationService:
    return DatabaseRestoreValidationService(
        DatabaseRestoreValidationConfig(
            data_dir=data_dir,
            maximum_bytes=10_000_000,
            app_password="",
            sqlcipher_available=False,
            sqlite_backend=sqlite3,
            configure_cipher=Mock(),
            row_factory=sqlite3.Row,
            schema_is_current=database_schema_is_current,
            migrate_schema=migrate_schema,
        )
    )


class ReleaseV13RestoreTests(unittest.TestCase):
    def test_validate_upgrades_a_populated_release_v13_backup(self) -> None:
        stamp = "2026-10-16T08:00:00+00:00"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(V13_FIXTURE.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO activity_sessions(activity_id, primary_provider, "
                    "primary_provider_activity_id, started_at, created_at, updated_at) "
                    "VALUES ('act_1', 'intervals', 'i1', ?, ?, ?)",
                    (stamp, stamp, stamp),
                )
                connection.execute(
                    "INSERT INTO activity_feedback(activity_id, notes, created_at, "
                    "updated_at) VALUES ('act_1', 'Locker', ?, ?)",
                    (stamp, stamp),
                )
                connection.commit()
            service(Path(directory)).validate(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.row_factory = sqlite3.Row
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertTrue(database_schema_is_current(connection))
                rows = connection.execute(
                    "SELECT activity_id, notes, session_id FROM activity_feedback"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in rows], [("act_1", "Locker", "act_1")]
                )


if __name__ == "__main__":
    unittest.main()
