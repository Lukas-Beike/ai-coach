"""The athlete confirms, splits and merges canonical sessions, each with an undo.

A Wahoo ride and the same ride from Garmin are bundled by session
linking. A split keeps both copies apart through later syncs, a merge bundles
them again, feedback stays with the session it was written for, and every
correction's receipt undoes it. Feedback written on a Garmin-only session still
resolves after the Wahoo copy arrives. Temporary database and synthetic
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
from tests.test_feedback_session_identity import (
    GARMIN_ID,
    WAHOO_ID,
    FeedbackSessionFixture,
    ingest_wahoo,
    wahoo_row,
)


class SessionCorrectionFixture(FeedbackSessionFixture):
    def setUp(self) -> None:
        super().setUp()
        self.load_input_changes: list[bool] = []
        self.corrections = SessionCorrectionService(
            self.manager,
            lambda: "2026-09-21T08:00:00+00:00",
            on_change=lambda: self.load_input_changes.append(True),
        )
        self.wahoo = self.sessions["wahoo"]
        self.garmin = self.sessions["garmin"]

    def _effective(self) -> dict[str, str]:
        with self.manager.reader() as db:
            return canonical_store.effective_session_ids(db, [self.wahoo, self.garmin])

    def _rows(self) -> dict[str, dict[str, Any]]:
        with self.manager.reader() as db:
            return {
                row["activity_id"]: row
                for row in canonical_store.session_correction_rows(
                    db, [self.wahoo, self.garmin]
                )
            }

    def _resync(self) -> None:
        with self.manager.unit_of_work() as db:
            ingest_wahoo(db, [wahoo_row(WAHOO_ID)], "2026-09-22T08:00:00+00:00")

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
            ["garmin", "wahoo"],
        )
        self.assertFalse(bundle["athlete_confirmed"])
        self.assertEqual(bundle["merge_candidates"], [])

    def test_confirm_marks_the_bundle_and_undo_restores_it(self) -> None:
        survivor = self._effective()[self.wahoo]
        before = self._rows()[survivor]

        result = self.corrections.confirm(self.garmin)

        confirmed = self._rows()[survivor]
        self.assertEqual(
            (confirmed["athlete_confirmed"], confirmed["link_kind"]), (1, "confirmed")
        )
        self.undo(result["change"])
        self.assertEqual(self._rows()[survivor], before)

    def test_correction_and_its_undo_request_a_local_load_pass(self) -> None:
        result = self.corrections.split(self.wahoo, self.garmin)
        self.assertEqual(self.load_input_changes, [True])
        self.undo(result["change"])
        self.assertEqual(self.load_input_changes, [True, True])

    def test_split_keeps_both_copies_apart_through_later_syncs(self) -> None:
        self.service.save(WAHOO_ID, {"notes": "Heavy legs", "session_rpe": 6})

        result = self.corrections.split(self.wahoo, self.garmin)
        self._resync()

        effective = self._effective()
        self.assertEqual(effective, {self.wahoo: self.wahoo, self.garmin: self.garmin})
        rows = self._rows()
        self.assertTrue(all(row["athlete_confirmed"] for row in rows.values()))
        self.assertTrue(all(row["state"] == "active" for row in rows.values()))
        by_id = {
            item["activity_id"]: item
            for item in self.service.for_activity_ids([WAHOO_ID, GARMIN_ID])
        }
        self.assertEqual(by_id[WAHOO_ID]["notes"], "Heavy legs")
        self.assertNotIn(GARMIN_ID, by_id)
        self.assertIsNotNone(result["change"])

    def test_undoing_a_split_restores_the_bundle(self) -> None:
        before = self._rows()
        result = self.corrections.split(self.garmin, self.garmin)

        self.undo(result["change"])

        self.assertEqual(self._rows(), before)
        self.assertEqual(len(set(self._effective().values())), 1)

    def test_merge_bundles_split_sessions_and_undo_splits_them_again(self) -> None:
        self.corrections.split(self.wahoo, self.garmin)
        split = self._rows()

        result = self.corrections.merge(self.garmin, self.wahoo)

        self.assertEqual(len(set(self._effective().values())), 1)
        survivor = self._rows()[result["activity_id"]]
        self.assertEqual(
            (survivor["link_kind"], survivor["athlete_confirmed"]), ("confirmed", 1)
        )
        self.undo(result["change"])
        self.assertEqual(self._rows(), split)

    def test_a_single_copy_cannot_be_split(self) -> None:
        self.corrections.split(self.wahoo, self.garmin)

        with self.assertRaises(AppError) as raised:
            self.corrections.split(self.garmin, self.garmin)

        self.assertEqual(raised.exception.status, 409)

    def test_an_unknown_session_is_not_found(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.corrections.confirm("act_missing")

        self.assertEqual(raised.exception.status, 404)
        self.assertIsNone(self.corrections.bundle("act_missing"))

    def test_merge_refuses_two_copies_from_one_source(self) -> None:
        with self.manager.unit_of_work() as db:
            ingest_wahoo(db, [wahoo_row("602", starts="2026-09-10T16:00:00.000Z")])
            other = canonical_store.activity_local_ids(db, "wahoo", ["602"])["602"]

        with self.assertRaises(AppError) as raised:
            self.corrections.merge(self.wahoo, other)

        self.assertEqual(raised.exception.status, 409)
        bundle = self.corrections.bundle(self.wahoo)
        assert bundle is not None
        self.assertEqual(bundle["merge_candidates"], [])

    def test_merge_refuses_a_session_of_another_day(self) -> None:
        with self.manager.unit_of_work() as db:
            ingest_wahoo(db, [wahoo_row("603", starts="2026-09-11T05:00:00.000Z")])
            other = canonical_store.activity_local_ids(db, "wahoo", ["603"])["603"]
        self.corrections.split(self.wahoo, self.garmin)

        with self.assertRaises(AppError) as raised:
            self.corrections.merge(self.garmin, other)

        self.assertEqual(raised.exception.status, 409)


class SessionDeleteTests(SessionCorrectionFixture):
    def _live(self) -> list[str]:
        with self.manager.reader() as db:
            return [
                session
                for session, _ in canonical_store.active_session_activity_rows(db)
            ]

    def test_delete_removes_the_activity_and_every_copy(self) -> None:
        self.corrections.delete(self.garmin)

        self.assertEqual(self._live(), [])
        rows = self._rows()
        self.assertTrue(all(row["state"] == "deleted" for row in rows.values()))
        self.assertIsNone(self.corrections.bundle(self.garmin))

    def test_undoing_a_delete_restores_the_activity(self) -> None:
        before = self._rows()
        result = self.corrections.delete(self.garmin)

        self.undo(result["change"])

        self.assertEqual(self._rows(), before)
        self.assertEqual(len(set(self._live())), 1)

    def test_no_copy_comes_back_after_provider_deletes_or_edits(self) -> None:
        self.corrections.delete(self.wahoo)
        with self.manager.unit_of_work() as db:
            ingest_wahoo(
                db, [wahoo_row(WAHOO_ID, distance="20100")], "2026-09-22T08:00:00+00:00"
            )
            canonical_store.mark_activity_deleted(
                db,
                "wahoo",
                record_kind="activity",
                provider_activity_id=WAHOO_ID,
                now="2026-09-23T08:00:00+00:00",
            )
            record = canonical_store.provider_activity_record_rows(
                db, "wahoo", [WAHOO_ID]
            )

        self.assertEqual(self._live(), [])
        self.assertEqual(record, [])
        self.assertTrue(all(row["state"] == "deleted" for row in self._rows().values()))


class AthleteDeleteFollowUpTests(SessionCorrectionFixture):
    def test_undo_is_refused_once_the_provider_deleted_the_primary(self) -> None:
        survivor = self._effective()[self.wahoo]
        provider, record = (
            ("wahoo", WAHOO_ID) if survivor == self.wahoo else ("garmin", GARMIN_ID)
        )
        result = self.corrections.delete(self.wahoo)
        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                provider,
                record_kind="activity",
                provider_activity_id=record,
                now="2026-09-23T08:00:00+00:00",
            )

        with self.assertRaises(AppError) as raised:
            self.undo(result["change"])

        self.assertEqual(raised.exception.status, 409)

    def test_a_later_copy_of_a_deleted_activity_stays_deleted(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                "wahoo",
                record_kind="activity",
                provider_activity_id=WAHOO_ID,
                now="2026-09-20T08:00:00+00:00",
            )
        self.corrections.delete(self.garmin)
        with self.manager.unit_of_work() as db:
            ingest_wahoo(
                db,
                [wahoo_row("607", starts="2026-09-10T05:02:00.000Z")],
                "2026-09-22T08:00:00+00:00",
            )
            live = canonical_store.active_session_activity_rows(db)

        self.assertEqual(live, [])

    def test_undoing_the_delete_brings_a_later_copy_back(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                "wahoo",
                record_kind="activity",
                provider_activity_id=WAHOO_ID,
                now="2026-09-20T08:00:00+00:00",
            )
        result = self.corrections.delete(self.garmin)
        with self.manager.unit_of_work() as db:
            ingest_wahoo(
                db,
                [wahoo_row("607", starts="2026-09-10T05:02:00.000Z")],
                "2026-09-22T08:00:00+00:00",
            )

        self.undo(result["change"])

        with self.manager.reader() as db:
            live = canonical_store.active_session_activity_rows(db)
        self.assertEqual(
            sorted(row["provider_activity_id"] for _, row in live), ["607", "910"]
        )
        self.assertEqual(len({session for session, _ in live}), 1)


if __name__ == "__main__":
    unittest.main()
