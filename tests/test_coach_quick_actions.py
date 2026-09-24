import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.coach.context import CoachQuickActionsService, coach_quick_actions_state
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository


class CoachQuickActionsProjectionTests(unittest.TestCase):
    TODAY = date(2026, 9, 20)
    LABEL = "Geplantes Training"

    def project(self, status=None, checkin_date=None, preview=None):
        return coach_quick_actions_state(
            self.TODAY,
            status,
            checkin_date,
            preview,
            planned_workout_label=self.LABEL,
        )

    def test_ready_checkin_is_done_only_for_today(self):
        self.assertFalse(self.project("ready", "2026-09-20")["morning_checkin"])
        self.assertTrue(self.project("ready", "2026-09-19")["morning_checkin"])

    def test_missing_or_invalid_checkin_status_remains_actionable(self):
        self.assertTrue(self.project()["morning_checkin"])
        self.assertTrue(self.project("", "2026-09-20")["morning_checkin"])
        self.assertTrue(self.project("error", "2026-09-20")["morning_checkin"])

    def test_blockers_include_today_through_two_days_but_not_day_three(self):
        result = self.project(preview={
            "status": "preview",
            "changes": [
                {"date": "2026-09-22", "blocking_triggers": ["illness"]},
                {"date": "2026-09-23", "blocking_triggers": ["calendar"]},
            ],
        })

        self.assertEqual(result["plan_blockers"], [{
            "date": "2026-09-22",
            "name": self.LABEL,
            "triggers": ["illness"],
        }])
        self.assertTrue(result["adjust_plan"])

    def test_empty_preview_has_no_blockers_and_exact_public_shape(self):
        result = self.project(preview={"status": "preview", "changes": []})

        self.assertEqual(set(result), {
            "morning_checkin",
            "analyze_latest_activity",
            "adjust_plan",
            "plan_blockers",
            "horizon_days",
        })
        self.assertEqual(result, {
            "morning_checkin": True,
            "analyze_latest_activity": True,
            "adjust_plan": False,
            "plan_blockers": [],
            "horizon_days": 3,
        })


class FakeAdaptivePreviewService:
    def __init__(self, preview):
        self.preview = preview

    def latest_preview(self):
        return self.preview


class CoachQuickActionsServiceTests(unittest.TestCase):
    TODAY = date(2026, 9, 20)
    LABEL = "Geplantes Training"

    def project(self, status, checkin_date, preview):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "coach.sqlite"
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
            connection.executemany(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                [
                    ("morning_checkin_status", status, "2026-09-20T08:00:00"),
                    ("morning_checkin_date", checkin_date, "2026-09-20T08:00:00"),
                ],
            )
            connection.commit()
            connection.close()

            manager = DatabaseManager(
                database_path, sqlite3, row_factory=sqlite3.Row
            )
            service = CoachQuickActionsService(
                manager,
                KeyValueRepository(lambda: "2026-09-20T08:00:00"),
                FakeAdaptivePreviewService(preview),
                lambda: self.TODAY,
                self.LABEL,
            )
            try:
                return service.state()
            finally:
                manager.close()

    def test_state_reads_ready_today_but_not_yesterday(self):
        today = self.project("ready", "2026-09-20", None)
        yesterday = self.project("ready", "2026-09-19", None)

        self.assertFalse(today["morning_checkin"])
        self.assertTrue(yesterday["morning_checkin"])

    def test_state_projects_preview_blockers_without_provider_status(self):
        result = self.project("pending", "2026-09-19", {
            "status": "preview",
            "provider_status": {"garmin": "connected", "intervals": "ready"},
            "changes": [{
                "date": "2026-09-22",
                "blocking_triggers": ["calendar"],
            }],
        })

        self.assertEqual(result["plan_blockers"], [{
            "date": "2026-09-22",
            "name": self.LABEL,
            "triggers": ["calendar"],
        }])
        self.assertTrue(result["adjust_plan"])
        self.assertNotIn("provider_status", result)
        self.assertEqual(set(result), {
            "morning_checkin",
            "analyze_latest_activity",
            "adjust_plan",
            "plan_blockers",
            "horizon_days",
        })


if __name__ == "__main__":
    unittest.main()
