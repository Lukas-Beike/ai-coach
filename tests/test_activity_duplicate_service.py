from __future__ import annotations

import unittest
from unittest.mock import Mock

from duplicate_support import FETCHED_AT, GARMIN_ID, WAHOO_ID, DuplicateCase

from backend.activities.activity_reference import ActivityReferences
from backend.activities.duplicate_service import DuplicateActivityService
from backend.canonical.vocabulary import RecordingOrigin
from backend.errors import AppError
from backend.performance.canonical_detail import read_reference

DELETED_AT = "2026-09-20T11:00:00+00:00"
SNAPSHOT_SYNCED_AT = "2026-09-20T09:00:00+00:00"


class _Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def publish(self, event: str, payload: dict) -> None:
        self.published.append((event, payload))


class DuplicateDeleteTests(DuplicateCase):
    """The confirmed delete on synthetic Intervals.icu sessions, with no snapshot read."""

    def setUp(self) -> None:
        super().setUp()
        self.wahoo_session, self.garmin_session = self.seed_pair()
        self.intervals = Mock()
        self.events = _Events()
        self.service = DuplicateActivityService(
            self.manager, self.inspector, lambda: DELETED_AT, self.events
        )

    def payload(self, **changes: str) -> dict[str, str]:
        return {
            "canonical_id": WAHOO_ID,
            "duplicate_id": GARMIN_ID,
            "snapshot_synced_at": FETCHED_AT,
            **changes,
        }

    def states(self) -> dict[str, list[object]]:
        return {
            table: [row["state"] for row in self.query(f"SELECT state FROM {table}")]
            for table in ("activity_records", "provider_records", "activity_sessions")
        }

    def store_snapshot(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO snapshots(payload, created_at, synced_at, "
                "recent_activity_count) VALUES ('{}', ?, ?, 0)",
                (SNAPSHOT_SYNCED_AT, SNAPSHOT_SYNCED_AT),
            )

    def test_confirmed_delete_removes_only_the_garmin_copy_remotely(self) -> None:
        result = self.service.delete(self.payload(), self.intervals)

        self.intervals.delete_activity.assert_called_once_with(GARMIN_ID)
        self.assertEqual(
            result,
            {
                "status": "deleted",
                "deleted_activity_id": GARMIN_ID,
                "kept_activity_id": WAHOO_ID,
                "kept_source": "Wahoo",
            },
        )
        self.assertEqual(
            self.events.published,
            [("provider", {"provider": "intervals", "status": "duplicate_deleted"})],
        )

    def test_delete_tombstones_the_copy_and_keeps_the_wahoo_ride(self) -> None:
        self.service.delete(self.payload(), self.intervals)

        copy = self.query(
            "SELECT s.state, r.state AS record_state, s.merged_into "
            "FROM activity_records AS r JOIN activity_sessions AS s "
            "ON s.activity_id = r.activity_id WHERE r.provider_activity_id = ?",
            (GARMIN_ID,),
        )
        kept = self.query(
            "SELECT s.state, r.state AS record_state "
            "FROM activity_records AS r JOIN activity_sessions AS s "
            "ON s.activity_id = r.activity_id WHERE r.provider_activity_id = ?",
            (WAHOO_ID,),
        )
        self.assertEqual(
            copy, [{"state": "deleted", "record_state": "deleted", "merged_into": None}]
        )
        self.assertEqual(kept, [{"state": "active", "record_state": "active"}])
        provider_records = {
            row["source_record_id"]: row["state"]
            for row in self.query(
                "SELECT source_record_id, state FROM provider_records"
            )
        }
        self.assertEqual(provider_records, {WAHOO_ID: "active", GARMIN_ID: "deleted"})
        with self.manager.reader() as db:
            served = {record.activity_id for record in self.reader.activities(db)}
        self.assertEqual(served, {WAHOO_ID})
        self.assertIsNone(self.inspector.latest())

    def test_delete_never_touches_the_snapshot(self) -> None:
        self.store_snapshot()

        self.service.delete(self.payload(), self.intervals)

        self.assertEqual(
            self.query("SELECT synced_at, created_at FROM snapshots"),
            [{"synced_at": SNAPSHOT_SYNCED_AT, "created_at": SNAPSHOT_SYNCED_AT}],
        )

    def test_merged_alias_session_is_tombstoned_in_the_same_transaction(self) -> None:
        self.merge(self.garmin_session, self.wahoo_session)

        self.service.delete(self.payload(), self.intervals)

        self.assertEqual(
            self.query(
                "SELECT state, merged_into FROM activity_sessions WHERE activity_id = ?",
                (self.garmin_session,),
            ),
            [{"state": "deleted", "merged_into": None}],
        )
        self.assertEqual(
            self.query(
                "SELECT state FROM activity_records WHERE provider_activity_id = ?",
                (GARMIN_ID,),
            ),
            [{"state": "deleted"}],
        )

    def test_stale_confirmation_has_no_side_effects(self) -> None:
        before = self.states()
        for label, changes in (
            ("duplicate id", {"duplicate_id": "old-garmin"}),
            ("keep id", {"canonical_id": "old-wahoo"}),
            ("token", {"snapshot_synced_at": "2026-09-19T00:00:00+00:00"}),
            ("missing token", {"snapshot_synced_at": ""}),
        ):
            with self.subTest(label), self.assertRaises(AppError) as raised:
                self.service.delete(self.payload(**changes), self.intervals)
            self.assertEqual(raised.exception.status, 409)

        self.intervals.delete_activity.assert_not_called()
        self.assertEqual(self.events.published, [])
        self.assertEqual(self.states(), before)

    def test_a_refetched_record_makes_the_earlier_confirmation_stale(self) -> None:
        self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            duration_s=3580.0,
            fetched_at="2026-09-20T12:00:00+00:00",
        )

        with self.assertRaises(AppError) as raised:
            self.service.delete(self.payload(), self.intervals)

        self.assertEqual(raised.exception.status, 409)
        self.intervals.delete_activity.assert_not_called()

    def test_remote_failure_does_not_mutate_local_data_or_publish(self) -> None:
        before = self.states()
        self.intervals.delete_activity.side_effect = RuntimeError("provider failed")

        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            self.service.delete(self.payload(), self.intervals)

        self.assertEqual(self.states(), before)
        self.assertEqual(self.events.published, [])

    def test_no_current_pair_is_a_conflict(self) -> None:
        self.service.delete(self.payload(), self.intervals)

        with self.assertRaises(AppError) as raised:
            self.service.delete(self.payload(), self.intervals)

        self.assertEqual(raised.exception.status, 409)
        self.intervals.delete_activity.assert_called_once_with(GARMIN_ID)


class SurvivorDeletedAliasTests(DuplicateCase):
    """The Garmin copy is the older session and the Wahoo ride its alias."""

    def setUp(self) -> None:
        super().setUp()
        # The older session survives a merge, so the Garmin copy is seeded first.
        self.garmin_session = self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            duration_s=3580.0,
            fetched_at="2026-09-20T09:00:00+00:00",
        )
        self.wahoo_session = self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO)
        self.merge(self.wahoo_session, self.garmin_session)
        DuplicateActivityService(
            self.manager, self.inspector, lambda: DELETED_AT, _Events()
        ).delete(
            {
                "canonical_id": WAHOO_ID,
                "duplicate_id": GARMIN_ID,
                "snapshot_synced_at": FETCHED_AT,
            },
            Mock(),
        )

    def test_the_wahoo_ride_stays_served_after_its_survivor_is_deleted(self) -> None:
        with self.manager.reader() as db:
            served = {record.activity_id for record in self.reader.activities(db)}
            rows = {row["id"] for row in self.reader.activity_rows(db)}
        self.assertEqual((served, rows), ({WAHOO_ID}, {WAHOO_ID}))

    @unittest.expectedFailure
    def test_no_session_is_left_merged_into_a_deleted_session(self) -> None:
        # Known defect, not accepted behavior: canonical_store._delete_activity
        # tombstones the survivor without re-pointing the aliases merged into it.
        # Its fix edits backend/db/canonical_store.py and waits for the Epic B
        # change (PR #1464, schema v15); see the follow-up in the #1414 report.
        dangling = self.query(
            "SELECT alias.activity_id FROM activity_sessions AS alias "
            "JOIN activity_sessions AS target ON target.activity_id = alias.merged_into "
            "WHERE target.state = 'deleted'"
        )
        self.assertEqual(dangling, [])

    def test_the_wahoo_session_id_still_resolves_for_feedback_references(self) -> None:
        reference = ActivityReferences(self.manager).resolve_reference(
            self.wahoo_session
        )
        self.assertEqual(reference.activity_id, WAHOO_ID)

    @unittest.expectedFailure
    def test_the_wahoo_ride_detail_reference_is_its_own_session(self) -> None:
        # Same known defect: read_reference follows the alias to the deleted
        # survivor, so the detail of the surviving Wahoo ride reads as not found.
        with self.manager.reader() as db:
            self.assertEqual(read_reference(db, WAHOO_ID), self.wahoo_session)
            self.assertEqual(read_reference(db, self.wahoo_session), self.wahoo_session)


if __name__ == "__main__":
    unittest.main()
