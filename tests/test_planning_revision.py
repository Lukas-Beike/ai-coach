"""Regression tests for the planning revision state owner."""

from __future__ import annotations

import sqlite3
import unittest

from backend.db import row_factory
from backend.db.repositories import PlanningStateRepository
from backend.errors import AppError
from backend.planning.revision import PlanningRevisionService


class PlanningRevisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.db.execute(
            "CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 3, 'old')"
        )
        self.now = "2026-09-20T09:00:00+00:00"
        self.service = PlanningRevisionService(
            PlanningStateRepository(), lambda: self.now
        )

    def tearDown(self):
        self.db.close()

    def state(self):
        return self.db.execute(
            "SELECT revision, updated_at FROM planning_state WHERE id=1"
        ).fetchone()

    def test_bump_updates_revision_and_timestamp(self):
        self.service.bump(self.db, 2)

        self.assertEqual(dict(self.state()), {"revision": 5, "updated_at": self.now})
        self.assertEqual(self.service.read(self.db), 5)

    def test_non_positive_bump_is_a_noop(self):
        self.service.bump(self.db, 0)
        self.service.bump(self.db, -1)

        self.assertEqual(dict(self.state()), {"revision": 3, "updated_at": "old"})

    def test_missing_revision_is_corruption_without_explicit_reset(self):
        self.db.execute("DELETE FROM planning_state")

        with self.assertRaises(AppError) as error:
            self.service.bump(self.db)

        self.assertEqual(error.exception.status, 500)
        self.assertEqual(error.exception.reason, "database_corrupt")
        self.assertIsNone(self.state())

    def test_explicit_privacy_reset_recreates_singleton_once(self):
        self.db.execute("DELETE FROM planning_state")
        self.service.mark_reset_pending()

        self.service.bump(self.db, 2)

        self.assertEqual(dict(self.state()), {"revision": 2, "updated_at": self.now})
        self.db.execute("DELETE FROM planning_state")
        with self.assertRaises(AppError):
            self.service.bump(self.db)


if __name__ == "__main__":
    unittest.main()
