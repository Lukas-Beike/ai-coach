"""The athlete confirms, splits and merges canonical sessions, each with an undo.

An Intervals.icu ride and the same ride from Garmin are bundled by session
linking. A split keeps both copies apart through later syncs, a merge bundles
them again, feedback stays with the session it was written for, and every
correction's receipt undoes it. Feedback written on a Garmin-only session still
resolves after the Intervals.icu copy arrives. Temporary database and synthetic
rows only.
"""

from __future__ import annotations

import threading
import unittest
from typing import Any

from backend.activities.session_corrections import SessionCorrectionService
from backend.db import canonical_store
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.sync import canonical_ingest
from tests.test_feedback_session_identity import (
    GARMIN_ID,
    INTERVALS_ID,
    SYNCED,
    ZONE,
    FeedbackSessionFixture,
    intervals_row,
)


class SessionCorrectionFixture(FeedbackSessionFixture):
    def setUp(self) -> None:
        super().setUp()
        self.corrections = SessionCorrectionService(
            self.manager, lambda: "2026-09-21T08:00:00+00:00"
        )
        self.intervals = self.sessions["intervals"]
        self.garmin = self.sessions["garmin"]

    def _effective(self) -> dict[str, str]:
        with self.manager.reader() as db:
            return canonical_store.effective_session_ids(
                db, [self.intervals, self.garmin]
            )

    def _rows(self) -> dict[str, dict[str, Any]]:
        with self.manager.reader() as db:
            return {
                row["activity_id"]: row
                for row in canonical_store.session_correction_rows(
                    db, [self.intervals, self.garmin]
                )
            }

    def _resync(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": "2026-09-22T08:00:00+00:00",
                    "raw_provider_data": {
                        "activities": [intervals_row(INTERVALS_ID, icu_rpe=7)]
                    },
                },
                zone=ZONE,
            )

    def undo(self, change: dict[str, Any]) -> None:
        unused: Any = None
        HistoryUndoService(
            self.manager,
            ChangeHistoryService(
                self.manager, unused, session_corrections=self.corrections
            ),
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            session_corrections=self.corrections,
            profile_mutation_coordinator=threading.RLock(),
        ).apply(
            {"change_id": change["id"], "expected_current_hash": change["after_hash"]}
        )


class SessionCorrectionTests(SessionCorrectionFixture):
    def test_the_bundle_lists_both_provider_copies(self) -> None:
        bundle = self.corrections.bundle(self.garmin)

        assert bundle is not None
        self.assertEqual(bundle["activity_id"], self._effective()[self.garmin])
        self.assertEqual(
            sorted(member["provider"] for member in bundle["members"]),
            ["garmin", "intervals"],
        )
        self.assertFalse(bundle["athlete_confirmed"])
        self.assertEqual(bundle["merge_candidates"], [])

    def test_confirm_marks_the_bundle_and_undo_restores_it(self) -> None:
        survivor = self._effective()[self.intervals]
        before = self._rows()[survivor]

        result = self.corrections.confirm(self.garmin)

        confirmed = self._rows()[survivor]
        self.assertEqual(
            (confirmed["athlete_confirmed"], confirmed["link_kind"]), (1, "confirmed")
        )
        self.undo(result["change"])
        self.assertEqual(self._rows()[survivor], before)

    def test_split_keeps_both_copies_apart_through_later_syncs(self) -> None:
        self.service.save(INTERVALS_ID, {"notes": "Heavy legs", "session_rpe": 6})

        result = self.corrections.split(self.intervals, self.garmin)
        self._resync()

        effective = self._effective()
        self.assertEqual(
            effective, {self.intervals: self.intervals, self.garmin: self.garmin}
        )
        rows = self._rows()
        self.assertTrue(all(row["athlete_confirmed"] for row in rows.values()))
        self.assertTrue(all(row["state"] == "active" for row in rows.values()))
        by_id = {
            item["activity_id"]: item
            for item in self.service.for_activity_ids([INTERVALS_ID, GARMIN_ID])
        }
        self.assertEqual(by_id[INTERVALS_ID]["notes"], "Heavy legs")
        self.assertNotIn(GARMIN_ID, by_id)
        self.assertIsNotNone(result["change"])

    def test_undoing_a_split_restores_the_bundle(self) -> None:
        before = self._rows()
        result = self.corrections.split(self.garmin, self.garmin)

        self.undo(result["change"])

        self.assertEqual(self._rows(), before)
        self.assertEqual(len(set(self._effective().values())), 1)

    def test_merge_bundles_split_sessions_and_undo_splits_them_again(self) -> None:
        self.corrections.split(self.intervals, self.garmin)
        split = self._rows()

        result = self.corrections.merge(self.garmin, self.intervals)

        self.assertEqual(len(set(self._effective().values())), 1)
        survivor = self._rows()[result["activity_id"]]
        self.assertEqual(
            (survivor["link_kind"], survivor["athlete_confirmed"]), ("confirmed", 1)
        )
        self.undo(result["change"])
        self.assertEqual(self._rows(), split)

    def test_merge_refuses_two_copies_from_one_source(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": SYNCED,
                    "raw_provider_data": {
                        "activities": [
                            intervals_row("i2", start_date_local="2026-09-10T18:00:00")
                        ]
                    },
                },
                zone=ZONE,
            )
            other = canonical_store.activity_local_ids(db, "intervals", ["i2"])["i2"]

        with self.assertRaises(AppError) as raised:
            self.corrections.merge(self.intervals, other)

        self.assertEqual(raised.exception.status, 409)
        bundle = self.corrections.bundle(self.intervals)
        assert bundle is not None
        self.assertEqual(
            [candidate["session_id"] for candidate in bundle["merge_candidates"]],
            [other],
        )

    def test_merge_refuses_a_session_of_another_day(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": SYNCED,
                    "raw_provider_data": {
                        "activities": [
                            intervals_row("i3", start_date_local="2026-09-11T07:00:00")
                        ]
                    },
                },
                zone=ZONE,
            )
            other = canonical_store.activity_local_ids(db, "intervals", ["i3"])["i3"]
        self.corrections.split(self.intervals, self.garmin)

        with self.assertRaises(AppError) as raised:
            self.corrections.merge(self.garmin, other)

        self.assertEqual(raised.exception.status, 409)

    def test_a_single_copy_cannot_be_split(self) -> None:
        self.corrections.split(self.intervals, self.garmin)

        with self.assertRaises(AppError) as raised:
            self.corrections.split(self.garmin, self.garmin)

        self.assertEqual(raised.exception.status, 409)

    def test_an_unknown_session_is_not_found(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.corrections.confirm("act_missing")

        self.assertEqual(raised.exception.status, 404)
        self.assertIsNone(self.corrections.bundle("act_missing"))


class FeedbackAnchorTests(FeedbackSessionFixture):
    """Feedback on a Garmin-only session resolves after the Intervals.icu copy arrives."""

    def setUp(self) -> None:
        super().setUp()
        with self.manager.unit_of_work() as db:
            # Start over with the Garmin copy alone: tombstone the Intervals copy.
            canonical_store.mark_activity_deleted(
                db,
                "intervals",
                record_kind="activity",
                provider_activity_id=INTERVALS_ID,
                now=SYNCED,
            )

    def test_feedback_written_before_the_intervals_copy_still_resolves(self) -> None:
        garmin = self.sessions["garmin"]
        self.service.save(garmin, {"notes": "Windy", "session_rpe": 4})

        with self.manager.unit_of_work() as db:
            canonical_ingest.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": "2026-09-22T08:00:00+00:00",
                    "raw_provider_data": {"activities": [intervals_row("i9")]},
                },
                zone=ZONE,
            )
            later = canonical_store.activity_local_ids(db, "intervals", ["i9"])["i9"]
            effective = canonical_store.effective_session_ids(db, [garmin, later])

        self.assertEqual(effective[garmin], effective[later])
        by_id = {
            item["activity_id"]: item
            for item in self.service.for_activity_ids(["i9", garmin])
        }
        self.assertEqual(by_id["i9"]["notes"], "Windy")
        self.assertEqual(by_id[garmin]["session_rpe"], 4)


if __name__ == "__main__":
    unittest.main()
