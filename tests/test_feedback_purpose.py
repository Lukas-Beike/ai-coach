"""The athlete's purpose marking on activity feedback: receipt, undo, groups, Coach.

Built on the two-provider session of ``test_feedback_session_identity``. The
marking shares the receipts, undo and merge groups of the feedback rows, applies
to every row of a group, survives feedback edits that omit it and is served to
the activity summaries per live session id. Temporary database and synthetic
rows only.
"""

from __future__ import annotations

import threading
import unittest
from typing import Any

from test_feedback_session_identity import (
    GARMIN_ID,
    INTERVALS_ID,
    FeedbackSessionFixture,
    merged_session_id,
    stored_rows,
)

from backend.activities.feedback import (
    normalize_activity_feedback,
    session_purpose_marks,
)
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService


class FeedbackPurposeTests(FeedbackSessionFixture):
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

    def marks(self) -> dict[str, str]:
        with self.manager.reader() as db:
            return session_purpose_marks(db)

    def test_a_marking_alone_is_stored_with_a_receipt(self) -> None:
        saved = self.service.save(GARMIN_ID, {"purpose": "commute"})

        self.assertEqual(saved["activity_feedback"]["purpose"], "commute")
        self.assertEqual(saved["activity_feedback"]["notes"], "")
        self.assertIsNotNone(saved["change"])
        (row,) = stored_rows(self)
        self.assertEqual(row["purpose"], "commute")
        self.assertEqual(self.marks(), {merged_session_id(self): "commute"})

    def test_undo_restores_the_previous_marking_and_then_none(self) -> None:
        first = self.service.save(GARMIN_ID, {"purpose": "commute"})
        second = self.service.save(GARMIN_ID, {"purpose": "training"})
        self.assertEqual(stored_rows(self)[0]["purpose"], "training")

        self.undo(second["change"])
        self.assertEqual(stored_rows(self)[0]["purpose"], "commute")
        self.assertEqual(list(self.marks().values()), ["commute"])

        self.undo(first["change"])
        self.assertEqual(stored_rows(self), [])
        self.assertEqual(self.marks(), {})

    def test_feedback_edits_keep_an_omitted_marking(self) -> None:
        self.service.save(GARMIN_ID, {"purpose": "race"})

        saved = self.service.save(GARMIN_ID, {"notes": "Felt strong", "session_rpe": 8})

        self.assertEqual(saved["activity_feedback"]["purpose"], "race")
        self.assertEqual(stored_rows(self)[0]["purpose"], "race")

    def test_deleting_the_feedback_keeps_the_marking(self) -> None:
        self.service.save(
            GARMIN_ID, {"notes": "Felt strong", "session_rpe": 8, "purpose": "race"}
        )

        self.service.save(
            GARMIN_ID, {"notes": "", "session_rpe": None, "deviation_reason": ""}
        )

        (row,) = stored_rows(self)
        self.assertEqual(
            (row["notes"], row["session_rpe"], row["purpose"]), ("", None, "race")
        )

    def test_clearing_the_marking_removes_a_row_without_other_feedback(self) -> None:
        self.service.save(GARMIN_ID, {"purpose": "warmup"})

        cleared = self.service.save(GARMIN_ID, {"purpose": None})

        self.assertIsNone(cleared["activity_feedback"])
        self.assertEqual(stored_rows(self), [])
        self.assertEqual(self.marks(), {})

    def test_clearing_the_marking_keeps_other_feedback(self) -> None:
        self.service.save(GARMIN_ID, {"notes": "Easy", "purpose": "warmup"})

        self.service.save(GARMIN_ID, {"purpose": None})

        (row,) = stored_rows(self)
        self.assertEqual((row["notes"], row["purpose"]), ("Easy", None))

    def test_an_unknown_purpose_is_rejected_without_a_change(self) -> None:
        for purpose in ("party", "Race", 3, ["race"]):
            with self.subTest(purpose=purpose), self.assertRaises(AppError) as caught:
                self.service.save(GARMIN_ID, {"purpose": purpose})
            self.assertEqual(caught.exception.status, 400)
        self.assertEqual(stored_rows(self), [])

    def test_normalization_accepts_the_five_purposes_and_blank_as_none(self) -> None:
        for purpose in ("training", "race", "commute", "warmup", "cooldown"):
            self.assertEqual(
                normalize_activity_feedback("a", {"purpose": purpose})["purpose"],
                purpose,
            )
        for blank in (None, ""):
            self.assertIsNone(
                normalize_activity_feedback("a", {"purpose": blank})["purpose"]
            )
        self.assertNotIn("purpose", normalize_activity_feedback("a", {"notes": "x"}))

    def test_the_marking_applies_to_every_row_of_a_merged_group(self) -> None:
        # One row per provider copy of the session; the newer one is shown.
        session = merged_session_id(self)
        self.store_legacy(
            INTERVALS_ID, "Old", "2026-09-20T10:00:00+00:00", session=session
        )
        self.store_legacy(
            GARMIN_ID, "New", "2026-09-20T11:00:00+00:00", session=session
        )

        self.service.save(GARMIN_ID, {"purpose": "cooldown"})

        self.assertEqual(
            [row["purpose"] for row in stored_rows(self)], ["cooldown", "cooldown"]
        )
        self.assertEqual(self.marks(), {session: "cooldown"})

        self.service.save(GARMIN_ID, {"purpose": None})

        self.assertEqual([row["purpose"] for row in stored_rows(self)], [None, None])
        self.assertEqual(self.marks(), {})

    def test_a_hidden_older_marking_never_wins_over_the_shown_row(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(
            INTERVALS_ID, "Old", "2026-09-20T10:00:00+00:00", session=session
        )
        self.store_legacy(
            GARMIN_ID, "New", "2026-09-20T11:00:00+00:00", session=session
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_feedback SET purpose = 'race' WHERE activity_id = ?",
                (INTERVALS_ID,),
            )

        self.assertEqual(self.marks(), {})

    def test_the_coach_marks_a_session_and_needs_something_to_save(self) -> None:
        saved = self.service.save_coach(GARMIN_ID, {"purpose": "race"})

        self.assertEqual(saved["activity_feedback"]["purpose"], "race")
        self.assertEqual(stored_rows(self)[0]["purpose"], "race")
        cleared = self.service.save_coach(GARMIN_ID, {"purpose": None})
        self.assertIsNone(cleared["activity_feedback"])
        with self.assertRaises(AppError) as empty:
            self.service.save_coach(GARMIN_ID, {"notes": ""})
        self.assertEqual(empty.exception.status, 400)

    def test_a_row_without_a_session_marks_no_session(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO activity_feedback(activity_id, created_at, updated_at, "
                "purpose) VALUES ('unknown-id', 'x', 'x', 'commute')"
            )

        self.assertEqual(self.marks(), {})


if __name__ == "__main__":
    unittest.main()
