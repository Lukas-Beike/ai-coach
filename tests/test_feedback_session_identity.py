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
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_reference import ActivityReferences
from backend.activities.feedback import ActivityFeedbackService
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import ActivityFeedbackRepository, KeyValueRepository
from backend.db.schema import initialize_schema
from backend.sync import canonical_ingest
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

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
            canonical_ingest.ingest_intervals_partial_snapshot(
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
            CanonicalTableReader(),
            references=ActivityReferences(self.manager),
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

        self.assertEqual(
            (saved["activity_id"], saved["notes"], saved["session_rpe"]),
            (INTERVALS_ID, "Heavy legs", 5),
        )
        self.assertEqual(
            [row["activity_id"] for row in stored_rows(self)], [INTERVALS_ID]
        )
        (effective,) = self.service.list()
        self.assertEqual(effective["session_rpe"], 5)
        by_id = {
            item["activity_id"]: item
            for item in self.service.for_activity_ids([INTERVALS_ID, GARMIN_ID])
        }
        self.assertEqual(by_id[GARMIN_ID]["notes"], by_id[INTERVALS_ID]["notes"])

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

    def test_an_ambiguous_id_stands_alone(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_ingest.ingest_intervals_partial_snapshot(
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


if __name__ == "__main__":
    unittest.main()
