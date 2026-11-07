"""Activity feedback belongs to the canonical session across provider copies.

An Intervals.icu ride and the same ride from Garmin are ingested, so session
linking bundles them. Feedback saved through either provider id is one effective
feedback of that session; conflicting originals stay stored and are named, a
cleared group stays cleared, an ambiguous id stands alone and a deleted provider
copy keeps its feedback. Temporary database and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import intervals_compaction as intervals_fixture

from backend.activities.activity_reference import ActivityReferences
from backend.activities.feedback import ActivityFeedbackService
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import ActivityFeedbackRepository, KeyValueRepository
from backend.db.schema import initialize_schema
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.report_service import (
    BlockReviewSource,
    TrainingReportReadService,
)
from backend.planning.block_review import block_review, last_completed_test
from backend.planning.season_preparation import load_scenarios
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from tests.test_training_report import (
    _empty_season_source,
    _FakeDatabaseManager,
    _Rows,
    _summary,
)
from tests.test_weekly_progress import _EmptyReader

ZONE = ZoneInfo("Europe/Berlin")
SYNCED = "2026-09-20T08:00:00+00:00"
INTERVALS_ID = "i1"
GARMIN_ID = "910"


def intervals_row(identifier: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "start_date_local": "2026-09-10T07:00:00",
        "type": "Ride",
        "distance": 20000.0,
        "moving_time": 3600,
        "elapsed_time": 3600,
        **extra,
    }


def stored_rows(fixture: Any) -> list[dict[str, Any]]:
    with fixture.manager.reader() as db:
        return sorted(fixture.repository.all(db), key=lambda row: row["activity_id"])


def merged_session_id(case: Any) -> str:
    """The one effective session the case's Intervals and Garmin records lead to."""
    with case.manager.reader() as db:
        effective = canonical_store.effective_session_ids(
            db, list(case.sessions.values())
        )
    (session,) = set(effective.values())
    return session


class FeedbackSessionFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "feedback.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            intervals_fixture.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": SYNCED,
                    "raw_provider_data": {
                        "activities": [intervals_row(INTERVALS_ID, icu_rpe=7)]
                    },
                },
                zone=ZONE,
            )
            GarminSnapshotWriter(
                KeyValueRepository(lambda: SYNCED), lambda: ZONE
            ).write(
                db,
                {
                    "synced_at": SYNCED,
                    "activities": [
                        {
                            "activityId": int(GARMIN_ID),
                            "activityName": "Synthetic ride",
                            "activityType": {"typeKey": "cycling"},
                            "startTimeLocal": "2026-09-10 07:00:00",
                            "distance": 20000.0,
                            "duration": 3600.0,
                        }
                    ],
                },
            )
            self.sessions = {
                provider: canonical_store.activity_local_ids(db, provider, [key])[key]
                for provider, key in (
                    ("intervals", INTERVALS_ID),
                    ("garmin", GARMIN_ID),
                )
            }
        self.clock = iter(
            f"2026-09-20T12:00:{second:02d}+00:00" for second in range(60)
        )
        self.repository = ActivityFeedbackRepository(lambda: next(self.clock))
        self.service = ActivityFeedbackService(
            self.manager,
            self.repository,
            references=ActivityReferences(self.manager),
        )

    def store_legacy(
        self, key: str, notes: str, updated: str, *, session: str | None, rpe=None
    ) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO activity_feedback(activity_id, notes, session_rpe, "
                "created_at, updated_at, session_id) VALUES (?, ?, ?, ?, ?, ?)",
                (key, notes, rpe, updated, updated, session),
            )


class FeedbackSessionTests(FeedbackSessionFixture):
    def test_the_provider_copies_are_one_session(self) -> None:
        with self.manager.reader() as db:
            effective = canonical_store.effective_session_ids(
                db, list(self.sessions.values())
            )
        self.assertEqual(len(set(effective.values())), 1)

    def test_either_provider_id_reads_and_edits_the_same_feedback(self) -> None:
        self.service.save(INTERVALS_ID, {"notes": "Heavy legs", "session_rpe": 6})
        saved = self.service.save(GARMIN_ID, {"session_rpe": 5})["activity_feedback"]

        # The edit through the Garmin id moves the one row to the Garmin session.
        session = self.sessions["garmin"]
        self.assertEqual(
            (saved["activity_id"], saved["notes"], saved["session_rpe"]),
            (session, "Heavy legs", 5),
        )
        self.assertEqual([row["activity_id"] for row in stored_rows(self)], [session])
        (effective,) = self.service.list()
        self.assertEqual(effective["session_rpe"], 5)
        by_id = {
            item["activity_id"]: item
            for item in self.service.for_activity_ids([INTERVALS_ID, GARMIN_ID])
        }
        self.assertEqual(by_id[GARMIN_ID]["notes"], by_id[INTERVALS_ID]["notes"])

    def test_feedback_stays_with_the_copy_it_was_written_through(self) -> None:
        # Whichever session survives the bundle, the row is stored under the
        # session of the id it was saved through, so a split keeps it there.
        for written_through, own, other in (
            (INTERVALS_ID, self.sessions["intervals"], self.sessions["garmin"]),
            (GARMIN_ID, self.sessions["garmin"], self.sessions["intervals"]),
        ):
            with self.subTest(written_through):
                self.service.save(written_through, {"notes": "Heavy legs"})
                self.assertEqual(
                    [row["activity_id"] for row in stored_rows(self)], [own]
                )
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "UPDATE activity_sessions SET state = 'active', "
                        "merged_into = NULL, athlete_confirmed = 1"
                    )
                self.assertEqual(
                    [i["notes"] for i in self.service.for_activity_ids([own])],
                    ["Heavy legs"],
                )
                self.assertEqual(self.service.for_activity_ids([other]), [])
                self.service.save(own, {"notes": ""})
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "UPDATE activity_sessions SET state = 'duplicate', "
                        "merged_into = ? WHERE activity_id = ?",
                        (own, other),
                    )

    def test_a_legacy_row_under_the_intervals_id_is_found_for_the_session(self) -> None:
        session = merged_session_id(self)
        for stored_session in (self.sessions["intervals"], None):
            with self.subTest(session=stored_session):
                self.store_legacy(
                    INTERVALS_ID, "legacy", "2026-09-19", session=stored_session, rpe=4
                )
                (found,) = self.service.for_activity_ids([session])
                self.assertEqual(
                    (found["activity_id"], found["notes"], found["session_rpe"]),
                    (session, "legacy", 4),
                )
                with self.manager.unit_of_work() as db:
                    db.execute("DELETE FROM activity_feedback")

    def test_a_row_under_the_session_id_wins_over_a_legacy_row(self) -> None:
        session = merged_session_id(self)
        # The legacy row is the newer one, yet the session-id row still wins.
        self.store_legacy(INTERVALS_ID, "legacy", "2026-09-21", session=None, rpe=9)
        self.store_legacy(session, "current", "2026-09-19", session=session, rpe=3)

        (found,) = self.service.for_activity_ids([session])

        self.assertEqual((found["notes"], found["session_rpe"]), ("current", 3))

    def test_a_new_save_over_a_legacy_row_is_stored_under_the_session_id(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(
            INTERVALS_ID, "legacy", "2026-09-19", session=self.sessions["intervals"]
        )

        saved = self.service.save(session, {"session_rpe": 5})["activity_feedback"]

        self.assertEqual(
            (saved["activity_id"], saved["notes"], saved["session_rpe"]),
            (session, "legacy", 5),
        )
        # The effective row moved to the session id; the group did not grow.
        self.assertEqual([row["activity_id"] for row in stored_rows(self)], [session])
        (found,) = self.service.for_activity_ids([session])
        self.assertEqual(found["session_rpe"], 5)
        self.assertNotIn("conflicting_feedback", found)
        self.assertEqual(len(self.service.list()), 1)

    def test_ordinary_edits_never_add_rows_or_conflicts(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(
            INTERVALS_ID,
            "legacy",
            "2026-09-19",
            session=self.sessions["intervals"],
            rpe=4,
        )
        for rpe in (5, 6, 7):
            self.service.save(session, {"session_rpe": rpe})
            self.service.save(INTERVALS_ID, {"notes": f"note {rpe}"})
            # One row, whichever copy the last edit was written through.
            self.assertEqual(len(stored_rows(self)), 1)
            (effective,) = self.service.list()
            self.assertNotIn("conflicting_feedback", effective)
            (found,) = self.service.for_activity_ids([session])
            self.assertNotIn("conflicting_feedback", found)
        self.assertEqual((found["session_rpe"], found["notes"]), (7, "note 7"))

    def test_a_save_keeps_the_fields_of_a_legacy_row_without_a_session(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(INTERVALS_ID, "legacy", "2026-09-19", session=None, rpe=4)

        saved = self.service.save(session, {"deviation_reason": "illness"})
        saved = saved["activity_feedback"]

        self.assertEqual(
            (saved["notes"], saved["session_rpe"], saved["deviation_reason"]),
            ("legacy", 4, "illness"),
        )
        self.assertEqual([row["activity_id"] for row in stored_rows(self)], [session])

    def test_clearing_removes_the_session_row_and_its_legacy_rows(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(INTERVALS_ID, "legacy", "2026-09-21", session=None)
        self.store_legacy(session, "current", "2026-09-19", session=session)

        result = self.service.save(session, {"notes": ""})

        self.assertIsNone(result["activity_feedback"])
        self.assertEqual((self.service.list(), stored_rows(self)), ([], []))
        self.assertEqual(self.service.for_activity_ids([session]), [])

    def test_a_row_of_another_provider_does_not_join_the_session(self) -> None:
        session = merged_session_id(self)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO activity_feedback(activity_id, notes, created_at, "
                "updated_at, provider) VALUES (?, 'other', ?, ?, 'garmin')",
                (INTERVALS_ID, "2026-09-19", "2026-09-19"),
            )
        self.assertEqual(self.service.for_activity_ids([session]), [])
        self.assertEqual([item["notes"] for item in self.service.list()], ["other"])

    def test_an_unambiguous_legacy_row_counts_for_sessions_only(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(INTERVALS_ID, "legacy", "2026-09-19", session=None, rpe=4)

        (found,) = self.service.for_activity_ids([session], sessions_only=True)

        self.assertEqual((found["activity_id"], found["session_rpe"]), (session, 4))

    def test_a_row_under_an_alias_session_id_does_not_beat_a_newer_row(self) -> None:
        session = merged_session_id(self)
        (alias,) = {*self.sessions.values()} - {session}
        self.store_legacy(alias, "old alias", "2026-09-19", session=alias)
        self.store_legacy(INTERVALS_ID, "newer", "2026-09-21", session=session)

        (found,) = self.service.for_activity_ids([session])

        self.assertEqual(found["notes"], "newer")

    def test_conflicting_originals_stay_stored_and_are_named(self) -> None:
        with self.manager.unit_of_work() as db:
            for key, session, notes, updated in (
                (INTERVALS_ID, self.sessions["intervals"], "older", "2026-09-19"),
                (GARMIN_ID, self.sessions["garmin"], "newer", "2026-09-20"),
            ):
                db.execute(
                    "INSERT INTO activity_feedback(activity_id, notes, created_at, "
                    "updated_at, session_id) VALUES (?, ?, ?, ?, ?)",
                    (key, notes, updated, updated, session),
                )
        (effective,) = self.service.list()
        self.assertEqual(effective["notes"], "newer")
        self.assertEqual(
            effective["conflicting_feedback"],
            [{"activity_id": INTERVALS_ID, "updated_at": "2026-09-19"}],
        )
        self.assertEqual(len(stored_rows(self)), 2)

        self.service.save(INTERVALS_ID, {"notes": ""})
        self.assertEqual((self.service.list(), stored_rows(self)), ([], []))


    def test_local_feedback_never_takes_the_provider_rpe(self) -> None:
        self.service.save(INTERVALS_ID, {"notes": "No RPE given"})
        (effective,) = self.service.list()
        self.assertIsNone(effective["session_rpe"])

    def test_a_deleted_provider_copy_keeps_its_feedback(self) -> None:
        self.service.save(GARMIN_ID, {"notes": "Saved on the Garmin copy"})
        with self.manager.unit_of_work() as db:
            self.assertTrue(
                canonical_store.mark_activity_deleted(
                    db,
                    "garmin",
                    record_kind="activity",
                    provider_activity_id=GARMIN_ID,
                    now=SYNCED,
                )
            )
        (row,) = stored_rows(self)
        self.assertEqual(row["notes"], "Saved on the Garmin copy")
        (shown,) = self.service.for_activity_ids([INTERVALS_ID])
        self.assertEqual(shown["notes"], "Saved on the Garmin copy")

    def test_an_ambiguous_id_stands_alone(self) -> None:
        with self.manager.unit_of_work() as db:
            intervals_fixture.ingest_intervals_partial_snapshot(
                db,
                {
                    "synced_at": SYNCED,
                    "raw_provider_data": {
                        "activities": [
                            intervals_row(INTERVALS_ID, icu_rpe=7),
                            intervals_row(
                                GARMIN_ID, start_date_local="2026-09-12T07:00:00"
                            ),
                        ]
                    },
                },
                zone=ZONE,
            )
        self.service.save(GARMIN_ID, {"notes": "Which one?"})
        self.service.save(INTERVALS_ID, {"notes": "The Intervals ride"})

        self.assertEqual(
            sorted(item["notes"] for item in self.service.list()),
            ["The Intervals ride", "Which one?"],
        )
        (ambiguous,) = [
            row for row in stored_rows(self) if row["activity_id"] == GARMIN_ID
        ]
        self.assertIsNone(ambiguous["session_id"])


class ReportFeedbackTests(FeedbackSessionFixture):
    """Block review and training report read feedback through the session lookup."""

    def report_service(self, session: str) -> TrainingReportReadService:
        summary = _summary(
            session,
            "2026-09-10T07:00:00",
            sport="ride",
            moving_duration_s=3600,
            record_ids={"intervals": INTERVALS_ID},
        )
        return TrainingReportReadService(
            read_synced_at=lambda _db: None,
            read_plan=lambda: None,
            read_checkins=list,
            read_feedback=self.service.for_activity_ids,
            today=lambda: date(2026, 10, 2),
            load_scenarios=load_scenarios,
            season_source=_empty_season_source(),
            canonical=CanonicalPerformanceSource(
                database_manager=_FakeDatabaseManager,
                observation_reader=_EmptyReader,
                activity_summaries=lambda: _Rows([summary]),
            ),
            curve_records=list,
            training_model=lambda: "pyramidal",
            block_review=BlockReviewSource(
                review=block_review, last_test=last_completed_test
            ),
        )

    def notes(self, session: str) -> tuple[list[str], list[str]]:
        service = self.report_service(session)
        review = service.block_review({}, "UTC")
        report = service.read({"start": "2026-09-07", "days": 7}, "UTC")
        return (
            [item["notes"] for item in review["subjective"]["feedback_notes"]],
            [item["notes"] for item in report["activity_feedback"]],
        )

    def test_legacy_feedback_is_found_for_the_session(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(
            INTERVALS_ID, "legacy note", "2026-09-19", session=None, rpe=4
        )

        self.assertEqual(self.notes(session), (["legacy note"], ["legacy note"]))

    def test_feedback_under_the_session_id_wins_over_a_legacy_row(self) -> None:
        session = merged_session_id(self)
        self.store_legacy(INTERVALS_ID, "legacy note", "2026-09-21", session=None)
        self.store_legacy(session, "new note", "2026-09-19", session=session)

        self.assertEqual(self.notes(session), (["new note"], ["new note"]))

    def test_feedback_saved_through_a_local_id_is_found(self) -> None:
        session = merged_session_id(self)
        self.service.save(session, {"notes": "saved now"})

        self.assertEqual(self.notes(session), (["saved now"], ["saved now"]))


if __name__ == "__main__":
    unittest.main()
