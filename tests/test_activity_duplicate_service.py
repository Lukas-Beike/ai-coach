from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import Mock

from duplicate_support import (
    FETCHED_AT,
    GARMIN_ID,
    START,
    WAHOO_ID,
    DuplicateCase,
    seed_pair,
)

from backend.activities.activity_reference import ActivityReferences
from backend.activities.duplicate_service import DuplicateActivityService
from backend.canonical.vocabulary import ProviderId, RecordingOrigin
from backend.db import canonical_store
from backend.errors import AppError
from backend.performance.canonical_detail import read_reference
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND

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
        self.wahoo_session, self.garmin_session = seed_pair(self)
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

    def test_no_session_is_left_merged_into_a_deleted_session(self) -> None:
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

    def test_the_wahoo_ride_detail_reference_is_its_own_session(self) -> None:
        # read_reference must not follow the alias to the deleted survivor.
        with self.manager.reader() as db:
            self.assertEqual(read_reference(db, WAHOO_ID), self.wahoo_session)
            self.assertEqual(read_reference(db, self.wahoo_session), self.wahoo_session)

    def test_the_wahoo_session_is_the_active_survivor_and_keeps_the_copys_feedback(
        self,
    ) -> None:
        sessions = {
            row["activity_id"]: row
            for row in self.query(
                "SELECT activity_id, state, merged_into, merged_into_retained "
                "FROM activity_sessions"
            )
        }
        self.assertEqual(sessions[self.wahoo_session]["state"], "active")
        self.assertIsNone(sessions[self.wahoo_session]["merged_into"])
        self.assertEqual(sessions[self.garmin_session]["state"], "deleted")
        self.assertEqual(
            sessions[self.garmin_session]["merged_into_retained"], self.wahoo_session
        )


class SeveralAliasesTests(DuplicateCase):
    """A deleted survivor with two live aliases: the oldest alias takes over."""

    def test_the_oldest_alias_becomes_the_survivor_and_the_other_merges_into_it(
        self,
    ) -> None:
        survivor = self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            fetched_at="2026-09-20T08:00:00+00:00",
        )
        first = self.seed(
            WAHOO_ID,
            recorded_by=RecordingOrigin.WAHOO,
            fetched_at="2026-09-20T09:00:00+00:00",
        )
        second = self.seed(
            "wahoo-2",
            recorded_by=RecordingOrigin.WAHOO,
            started_at=START + timedelta(hours=3),
            fetched_at="2026-09-20T10:00:00+00:00",
        )
        self.merge(first, survivor)
        self.merge(second, survivor)

        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id=GARMIN_ID,
                now=DELETED_AT,
            )

        rows = {
            row["activity_id"]: row
            for row in self.query(
                "SELECT activity_id, state, merged_into, merged_into_retained "
                "FROM activity_sessions"
            )
        }
        self.assertEqual(
            (rows[first]["state"], rows[first]["merged_into"]), ("active", None)
        )
        self.assertEqual(
            (rows[second]["state"], rows[second]["merged_into"]),
            ("duplicate", first),
        )
        self.assertEqual(
            (rows[survivor]["state"], rows[survivor]["merged_into_retained"]),
            ("deleted", first),
        )

    def test_a_provider_disappearance_repairs_the_same_way(self) -> None:
        survivor = self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            fetched_at="2026-09-20T08:00:00+00:00",
        )
        alias = self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO)
        self.merge(alias, survivor)

        with self.manager.unit_of_work() as db:
            deleted = canonical_store.mark_missing_deleted(
                db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                window_start=START.date(),
                window_end=START.date(),
                present_ids=frozenset({WAHOO_ID}),
                now=DELETED_AT,
            )

        self.assertEqual(deleted, 1)
        with self.manager.reader() as db:
            self.assertEqual(read_reference(db, WAHOO_ID), alias)


if __name__ == "__main__":
    unittest.main()
