"""Direct regression coverage for morning Coach job completion persistence."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.coach.morning_completion import MorningCoachJobCompletionService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository


class CountingDatabaseManager(DatabaseManager):
    def __init__(self, path: Path) -> None:
        super().__init__(
            path,
            sqlite3,
            row_factory=lambda cursor, row: dict(
                zip((column[0] for column in cursor.description), row)
            ),
        )
        self.uow_count = 0

    @contextmanager
    def unit_of_work(self):
        self.uow_count += 1
        with super().unit_of_work() as db:
            yield db


class MorningCoachJobCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="morning-completion-")
        self.manager = CountingDatabaseManager(Path(self.temp_dir.name) / "test.db")
        self.lock = threading.RLock()
        self.key_values = KeyValueRepository(lambda: "kv-updated")
        with self.manager.unit_of_work() as db:
            db.execute("CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
            db.execute(
                "CREATE TABLE coach_commands(client_turn_id TEXT PRIMARY KEY, status TEXT, "
                "receipt TEXT, updated_at TEXT)"
            )
        self.manager.uow_count = 0

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def service(self, quick_actions: dict[str, Any]) -> MorningCoachJobCompletionService:
        return MorningCoachJobCompletionService(
            self.manager,
            self.lock,
            self.key_values,
            lambda: SimpleNamespace(state=lambda: quick_actions),
            lambda: datetime(2026, 9, 24, 7, 30, tzinfo=timezone.utc),
            lambda: "utc-updated",
        )

    def test_completed_command_gets_compact_unicode_receipt_in_two_transactions(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands(client_turn_id, status, receipt, updated_at) "
                "VALUES (?, 'completed', ?, 'old')",
                ("turn-1", '{"message":"Fertig ✓"}'),
            )
        self.manager.uow_count = 0
        quick_actions = {"morning_checkin": False, "label": "Morgen ✓"}
        states_seen: list[tuple[str | None, str | None]] = []

        def quick_actions_factory() -> Any:
            with self.manager.reader() as db:
                states_seen.append(
                    (
                        self.key_values.get(db, "morning_checkin_date"),
                        self.key_values.get(db, "morning_checkin_status"),
                    )
                )
            return SimpleNamespace(state=lambda: quick_actions)

        service = MorningCoachJobCompletionService(
            self.manager,
            self.lock,
            self.key_values,
            quick_actions_factory,
            lambda: datetime(2026, 9, 24, 7, 30, tzinfo=timezone.utc),
            lambda: "utc-updated",
        )

        result = service.complete("turn-1")

        self.assertEqual(self.manager.uow_count, 2)
        self.assertEqual(states_seen, [("2026-09-24", "ready")])
        self.assertEqual(
            result, {"message": "Fertig ✓", "coach_quick_actions": quick_actions}
        )
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT receipt, updated_at FROM coach_commands WHERE client_turn_id=?",
                ("turn-1",),
            ).fetchone()
        self.assertEqual(
            row["receipt"],
            '{"message":"Fertig ✓","coach_quick_actions":{"morning_checkin":false,"label":"Morgen ✓"}}',
        )
        self.assertEqual(row["updated_at"], "utc-updated")

    def test_non_completed_command_returns_receipt_but_does_not_update_it(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands(client_turn_id, status, receipt, updated_at) "
                "VALUES (?, 'running', ?, 'old')",
                ("turn-2", '{"status":"running"}'),
            )
        self.manager.uow_count = 0

        result = self.service({"morning_checkin": False}).complete("turn-2")

        self.assertEqual(
            result,
            {"status": "running", "coach_quick_actions": {"morning_checkin": False}},
        )
        self.assertEqual(self.manager.uow_count, 2)
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT receipt, updated_at FROM coach_commands WHERE client_turn_id=?",
                ("turn-2",),
            ).fetchone()
        self.assertEqual(row, {"receipt": '{"status":"running"}', "updated_at": "old"})

    def test_missing_command_keeps_existing_empty_receipt_return_semantics(self) -> None:
        self.manager.uow_count = 0

        result = self.service({"morning_checkin": False}).complete("missing")

        self.assertEqual(result, {"coach_quick_actions": {"morning_checkin": False}})
        self.assertEqual(self.manager.uow_count, 2)
        with self.manager.reader() as db:
            self.assertEqual(
                self.key_values.get(db, "morning_checkin_date"), "2026-09-24"
            )
            self.assertEqual(
                self.key_values.get(db, "morning_checkin_status"), "ready"
            )

    def test_quick_actions_failure_keeps_first_commit_and_does_not_touch_receipt(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands(client_turn_id, status, receipt, updated_at) "
                "VALUES (?, 'completed', ?, 'old')",
                ("turn-quick-actions-error", '{"status":"completed"}'),
            )
        self.manager.uow_count = 0

        def failed_quick_actions() -> Any:
            raise RuntimeError("synthetic quick-actions failure")

        service = MorningCoachJobCompletionService(
            self.manager,
            self.lock,
            self.key_values,
            failed_quick_actions,
            lambda: datetime(2026, 9, 24, 7, 30, tzinfo=timezone.utc),
            lambda: "utc-updated",
        )
        with self.assertRaisesRegex(RuntimeError, "synthetic quick-actions failure"):
            service.complete("turn-quick-actions-error")

        self.assertEqual(self.manager.uow_count, 1)
        with self.manager.reader() as db:
            self.assertEqual(
                self.key_values.get(db, "morning_checkin_date"), "2026-09-24"
            )
            self.assertEqual(
                self.key_values.get(db, "morning_checkin_status"), "ready"
            )
            row = db.execute(
                "SELECT receipt, updated_at FROM coach_commands WHERE client_turn_id=?",
                ("turn-quick-actions-error",),
            ).fetchone()
        self.assertEqual(
            row,
            {"receipt": '{"status":"completed"}', "updated_at": "old"},
        )


if __name__ == "__main__":
    unittest.main()
