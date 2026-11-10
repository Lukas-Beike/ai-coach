"""Diagnostics list sessions that hold two active records of one provider and origin."""

from __future__ import annotations

import tempfile
import unittest
from typing import Any

from canonical_detail_support import NOW, add_session_record, open_manager

from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.diagnostics.session_conflicts import summarize_session_conflicts
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND


class SessionConflictDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)

    def summary(self) -> dict[str, object]:
        """Return the origin conflicts alone; the link kind tests read the rest."""
        with self.manager.read_snapshot() as db:
            summary = summarize_session_conflicts(db)
        return {"total": summary["total"], "sessions": summary["sessions"]}

    def full_summary(self) -> dict[str, Any]:
        with self.manager.read_snapshot() as db:
            return summarize_session_conflicts(db)

    def test_exact_link_mismatches_are_no_longer_reported(self) -> None:
        add_session_record(self.manager, ProviderId.GARMIN, "g1", "act_g1")
        add_session_record(self.manager, ProviderId.WAHOO, "w1", "act_w1")

        self.assertEqual({"total", "sessions", "link_kinds"}, set(self.full_summary()))

    def test_link_kinds_follow_the_membership_after_an_alias_is_deleted(self) -> None:
        add_session_record(self.manager, ProviderId.WAHOO, "w1", "act_w1")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g1", "act_g1", merged_into="act_w1"
        )
        add_session_record(self.manager, ProviderId.GARMIN, "g2", "act_g2")
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE activity_sessions SET link_kind = 'heuristic'")
        # The stale kind of act_g2 is not counted: it bundles nothing.
        self.assertEqual(
            {"heuristic": 1, "single": 1}, self.full_summary()["link_kinds"]
        )

        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                "garmin",
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id="g1",
                now=NOW,
            )

        self.assertEqual({"single": 2}, self.full_summary()["link_kinds"])
        with self.manager.read_snapshot() as db:
            stored = db.execute(
                "SELECT activity_id, link_kind FROM activity_sessions "
                "WHERE state = 'active' ORDER BY activity_id"
            ).fetchall()
        # Deleting the alias repaired its survivor; the other stale row is left.
        self.assertEqual(
            [("act_g2", "heuristic"), ("act_w1", "single")],
            [(row["activity_id"], row["link_kind"]) for row in stored],
        )

    def test_lists_a_session_merged_from_two_garmin_records(self) -> None:
        add_session_record(self.manager, ProviderId.INTERVALS, "i1", "act_i1")
        for garmin_id in ("g1", "g2"):
            add_session_record(
                self.manager,
                ProviderId.GARMIN,
                garmin_id,
                f"act_{garmin_id}",
                merged_into="act_i1",
            )
        # A legitimate session: one record per provider and origin.
        add_session_record(self.manager, ProviderId.INTERVALS, "i2", "act_i2")
        add_session_record(
            self.manager,
            ProviderId.INTERVALS,
            "i3",
            "act_i3",
            recorded_by="wahoo",
            merged_into="act_i2",
        )

        self.assertEqual(
            {
                "total": 1,
                "sessions": [
                    {
                        "session_id": "act_i1",
                        "local_date": None,
                        "provider": "garmin",
                        "recorded_by": "garmin",
                        "records": 2,
                    }
                ],
            },
            self.summary(),
        )

    def test_aliases_of_a_deleted_survivor_are_not_listed(self) -> None:
        add_session_record(self.manager, ProviderId.INTERVALS, "i1", "act_i1")
        for garmin_id in ("g1", "g2"):
            add_session_record(
                self.manager,
                ProviderId.GARMIN,
                garmin_id,
                f"act_{garmin_id}",
                merged_into="act_i1",
            )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state='deleted' "
                "WHERE activity_id='act_i1'"
            )

        self.assertEqual({"total": 0, "sessions": []}, self.summary())

    def test_deleted_records_and_sessions_are_not_listed(self) -> None:
        add_session_record(self.manager, ProviderId.INTERVALS, "i1", "act_i1")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g1", "act_g1", merged_into="act_i1"
        )
        add_session_record(
            self.manager, ProviderId.GARMIN, "g2", "act_g2", merged_into="act_i1"
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET state='deleted' "
                "WHERE provider_activity_id='g2'"
            )

        self.assertEqual({"total": 0, "sessions": []}, self.summary())


if __name__ == "__main__":
    unittest.main()
