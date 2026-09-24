"""Direct contracts for structured Coach receipt/effect replay lookup."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Self

from backend.coach.tool_replay import CoachStructuredToolReplayService
from backend.db.manager import DatabaseManager
from backend.errors import AppError


class TrackingLock:
    def __init__(self) -> None:
        self.held = False

    def __enter__(self) -> Self:
        self.held = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.held = False


class LockCheckingDatabaseManager(DatabaseManager):
    def __init__(self, path: Path, lock: TrackingLock) -> None:
        super().__init__(path, sqlite3, row_factory=sqlite3.Row, persist_connections=False)
        self._tracking_lock = lock

    @contextmanager
    def unit_of_work(self) -> Iterator[Any]:
        if not self._tracking_lock.held:
            raise AssertionError("database unit of work must run under the injected lock")
        with super().unit_of_work() as db:
            yield db


class StructuredToolReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="coach-tool-replay-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "replay.sqlite3"
        self.lock = TrackingLock()
        self.database_manager = LockCheckingDatabaseManager(self.path, self.lock)
        self.addCleanup(self.database_manager.close)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(
                "CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL);"
                "INSERT INTO planning_state(id, revision) VALUES (1, 3);"
                "CREATE TABLE coach_plan_artifacts ("
                "id TEXT PRIMARY KEY, status TEXT NOT NULL, base_revision INTEGER NOT NULL);"
            )
        self.service = CoachStructuredToolReplayService(
            self.database_manager, self.lock, frozenset({"get_profile"})
        )

    @staticmethod
    def metadata(*, call_id: str = "call-new", name: str = "update_training_plan", effect_key: str = "effect-1") -> dict[str, str]:
        return {"call_id": call_id, "name": name, "effect_key": effect_key}

    @staticmethod
    def receipt(
        *,
        call_id: str = "call-old",
        name: str = "update_training_plan",
        effect_key: str = "effect-1",
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"call_id": call_id, "tool": name, "effect_key": effect_key, "result": result or {"ok": True}}

    def seed_artifact(self, artifact_id: str, *, status: str = "draft", base_revision: int = 3) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO coach_plan_artifacts(id, status, base_revision) VALUES (?, ?, ?)",
                (artifact_id, status, base_revision),
            )

    def test_replays_matching_call_id_and_rejects_changed_effect(self) -> None:
        cached = self.receipt(call_id="call-1", effect_key="effect-1")
        receipts = [cached]
        result = self.service.lookup(self.metadata(call_id="call-1"), receipts)
        self.assertIs(result, cached)
        self.assert_app_error_for_changed_call_id_effect(receipts)
        self.assertEqual(receipts, [cached])

    def assert_app_error_for_changed_call_id_effect(self, receipts: list[dict[str, Any]]) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.lookup(self.metadata(call_id="call-1", effect_key="effect-2"), receipts)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "tool_call_conflict")

    def test_replays_successful_mutating_effect_with_different_call_id(self) -> None:
        cached = self.receipt()
        receipts = [cached]
        self.assertIs(self.service.lookup(self.metadata(), receipts), cached)
        self.assertEqual(receipts, [cached])

    def test_does_not_replay_effect_for_read_only_tool(self) -> None:
        receipt = self.receipt(name="get_profile")
        result = self.service.lookup(self.metadata(name="get_profile"), [receipt])
        self.assertIsNone(result)

    def test_allows_exact_call_id_replay_for_read_only_tool(self) -> None:
        receipt = self.receipt(call_id="call-new", name="get_profile")
        result = self.service.lookup(self.metadata(name="get_profile"), [receipt])
        self.assertIs(result, receipt)

    def test_does_not_replay_failed_effect(self) -> None:
        failed = self.receipt(result={"ok": False})
        self.assertIsNone(self.service.lookup(self.metadata(), [failed]))

    def test_does_not_replay_missing_or_stale_draft(self) -> None:
        for artifact_id, base_revision in (("stale", 2), ("missing", 3)):
            with self.subTest(artifact_id=artifact_id):
                if artifact_id != "missing":
                    self.seed_artifact(artifact_id, base_revision=base_revision)
                cached = self.receipt(result={"ok": True, "artifact_id": artifact_id})
                result = self.service.lookup(
                    self.metadata(name="stage_training_plan"), [cached]
                )
                self.assertIsNone(result)
                self.assertFalse(self.lock.held)

    def test_replays_draft_when_base_revision_matches_current_state(self) -> None:
        self.seed_artifact("current", base_revision=3)
        cached = self.receipt(result={"ok": True, "artifact_id": "current"})
        result = self.service.lookup(self.metadata(name="stage_training_plan"), [cached])
        self.assertIs(result, cached)
        self.assertFalse(self.lock.held)

    def test_replays_nondraft_artifact_when_base_revision_differs(self) -> None:
        self.seed_artifact("committed", status="committed", base_revision=2)
        cached = self.receipt(result={"ok": True, "artifact_id": "committed"})
        result = self.service.lookup(self.metadata(name="stage_training_plan"), [cached])
        self.assertIs(result, cached)
        self.assertFalse(self.lock.held)


if __name__ == "__main__":
    unittest.main()
