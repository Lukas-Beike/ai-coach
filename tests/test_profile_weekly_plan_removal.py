"""One-time removal of the retired weekly plan from the stored profile (#1850)."""

from __future__ import annotations

import json
import unittest

from support import temp_database

from backend.db import row_factory
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.sync.profile_weekly_plan_removal import (
    STATE_KEY,
    ProfileWeeklyPlanRemoval,
    summarize_profile_weekly_plan_removal,
)

NOW = "2026-11-09T08:00:00+00:00"
PLAN = json.dumps({"days": {"wed": {"rest_day": True}}})


class ProfileWeeklyPlanRemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "profile.db", row_factory=row_factory, schema=True
        )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.profile = ProfileRepository(self.key_values)
        self.stage = ProfileWeeklyPlanRemoval(
            key_values=self.key_values, clock=lambda: NOW
        )

    def store(self, payload: str) -> None:
        with self.manager.unit_of_work() as db:
            self.profile.set(db, payload)

    def stored(self) -> str | None:
        with self.manager.reader() as db:
            return self.profile.get(db)

    def run_stage(self):
        with self.manager.unit_of_work() as db:
            return self.stage.run_batch(db)

    def summary(self) -> dict:
        with self.manager.reader() as db:
            return summarize_profile_weekly_plan_removal(self.key_values, db)

    def test_only_the_weekly_plan_key_is_removed(self) -> None:
        self.store(json.dumps({"name": "Ada", "weekly_plan": PLAN, "goals": "Ziel"}))

        report = self.run_stage()

        self.assertEqual((1, True), (report.items, report.done))
        self.assertEqual(
            {"name": "Ada", "goals": "Ziel"}, json.loads(self.stored() or "")
        )
        self.assertEqual(
            {"status": "complete", "version": 1, "removed": True}, self.summary()
        )

    def test_a_second_run_changes_nothing_until_an_older_backup_returns(self) -> None:
        self.store(json.dumps({"name": "Ada", "weekly_plan": PLAN}))
        self.run_stage()
        self.store(json.dumps({"name": "Ada", "weekly_plan": PLAN}))

        self.assertEqual(0, self.run_stage().items)
        self.assertIn("weekly_plan", json.loads(self.stored() or ""))

        # A restored older database carries no state row: the stage runs again.
        with self.manager.unit_of_work() as db:
            self.key_values.delete(db, STATE_KEY)
        self.assertEqual(1, self.run_stage().items)
        self.assertNotIn("weekly_plan", json.loads(self.stored() or ""))

    def test_missing_malformed_or_clean_profiles_are_left_alone(self) -> None:
        for payload in ("not json", json.dumps(["list"]), json.dumps({"name": "Ada"})):
            with self.subTest(payload=payload):
                self.store(payload)
                with self.manager.unit_of_work() as db:
                    self.key_values.delete(db, STATE_KEY)
                self.assertEqual(0, self.run_stage().items)
                self.assertEqual(payload, self.stored())
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM kv WHERE key='profile'")
            self.key_values.delete(db, STATE_KEY)
        self.assertEqual(0, self.run_stage().items)
        self.assertIsNone(self.stored())

    def test_a_failed_run_is_marked_and_retried(self) -> None:
        self.store(json.dumps({"weekly_plan": PLAN}))
        with self.manager.unit_of_work() as db:
            self.stage.mark_failed(db)
        self.assertEqual("failed", self.summary()["status"])

        self.assertEqual(1, self.run_stage().items)
        self.assertEqual("complete", self.summary()["status"])


if __name__ == "__main__":
    unittest.main()
