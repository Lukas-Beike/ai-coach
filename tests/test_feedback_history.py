"""Feedback saves and clears record receipts whose undo restores every row.

Built on the two-provider session of ``test_feedback_session_identity``: one ride
from Intervals.icu and Garmin. Undo restores the stored rows exactly, hidden
conflicting originals and full-length notes included, keeps one effective
feedback, and works after a restart. Deleting the surviving provider copy keeps
the feedback. Temporary database and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from test_feedback_session_identity import (
    GARMIN_ID,
    INTERVALS_ID,
    SYNCED,
    FeedbackSessionFixture,
    stored_rows,
)

from backend import change_history
from backend.activities.activity_reference import ActivityReferences
from backend.activities.feedback import ActivityFeedbackService
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.coach.change_receipts import change_summary
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.sync.canonical_table_reader import CanonicalTableReader

# Quotes and line breaks double in JSON, so the recorded row is far above 4000.
LONG_NOTES = ('"' + "\n") * 2000


class FeedbackHistoryTests(FeedbackSessionFixture):
    def undo(self, change: dict[str, Any]) -> None:
        unused: Any = None
        HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, feedback_service=self.service),
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            feedback_service=self.service,
            profile_mutation_coordinator=threading.RLock(),
        ).apply(
            {"change_id": change["id"], "expected_current_hash": change["after_hash"]}
        )

    def test_undo_restores_the_previous_feedback(self) -> None:
        created = self.service.save(INTERVALS_ID, {"notes": "First", "session_rpe": 6})
        before = stored_rows(self)
        updated = self.service.save(GARMIN_ID, {"session_rpe": 4})
        self.undo(updated["change"])
        self.assertEqual(stored_rows(self), before)
        self.undo(created["change"])
        self.assertEqual(stored_rows(self), [])

    def test_undoing_a_clear_restores_hidden_originals_and_long_notes(self) -> None:
        with self.manager.unit_of_work() as db:
            for key, session, notes, updated in (
                (INTERVALS_ID, self.sessions["intervals"], LONG_NOTES, "2026-09-19"),
                (GARMIN_ID, self.sessions["garmin"], "newer", "2026-09-20"),
            ):
                db.execute(
                    "INSERT INTO activity_feedback(activity_id, notes, created_at, "
                    "updated_at, session_id) VALUES (?, ?, ?, ?, ?)",
                    (key, notes, updated, updated, session),
                )
        before = stored_rows(self)
        cleared = self.service.save(INTERVALS_ID, {"notes": ""})
        self.assertEqual(stored_rows(self), [])
        self.undo(cleared["change"])

        self.assertEqual(stored_rows(self), before)
        (original,) = [
            row for row in stored_rows(self) if row["activity_id"] == INTERVALS_ID
        ]
        self.assertEqual(original["notes"], LONG_NOTES)
        (effective,) = self.service.list()
        self.assertEqual(effective["notes"], "newer")

    def test_history_keeps_no_feedback_text_in_its_public_view(self) -> None:
        self.service.save(INTERVALS_ID, {"notes": "Private note"})
        with self.manager.reader() as db:
            (row,) = db.execute("SELECT * FROM change_history").fetchall()
        public = change_history.public_view(dict(row))
        self.assertEqual(public["entity_type"], "activity_feedback")
        self.assertNotIn("Private note", str(public))

    def test_feedback_and_its_undo_survive_a_restart(self) -> None:
        saved = self.service.save(INTERVALS_ID, {"notes": "Before restart"})
        path = Path(self.manager.path)
        self.manager.close()
        self.reopen(path)
        (effective,) = self.service.for_activity_ids([GARMIN_ID])
        self.assertEqual(effective["notes"], "Before restart")
        self.undo(saved["change"])
        self.assertEqual(self.service.list(), [])

    def reopen(self, path: Path) -> None:
        self.manager = DatabaseManager(path, sqlite3, row_factory=row_factory)
        self.addCleanup(self.manager.close)
        self.service = ActivityFeedbackService(
            self.manager,
            self.repository,
            CanonicalTableReader(),
            references=ActivityReferences(self.manager),
        )

    def test_a_restored_backup_keeps_every_original_and_its_undo(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO activity_feedback(activity_id, notes, created_at, "
                "updated_at, session_id) VALUES (?, ?, ?, ?, ?)",
                (
                    GARMIN_ID,
                    LONG_NOTES,
                    "2026-09-19",
                    "2026-09-19",
                    self.sessions["garmin"],
                ),
            )
        saved = self.service.save(INTERVALS_ID, {"notes": "Newest"})
        before = stored_rows(self)
        path = Path(self.manager.path)
        backup = DatabaseBackupService(
            self.manager,
            Mock(),
            DatabaseBackupConfig(
                database_path=path,
                data_dir=path.parent,
                maximum_bytes=50_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=60,
                monotonic=lambda: 0.0,
                disk_usage=lambda _path: SimpleNamespace(free=10**12),
            ),
            Mock(),
        ).read_bytes()
        validation = DatabaseRestoreValidationService(
            DatabaseRestoreValidationConfig(
                data_dir=path.parent / "restore",
                maximum_bytes=50_000_000,
                app_password="",
                sqlcipher_available=False,
                sqlite_backend=sqlite3,
                configure_cipher=configure_cipher,
                row_factory=row_factory,
                schema_is_current=database_schema_is_current,
            )
        )
        staged = validation.stage(backup)
        self.addCleanup(staged.unlink, missing_ok=True)
        validation.validate(staged)
        self.reopen(staged)

        self.assertEqual(stored_rows(self), before)
        (effective,) = self.service.list()
        self.assertEqual(effective["notes"], "Newest")
        self.undo(saved["change"])
        (original,) = stored_rows(self)
        self.assertEqual(original["notes"], LONG_NOTES)

    def test_undo_follows_a_session_merged_after_the_edit(self) -> None:
        self.service.save(INTERVALS_ID, {"notes": "First"})
        updated = self.service.save(INTERVALS_ID, {"notes": "Second"})["change"]
        with self.manager.reader() as db:
            effective = canonical_store.effective_session_ids(
                db, [self.sessions["intervals"]]
            )[self.sessions["intervals"]]
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, "
                "primary_provider_activity_id, started_at, created_at, updated_at) "
                "VALUES ('act_survivor', 'intervals', 'survivor', ?, ?, ?)",
                (SYNCED, SYNCED, SYNCED),
            )
            db.execute(
                "UPDATE activity_sessions SET state = 'duplicate', merged_into = ? "
                "WHERE activity_id = ?",
                ("act_survivor", effective),
            )
        self.undo(updated)
        (feedback,) = self.service.list()
        self.assertEqual(feedback["notes"], "First")

    def test_deleting_the_surviving_copy_keeps_the_feedback(self) -> None:
        self.service.save(INTERVALS_ID, {"notes": "On the survivor"})
        with self.manager.unit_of_work() as db:
            self.assertTrue(
                canonical_store.mark_activity_deleted(
                    db,
                    "intervals",
                    record_kind="activity",
                    provider_activity_id=INTERVALS_ID,
                    now=SYNCED,
                )
            )
        (effective,) = self.service.list()
        self.assertEqual(effective["notes"], "On the survivor")

    def test_coach_feedback_turns_are_fully_tracked(self) -> None:
        receipts = [
            {
                "tool": tool,
                "result": {"ok": True},
                "changes": [{"id": "c1", "entity_type": "activity_feedback"}],
            }
            for tool in ("save_activity_feedback", "delete_activity_feedback")
        ]
        summary = change_summary(receipts)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["undoable"])  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
