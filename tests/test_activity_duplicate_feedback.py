"""Athlete feedback survives the confirmed delete of a Wahoo/Garmin duplicate copy.

Feedback belongs to the canonical session it was written for (Epic B). The delete
tombstones the Garmin copy's session; the Wahoo ride must keep showing the
feedback of both, in either merge direction. Temporary database, synthetic rows.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from duplicate_support import GARMIN_ID, WAHOO_ID, DuplicateCase

from backend.activities.activity_reference import ActivityReferences
from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.feedback import ActivityFeedbackService
from backend.canonical.vocabulary import RecordingOrigin
from backend.db.repositories import ActivityFeedbackRepository

OLDER = "2026-09-20T09:00:00+00:00"


class DuplicateFeedbackTests(DuplicateCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = iter(
            f"2026-09-20T12:00:{second:02d}+00:00" for second in range(60)
        )
        self.feedback = ActivityFeedbackService(
            self.manager,
            ActivityFeedbackRepository(lambda: next(self.clock)),
            self.reader,
            references=ActivityReferences(self.manager),
        )
        self.service = DuplicateActivityService(
            self.manager, self.inspector, lambda: "2026-09-20T11:00:00+00:00", Mock()
        )

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

    def shown(self, activity_id: str) -> dict[str, object]:
        by_id = {
            item["activity_id"]: item
            for item in self.feedback.for_activity_ids([activity_id])
        }
        return by_id.get(activity_id, {})

    def seed_pair_with_copy_as_alias(self) -> None:
        wahoo, garmin = self.seed_pair()
        self.merge(garmin, wahoo)

    def seed_pair_with_copy_as_survivor(self) -> None:
        # The older session survives a merge, so the Garmin copy is seeded first.
        garmin = self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            duration_s=3580.0,
            fetched_at=OLDER,
        )
        wahoo = self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO)
        self.merge(wahoo, garmin)

    def test_feedback_on_the_copy_moves_to_the_wahoo_ride_when_the_copy_is_an_alias(
        self,
    ) -> None:
        self.seed_pair_with_copy_as_alias()
        self.feedback.save(GARMIN_ID, {"notes": "Heavy legs", "session_rpe": 6})

        self.delete_copy()

        self.assertEqual(self.shown(WAHOO_ID).get("notes"), "Heavy legs")
        self.assertEqual(self.shown(WAHOO_ID).get("session_rpe"), 6)

    def test_feedback_on_both_copies_stays_one_group_on_the_wahoo_ride(self) -> None:
        self.seed_pair_with_copy_as_alias()
        self.feedback.save(WAHOO_ID, {"notes": "Own note"})
        self.feedback.save(GARMIN_ID, {"session_rpe": 4})

        self.delete_copy()

        shown = self.shown(WAHOO_ID)
        self.assertIn(shown.get("notes"), {"Own note", None})
        self.assertEqual(len(self.feedback.list()), 1)

    def test_feedback_stays_on_the_wahoo_ride_when_the_copy_was_the_survivor(
        self,
    ) -> None:
        self.seed_pair_with_copy_as_survivor()
        self.feedback.save(WAHOO_ID, {"notes": "Wahoo note"})
        self.feedback.save(GARMIN_ID, {"session_rpe": 4})

        self.delete_copy()

        self.assertEqual(self.shown(WAHOO_ID).get("notes"), "Wahoo note")
        self.assertEqual(len(self.feedback.list()), 1)
        # The Wahoo ride can still be edited, in the same group.
        self.feedback.save(WAHOO_ID, {"session_rpe": 7})
        self.assertEqual(self.shown(WAHOO_ID).get("session_rpe"), 7)
        self.assertEqual(len(self.feedback.list()), 1)

    def test_feedback_on_an_unlinked_copy_stays_stored_with_the_deleted_copy(
        self,
    ) -> None:
        # The copy was never merged: its feedback keeps the session it was written
        # for. This is the existing behaviour of any deleted provider copy.
        self.seed_pair()
        self.feedback.save(GARMIN_ID, {"notes": "On the copy"})

        self.delete_copy()

        self.assertEqual(len(self.feedback.list()), 1)
        self.assertEqual(self.shown(GARMIN_ID).get("notes"), "On the copy")
        self.assertEqual(self.shown(WAHOO_ID), {})


if __name__ == "__main__":
    unittest.main()
