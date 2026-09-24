"""Direct contracts for structured Coach tool execution orchestration."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Self
from unittest.mock import Mock, patch

from backend.activities.duplicates import duplicate_delete_action
from backend.coach.clarification import CoachClarificationService
from backend.coach.proposals import CoachProposalCreationService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.training_patch import CoachTrainingPatchService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.sync.state import SyncStateRepository


class TrackingLock:
    def __init__(self) -> None:
        self.held = False
        self.enter_count = 0

    def __enter__(self) -> Self:
        if self.held:
            raise AssertionError("execution lock must not be re-entered")
        self.held = True
        self.enter_count += 1
        return self

    def __exit__(self, *_exc: object) -> None:
        self.held = False


class LockCheckingDatabaseManager(DatabaseManager):
    def __init__(self, path: Path, lock: TrackingLock) -> None:
        super().__init__(path, sqlite3, row_factory=sqlite3.Row, persist_connections=False)
        self._tracking_lock = lock
        self.uow_count = 0

    @contextmanager
    def unit_of_work(self) -> Iterator[Any]:
        if not self._tracking_lock.held:
            raise AssertionError("database unit of work must run under the injected lock")
        self.uow_count += 1
        with super().unit_of_work() as db:
            yield db


class StructuredToolExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="coach-tool-execution-")
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name) / "coach.sqlite3"
        self.lock = TrackingLock()
        self.database_manager = LockCheckingDatabaseManager(path, self.lock)
        self.addCleanup(self.database_manager.close)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute("CREATE TABLE synthetic_writes (value TEXT NOT NULL)")
        self.key_values = KeyValueRepository(lambda: "2026-09-24T00:00:00+00:00")
        self.clarification = Mock(spec=CoachClarificationService)
        self.training_patch = Mock(spec=CoachTrainingPatchService)
        self.sync_state = Mock(spec=SyncStateRepository)
        self.proposal_creation = Mock(spec=CoachProposalCreationService)
        self.tool_dispatch = Mock(spec=CoachToolDispatchService)
        self.service = CoachStructuredToolExecutionService(
            self.database_manager,
            self.lock,
            self.key_values,
            self.clarification,
            self.training_patch,
            self.sync_state,
            self.proposal_creation,
            self.tool_dispatch,
        )

    @staticmethod
    def metadata(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"name": name, "arguments": arguments or {}}

    def execute(self, name: str, arguments: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "action": {"operation": name, "authorization_scope": ["local_plan"]},
            "context": {"messages": [{"role": "user", "id": 3}]},
            "conversation_id": "conversation-1",
            "client_turn_id": "turn-1",
            "session_csrf_hash": "csrf-hash",
            "sync_job_ids": ["job-1"],
            "cancel_event": threading.Event(),
        }
        values.update(kwargs)
        return self.service.execute(self.metadata(name, arguments), **values)

    def test_clarification_delegates_provenance_and_context(self) -> None:
        expected = {"ok": True, "status": "needs_clarification"}
        arguments = {"question": "Which day?", "source_message_ids": [3]}
        context = {"messages": [{"role": "user", "id": 3}]}
        self.clarification.save_question.return_value = expected

        self.assertIs(self.execute("clarify_coach_request", arguments, context=context), expected)
        self.clarification.save_question.assert_called_once_with(arguments, context)
        self.assertEqual(self.lock.enter_count, 1)
        self.assertEqual(self.database_manager.uow_count, 1)

    def test_cancel_persists_null_inside_locked_unit_of_work(self) -> None:
        self.assertEqual(
            self.execute("cancel_coach_request"), {"ok": True, "status": "cancelled"}
        )
        with closing(sqlite3.connect(self.database_manager.path)) as db:
            self.assertEqual(
                db.execute("SELECT value FROM kv WHERE key = 'coach_pending_request'").fetchone()[0],
                "null",
            )
        self.assertEqual(self.lock.enter_count, 1)
        self.assertEqual(self.database_manager.uow_count, 1)

    def test_training_patch_failure_rolls_back_and_releases_lock(self) -> None:
        arguments = {"changes": [{"local_id": "unit-1", "action": "update"}]}
        action = {"operation": "apply_training_patch", "authorization_scope": ["local_plan"]}

        def write_then_fail(_arguments: dict[str, Any], _action: dict[str, Any]) -> None:
            with self.database_manager.unit_of_work() as db:
                db.execute("INSERT INTO synthetic_writes(value) VALUES ('should roll back')")
            raise AppError(409, "Revision changed", reason="revision_conflict")

        self.training_patch.apply.side_effect = write_then_fail
        with self.assertRaisesRegex(AppError, "Revision changed"):
            self.execute("apply_training_patch", arguments, action=action)

        with closing(sqlite3.connect(self.database_manager.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM synthetic_writes").fetchone()[0], 0)
        self.assertFalse(self.lock.held)
        self.assertEqual(self.lock.enter_count, 1)
        self.assertEqual(self.database_manager.uow_count, 2)
        self.training_patch.apply.assert_called_once_with(arguments, action)

    def test_duplicate_inspection_only_creates_session_bound_delete_proposal(self) -> None:
        duplicate = {
            "canonical_id": "900",
            "canonical_name": "Run A",
            "duplicate_id": "901",
            "duplicate_name": "Run A copy",
            "start_date_local": "2026-09-20T08:00:00",
            "moving_time": 1200,
            "distance": 5000,
            "snapshot_synced_at": "2026-09-21T00:00:00Z",
        }
        self.sync_state.latest_snapshot.return_value = {"duplicate": duplicate}
        with patch(
            "backend.coach.tool_execution_service.latest_wahoo_garmin_duplicate",
            return_value=duplicate,
        ):
            result = self.execute("inspect_activity_duplicates", session_csrf_hash="")

        self.assertEqual(result, {"ok": True, "duplicate": duplicate})
        self.proposal_creation.create.assert_not_called()
        self.sync_state.latest_snapshot.assert_called_once_with()

        self.proposal_creation.create.return_value = {"proposal": {"id": "proposal-1"}}
        with patch(
            "backend.coach.tool_execution_service.latest_wahoo_garmin_duplicate",
            return_value=duplicate,
        ):
            result = self.execute("inspect_activity_duplicates", session_csrf_hash="bound-csrf")
        self.assertEqual(result, {"ok": True, "duplicate": duplicate, "proposal": {"id": "proposal-1"}})
        self.proposal_creation.create.assert_called_once_with(
            duplicate_delete_action(duplicate), "bound-csrf"
        )

    def test_dispatch_receives_complete_turn_and_cancellation_context(self) -> None:
        expected = {"ok": True, "status": "completed"}
        arguments = {"target": "intervals", "_request": {"period": {"start": "2026-09-20"}}}
        action = {"operation": "start_provider_refresh", "remote_write": False}
        cancel_event = threading.Event()
        self.tool_dispatch.execute.return_value = expected

        self.assertIs(
            self.execute(
                "start_provider_refresh",
                arguments,
                action=action,
                conversation_id="conversation-x",
                client_turn_id="turn-x",
                session_csrf_hash="csrf-x",
                sync_job_ids=["sync-x"],
                cancel_event=cancel_event,
            ),
            expected,
        )
        self.tool_dispatch.execute.assert_called_once_with(
            "start_provider_refresh",
            arguments,
            intent=action,
            conversation_id="conversation-x",
            client_turn_id="turn-x",
            session_csrf_hash="csrf-x",
            sync_job_ids=["sync-x"],
            cancel_event=cancel_event,
        )
        self.assertEqual(self.lock.enter_count, 0)
        self.assertEqual(self.database_manager.uow_count, 0)

    def test_adaptive_apply_is_also_outside_local_database_transaction(self) -> None:
        self.tool_dispatch.execute.return_value = {"ok": True}

        self.assertEqual(self.execute("apply_adaptive_replan"), {"ok": True})
        self.assertEqual(self.lock.enter_count, 0)
        self.assertEqual(self.database_manager.uow_count, 0)


if __name__ == "__main__":
    unittest.main()
