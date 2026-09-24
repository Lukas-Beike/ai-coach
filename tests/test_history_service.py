"""Focused tests for the local change-history read service."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import change_history
from backend.athlete.profile import DEFAULT_PROFILE
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService


class _FailHistoryRead:
    def __init__(self, db):
        self._db = db

    def execute(self, query, parameters=()):
        if query.startswith("SELECT id, entity_type, entity_id, action, source"):
            raise sqlite3.OperationalError("history read failed")
        return self._db.execute(query, parameters)


class _FailingReadManager:
    def __init__(self, manager):
        self._manager = manager

    @contextmanager
    def unit_of_work(self):
        with self._manager.unit_of_work() as db:
            yield _FailHistoryRead(db)


class ChangeHistoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "history.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: "2026-09-20T00:00:00+00:00")
        self.profile_repository = ProfileRepository(self.key_values)
        self.service = ChangeHistoryService(
            self.database_manager, self.profile_repository
        )

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _insert_history(self, history_id, created_at, diff=None):
        diff = diff or {"fields": {}, "before_present": False, "after_present": True}
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO change_history "
                "(id, entity_type, entity_id, action, source, created_at, "
                "before_hash, after_hash, diff) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    history_id,
                    "profile",
                    "profile",
                    "update",
                    "local",
                    created_at,
                    "before",
                    "after",
                    json.dumps(diff),
                ),
            )

    def test_list_clamps_limits_orders_rows_and_returns_private_projection(self):
        self._insert_history(
            "oldest",
            "2026-09-18T00:00:00+00:00",
            {
                "fields": {"name": {"before": "Ada Private", "after": "Grace Private"}},
                "before_present": True,
                "after_present": True,
            },
        )
        self._insert_history("newest", "2026-09-20T00:00:00+00:00")

        limited = self.service.list(limit=0)
        self.assertEqual([row["id"] for row in limited], ["newest"])
        full = self.service.list(limit=change_history.MAX_ROWS + 10)
        self.assertEqual([row["id"] for row in full], ["newest", "oldest"])
        self.assertNotIn("Ada Private", json.dumps(full))
        self.assertNotIn("Grace Private", json.dumps(full))
        self.assertEqual(full[1]["diff"]["fields"], {"name": {"changed": True}})
        self.assertEqual(full[1]["remote_sync"], "local_only")

    def test_list_cleanup_removes_expired_and_caps_retained_rows(self):
        base = datetime(2026, 9, 20, tzinfo=timezone.utc)
        with self.database_manager.unit_of_work() as db:
            rows = [
                (
                    f"row-{index:04d}",
                    "profile",
                    "profile",
                    "update",
                    "local",
                    (base + timedelta(seconds=index)).isoformat(),
                    "before",
                    "after",
                    "{}",
                )
                for index in range(change_history.MAX_ROWS + 1)
            ]
            expired = (
                "expired",
                "profile",
                "profile",
                "update",
                "local",
                (base - timedelta(days=181)).isoformat(),
                "before",
                "after",
                "{}",
            )
            db.executemany(
                "INSERT INTO change_history "
                "(id, entity_type, entity_id, action, source, created_at, "
                "before_hash, after_hash, diff) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [*rows, expired],
            )

        listed = self.service.list(limit=change_history.MAX_ROWS + 50)

        self.assertEqual(len(listed), change_history.MAX_ROWS)
        self.assertEqual(listed[0]["id"], f"row-{change_history.MAX_ROWS:04d}")
        self.assertNotIn("row-0000", {row["id"] for row in listed})
        with self.database_manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM change_history").fetchone()[
                    "count"
                ],
                change_history.MAX_ROWS,
            )
            self.assertIsNone(
                db.execute(
                    "SELECT id FROM change_history WHERE id='expired'"
                ).fetchone()
            )

    def test_list_clamps_large_requested_limit_to_max_rows(self):
        base = datetime(2026, 9, 20, tzinfo=timezone.utc)
        with self.database_manager.unit_of_work() as db:
            db.executemany(
                "INSERT INTO change_history "
                "(id, entity_type, entity_id, action, source, created_at, "
                "before_hash, after_hash, diff) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"row-{index:04d}",
                        "profile",
                        "profile",
                        "update",
                        "local",
                        (base + timedelta(seconds=index)).isoformat(),
                        "before",
                        "after",
                        "{}",
                    )
                    for index in range(change_history.MAX_ROWS + 1)
                ],
            )

        with patch("backend.history.service.change_history.cleanup"):
            listed = self.service.list(limit=change_history.MAX_ROWS + 50)

        self.assertEqual(len(listed), change_history.MAX_ROWS)
        self.assertEqual(listed[0]["id"], f"row-{change_history.MAX_ROWS:04d}")
        self.assertNotIn("row-0000", {row["id"] for row in listed})

    def test_list_rolls_back_cleanup_if_read_fails(self):
        expired_at = (datetime.now(timezone.utc) - timedelta(days=181)).isoformat()
        self._insert_history("expired", expired_at)
        service = ChangeHistoryService(
            _FailingReadManager(self.database_manager), self.profile_repository
        )

        with self.assertRaisesRegex(sqlite3.OperationalError, "history read failed"):
            service.list()

        with self.database_manager.reader() as db:
            self.assertIsNotNone(
                db.execute(
                    "SELECT id FROM change_history WHERE id='expired'"
                ).fetchone()
            )

    def test_current_profile_normalizes_and_falls_back_for_corrupt_payload(self):
        with self.database_manager.unit_of_work() as db:
            self.profile_repository.set(
                db, json.dumps({"name": "  Ada  ", "timezone": "UTC"})
            )
            value, projection = self.service.current(db, "profile", "profile")
            self.assertEqual(value["name"], "Ada")
            self.assertEqual(value["timezone"], "UTC")
            self.assertEqual(
                projection, change_history.audit_projection("profile", value)
            )
            self.profile_repository.set(db, "not-json")
            fallback, fallback_projection = self.service.current(
                db, "profile", "profile"
            )
            self.profile_repository.set(db, "null")
            non_object_fallback, _ = self.service.current(db, "profile", "profile")

        self.assertEqual(fallback, DEFAULT_PROFILE)
        self.assertEqual(non_object_fallback, DEFAULT_PROFILE)
        self.assertEqual(
            fallback_projection,
            change_history.audit_projection("profile", DEFAULT_PROFILE),
        )

    def test_current_reads_all_local_record_types_and_missing_rows(self):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES ('w1', 'w1', ?, 'now')",
                (json.dumps({"id": "w1", "name": "Local workout"}),),
            )
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
                "VALUES ('p1', 'p1', ?, 'now', 'now')",
                (json.dumps({"id": "p1", "name": "Local plan"}),),
            )
            db.execute(
                "INSERT INTO competitions "
                "(id, name, event_date, sport, priority, distance, target, course_profile, notes, created_at, updated_at) "
                "VALUES ('c1', 'Local race', '2026-10-01', 'Run', 'A', '', '', '', '', 'now', 'now')"
            )
            db.execute(
                "INSERT INTO training_plans "
                "(id, name, goal, start_date, end_date, status, created_at, updated_at) "
                "VALUES ('t1', 'Local plan', '', '2026-09-01', '2026-10-01', 'active', 'now', 'now')"
            )
            cases = (
                ("workout_library", "w1", "Local workout"),
                ("planned_unit", "p1", "Local plan"),
                ("competition", "c1", "Local race"),
                ("training_plan", "t1", "Local plan"),
            )
            for entity_type, entity_id, expected_name in cases:
                value, projection = self.service.current(db, entity_type, entity_id)
                current_name = (
                    json.loads(value["payload"])["name"]
                    if entity_type in {"workout_library", "planned_unit"}
                    else value["name"]
                )
                self.assertEqual(current_name, expected_name)
                self.assertEqual(
                    projection, change_history.audit_projection(entity_type, value)
                )
                self.assertEqual(
                    self.service.current(db, entity_type, "missing"), (None, None)
                )

            with self.assertRaises(AppError) as raised:
                self.service.current(db, "unknown", "id")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, "Unbekannte lokale Änderung.")

    def test_target_preserves_action_diff_and_error_semantics(self):
        create = {"action": "create", "diff": json.dumps({"fields": {}})}
        self.assertEqual(self.service.target(create), (None, None))

        diff = json.dumps(
            {
                "fields": {
                    "name": {"before": "Before", "after": "After"},
                    "new_field": {"after": "new"},
                    "ignored": "invalid field record",
                }
            }
        )
        for action in ("update", "delete"):
            target, duplicate = self.service.target({"action": action, "diff": diff})
            self.assertEqual(target, {"name": "Before"})
            self.assertIs(target, duplicate)

        cases = (
            (
                {"action": "update", "diff": "["},
                409,
                "Die Änderungshistorie ist beschädigt.",
            ),
            (
                {"action": "update", "diff": json.dumps({})},
                409,
                "Die Änderungshistorie enthält keinen wiederherstellbaren Diff.",
            ),
            (
                {"action": "undo", "diff": json.dumps({"fields": {}})},
                409,
                "Diese Änderung kann nicht erneut zurückgenommen werden.",
            ),
        )
        for row, status, message in cases:
            with self.subTest(action=row["action"]):
                with self.assertRaises(AppError) as raised:
                    self.service.target(row)
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(raised.exception.message, message)


if __name__ == "__main__":
    unittest.main()
