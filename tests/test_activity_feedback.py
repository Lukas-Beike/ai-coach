from __future__ import annotations

import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from activity_row_support import SnapshotActivityRows

from backend.activities.feedback import (
    ACTIVITY_FEEDBACK_TEXT_LIMITS,
    ActivityFeedbackService,
    normalize_activity_feedback,
)
from backend.db.manager import DatabaseManager
from backend.db.repositories import ActivityFeedbackRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.sync.snapshot_reader import SnapshotRepositoryReader


class ActivityFeedbackNormalizationTests(unittest.TestCase):
    def test_rpe_zero_and_bounds(self):
        self.assertEqual(
            0, normalize_activity_feedback("one", {"session_rpe": 0})["session_rpe"]
        )
        for value in (
            -1,
            11,
            float("nan"),
            float("inf"),
            10**400,
            -(10**400),
            True,
            "5",
        ):
            with self.subTest(value=value), self.assertRaises(AppError):
                normalize_activity_feedback("one", {"session_rpe": value})

    def test_normalizes_id_and_known_text_fields(self) -> None:
        result = normalize_activity_feedback(
            "  activity-1  ",
            {
                "activity_name": "  Morning ride  ",
                "activity_date": "  2026-09-20  ",
                "notes": "  Felt good  ",
            },
        )
        self.assertEqual(
            result,
            {
                "activity_id": "activity-1",
                "activity_name": "Morning ride",
                "activity_date": "2026-09-20",
                "notes": "Felt good",
            },
        )

    def test_id_and_value_errors_keep_existing_app_errors(self) -> None:
        with self.assertRaises(AppError) as empty_id:
            normalize_activity_feedback("  ", {})
        self.assertEqual(empty_id.exception.status, 400)
        self.assertEqual(
            empty_id.exception.message,
            "Die Aktivität konnte nicht eindeutig zugeordnet werden.",
        )

        with self.assertRaises(AppError) as long_id:
            normalize_activity_feedback("x" * 201, {})
        self.assertEqual(long_id.exception.status, 400)

        with self.assertRaises(AppError) as wrong_value:
            normalize_activity_feedback("activity-1", [])
        self.assertEqual(wrong_value.exception.status, 400)
        self.assertEqual(
            wrong_value.exception.message,
            "Die Aktivitätsrückmeldung muss ein Objekt sein.",
        )

    def test_values_are_stringified_trimmed_and_bounded(self) -> None:
        result = normalize_activity_feedback(
            42,
            {
                "activity_name": " n " * 150,
                "activity_date": 20260920,
                "notes": " note " * 1000,
            },
        )
        self.assertEqual(result["activity_id"], "42")
        self.assertEqual(
            len(result["activity_name"]), ACTIVITY_FEEDBACK_TEXT_LIMITS["activity_name"]
        )
        self.assertEqual(result["activity_date"], "20260920")
        self.assertEqual(len(result["notes"]), ACTIVITY_FEEDBACK_TEXT_LIMITS["notes"])

    def test_unknown_fields_are_ignored(self) -> None:
        result = normalize_activity_feedback(
            "activity-1",
            {"notes": "kept", "unknown": "ignored", "activity_id": "spoofed"},
        )
        self.assertEqual(
            result,
            {
                "activity_id": "activity-1",
                "activity_name": "",
                "activity_date": "",
                "notes": "kept",
            },
        )

    def test_input_is_not_mutated(self) -> None:
        value = {
            "activity_name": "  Ride  ",
            "activity_date": " 2026-09-20 ",
            "notes": "  Good  ",
            "unknown": {"keep": True},
        }
        original = deepcopy(value)
        normalize_activity_feedback(" activity-1 ", value)
        self.assertEqual(value, original)


class ParameterRecordingConnection:
    """Delegate to a connection while recording each statement's parameter count."""

    def __init__(self, db):
        self._db = db
        self.parameter_counts: list[int] = []

    def execute(self, sql, parameters=()):
        self.parameter_counts.append(len(parameters))
        return self._db.execute(sql, parameters)


class ActivityFeedbackServiceTests(unittest.TestCase):
    def test_rpe_only_preserves_notes_and_explicit_clear_deletes(self):
        self.service.save(
            "one", {"notes": "kept", "session_rpe": 4, "deviation_reason": "heat"}
        )
        result = self.service.save("one", {"session_rpe": 0})["activity_feedback"]
        self.assertEqual(
            ("kept", 0, "heat"),
            (result["notes"], result["session_rpe"], result["deviation_reason"]),
        )
        self.service.save("one", {"notes": ""})
        self.assertEqual(0, self.service.list()[0]["session_rpe"])
        self.assertIsNone(
            self.service.save("one", {"session_rpe": None, "deviation_reason": ""})[
                "activity_feedback"
            ]
        )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temp_dir.name) / "feedback.db",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.feedback_repository = ActivityFeedbackRepository(
            lambda: "2026-09-20T12:00:00+00:00"
        )
        self.snapshot_repository = SnapshotRepository()
        self.rows = SnapshotActivityRows(
            SnapshotRepositoryReader(self.snapshot_repository)
        )
        self.service = ActivityFeedbackService(
            self.manager,
            self.feedback_repository,
            self.rows,
        )

    def save_snapshot(self, payload: dict) -> None:
        with self.manager.unit_of_work() as db:
            self.snapshot_repository.save(db, payload, "2026-09-20T12:00:00+00:00")

    def insert_feedback_rows(self, rows: list[tuple[str, str]]) -> None:
        with self.manager.unit_of_work() as db:
            for activity_id, updated_at in rows:
                db.execute(
                    "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, notes, session_rpe, deviation_reason, created_at, updated_at, provider) "
                    "VALUES (?, '', '2026-09-20', 'note', NULL, '', ?, ?, NULL)",
                    (activity_id, updated_at, updated_at),
                )

    def test_list_limit_is_clamped(self) -> None:
        for activity_id in ("one", "two", "three"):
            self.service.save(activity_id, {"notes": activity_id})

        self.assertEqual(len(self.service.list(-10)), 1)
        self.assertEqual(len(self.service.list(999)), 3)

    def test_save_upserts_and_returns_stored_row(self) -> None:
        first = self.service.save(
            "activity-1",
            {"activity_name": "Ride", "activity_date": "2026-09-20", "notes": "Good"},
        )
        updated = self.service.save("activity-1", {"notes": "Better"})

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["activity_feedback"]["notes"], "Good")
        self.assertEqual(updated["activity_feedback"]["activity_id"], "activity-1")
        self.assertEqual(updated["activity_feedback"]["notes"], "Better")
        self.assertEqual(self.service.list(), [updated["activity_feedback"]])

    def test_empty_notes_delete_and_exact_response(self) -> None:
        self.service.save("activity-1", {"notes": "remove me"})

        result = self.service.save("activity-1", {"notes": "   "})
        self.assertEqual(
            {key: value for key, value in result.items() if key != "change"},
            {"status": "ok", "activity_feedback": None},
        )
        self.assertEqual(result["change"]["action"], "delete")
        self.assertEqual(self.service.list(), [])

    def test_coach_save_requires_known_snapshot_activity_and_accepts_aliases(
        self,
    ) -> None:
        self.save_snapshot(
            {
                "recent_activities": [
                    {"activityId": "activity-alias"},
                    {"external_id": "activity-external"},
                    {"id": "activity-id"},
                ]
            }
        )

        for activity_id in ("activity-alias", "activity-external", "activity-id"):
            self.assertEqual(
                self.service.save_coach(activity_id, {"notes": "athlete note"})[
                    "activity_feedback"
                ]["activity_id"],
                activity_id,
            )
        with self.assertRaises(AppError) as empty:
            self.service.save_coach("activity-id", {"notes": "  "})
        self.assertEqual(
            (empty.exception.status, empty.exception.message),
            (400, "Die Rückmeldung darf nicht leer sein."),
        )
        with self.assertRaises(AppError) as unknown:
            self.service.save_coach("unknown", {"notes": "not allowed"})
        self.assertEqual(
            (unknown.exception.status, unknown.exception.message),
            (
                404,
                "Die Aktivität ist im aktuellen lokalen Trainingssnapshot nicht vorhanden.",
            ),
        )

    def test_context_keeps_recent_and_scope(self) -> None:
        self.service.save("activity-1", {"notes": "note"})

        self.assertEqual(self.service.context()["recent"], self.service.list())
        self.assertEqual(
            self.service.context()["scope"],
            "Only athlete-entered notes, session RPE and deviation reasons about completed activities; this feedback is separate from daily check-ins and provider values.",
        )

    def test_attach_projects_only_dict_activities_without_mutating_input(self) -> None:
        self.service.save("activity-1", {"notes": "note"})
        activities = [{"id": "activity-1", "nested": {"keep": True}}, "skip", None]
        original = deepcopy(activities)

        result = self.service.attach_to_activities(activities)

        self.assertEqual(activities, original)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["activity_feedback"]["notes"], "note")
        self.assertEqual(self.service.attach_to_activities("not a list"), [])

    def test_attach_finds_feedback_older_than_the_newest_500_rows(self) -> None:
        rows = [("oldest", "2026-09-20T00:00:00+00:00")] + [
            (
                f"newer-{index}",
                f"2026-09-21T00:{index // 60:02d}:{index % 60:02d}+00:00",
            )
            for index in range(600)
        ]
        self.insert_feedback_rows(rows)
        self.assertNotIn(
            "oldest", [item["activity_id"] for item in self.service.list(500)]
        )

        result = self.service.attach_to_activities(
            [{"id": "oldest"}, {"id": "newer-0"}, {"id": "missing"}, {"id": ""}]
        )

        self.assertEqual(result[0]["activity_feedback"]["activity_id"], "oldest")
        self.assertEqual(result[1]["activity_feedback"]["activity_id"], "newer-0")
        self.assertNotIn("activity_feedback", result[2])
        self.assertNotIn("activity_feedback", result[3])

    def test_for_activity_ids_queries_in_bounded_chunks(self) -> None:
        self.insert_feedback_rows(
            [
                (f"activity-{index}", "2026-09-20T00:00:00+00:00")
                for index in range(1200)
            ]
        )
        requested = [f"activity-{index}" for index in range(1200)] + [
            "missing",
            "activity-0",
            "",
        ]

        with self.manager.unit_of_work() as db:
            recorder = ParameterRecordingConnection(db)
            rows = self.feedback_repository.for_activity_ids(recorder, requested)
            empty = self.feedback_repository.for_activity_ids(recorder, [""])
            no_ids = self.feedback_repository.for_activity_ids(recorder, [])

        self.assertEqual(len(rows), 1200)
        self.assertEqual(
            {row["activity_id"] for row in rows}, set(requested) - {"", "missing"}
        )
        self.assertEqual(recorder.parameter_counts, [500, 500, 201])
        self.assertEqual((empty, no_ids), ([], []))

    def test_failed_read_after_upsert_keeps_committed_row(self) -> None:
        class FailingListRepository(ActivityFeedbackRepository):
            def __init__(self) -> None:
                super().__init__(lambda: "2026-09-20T12:00:00+00:00")
                self.fail = True
                self.reads = 0

            def all(self, db):
                # Two reads prepare and record the save; the third follows its commit.
                self.reads += 1
                if self.fail and self.reads > 2:
                    raise RuntimeError("read failure")
                return super().all(db)

        repository = FailingListRepository()
        service = ActivityFeedbackService(self.manager, repository, self.rows)
        with self.assertRaisesRegex(RuntimeError, "read failure"):
            service.save("activity-1", {"notes": "must persist"})
        repository.fail = False
        self.assertEqual(service.list()[0]["notes"], "must persist")

    def test_write_failure_after_sql_rolls_back(self) -> None:
        class FailingUpsertRepository(ActivityFeedbackRepository):
            def upsert(self, db, feedback, **values):
                super().upsert(db, feedback, **values)
                raise RuntimeError("write failure")

        service = ActivityFeedbackService(
            self.manager,
            FailingUpsertRepository(lambda: "2026-09-20T12:00:00+00:00"),
            self.rows,
        )
        with self.assertRaisesRegex(RuntimeError, "write failure"):
            service.save("activity-1", {"notes": "must roll back"})
        self.assertEqual(service.list(), [])


if __name__ == "__main__":
    unittest.main()
