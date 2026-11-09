"""Coach plan sync from tool call to approved card to queued Intervals.icu job.

The athlete approves a card that lists the units. That card authorizes exactly
those units; the model's own scope tokens are not what decides it. Real services
run on a temporary SQLite database: dialogue classification, tool preparation,
card creation, confirmation, one-shot execution, plan selection and the job queue.
Only the planning-authority collaborator is mocked. No network, no real ``.env``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_read import CoachProposalConfirmationService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.daily import DailySyncMarkerService
from backend.sync.jobs import SyncJobStore
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.queue import SyncJobQueueService

NOW = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
SESSION = "owner-session"
CONVERSATION = "conversation-1"
TURN = "turn-1"
# The week of the athlete's report: three strength sessions, three runs, one ride.
WEEK = [
    ("00000000-0000-4000-8000-000000000001", "2026-11-09", "WeightTraining"),
    ("00000000-0000-4000-8000-000000000002", "2026-11-10", "Run"),
    ("00000000-0000-4000-8000-000000000003", "2026-11-11", "WeightTraining"),
    ("00000000-0000-4000-8000-000000000004", "2026-11-12", "Run"),
    ("00000000-0000-4000-8000-000000000005", "2026-11-13", "VirtualRide"),
    ("00000000-0000-4000-8000-000000000006", "2026-11-14", "WeightTraining"),
    ("00000000-0000-4000-8000-000000000007", "2026-11-15", "Run"),
]
OTHER_UNIT = "00000000-0000-4000-8000-0000000000ff"


def _payload(name: str, day: str, sport: str) -> str:
    return json.dumps({"name": name, "date": day, "type": sport}, sort_keys=True)


class CoachPlanSyncCardFlowCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = DatabaseManager(
            Path(temporary.name) / "coach.sqlite", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.database.close)
        with self.database.unit_of_work() as db:
            initialize_schema(db)
            for local_id, day, sport in (*WEEK, (OTHER_UNIT, "2026-11-20", "Run")):
                db.execute(
                    "INSERT INTO planned_units (local_id, payload, sync_dirty, sync_state, "
                    "revision, tombstone, created_at, updated_at) "
                    "VALUES (?, ?, 1, 'local', 1, 0, 'now', 'now')",
                    (local_id, _payload(f"{sport} {day}", day, sport)),
                )
            db.execute(
                "INSERT INTO messages(id, role, content, client_turn_id, created_at) "
                "VALUES (1, 'user', 'Sync diese Woche nach Intervals', ?, 'now')",
                (TURN,),
            )
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, "
                "target_system, status, receipt, created_at, updated_at) "
                "VALUES ('command-1', ?, ?, '{}', 'intervals', 'complete', ?, 'now', 'now')",
                (
                    TURN,
                    CONVERSATION,
                    json.dumps(
                        {"session_key": hashlib.sha256(SESSION.encode()).hexdigest()}
                    ),
                ),
            )
        identifiers = iter(f"job-{index}" for index in range(1, 100))
        self.queue = SyncJobQueueService(
            SyncJobStore(self.database, NOW.isoformat, lambda: next(identifiers)),
            mock.Mock(spec=StateEventBuffer),
            MaintenanceGate(),
            threading.Event(),
            all_sync_days=-1,
            daily_sync_markers=DailySyncMarkerService(
                self.database, KeyValueRepository(NOW.isoformat), lambda: NOW
            ),
        )
        self.authority = mock.Mock()
        self.sync_tools = CoachSyncToolService(
            self.queue,
            self.authority,
            mock.Mock(),
            StructuredPlanSyncService(
                self.database, self.authority, PlanPushCommandService(self.queue), 28
            ),
            mock.Mock(),
            PlanPushCommandService(self.queue),
            mock.Mock(),
        )
        dispatcher = mock.Mock()
        dispatcher.execute.side_effect = lambda name, arguments, **kwargs: (
            self.sync_tools.execute(
                name,
                arguments,
                intent=kwargs["intent"],
                sync_job_ids=kwargs["sync_job_ids"],
            )
        )
        self.clock = [1000.0]
        self.creation = CoachProposalCreationService(
            self.database,
            now=lambda: self.clock[0],
            utc_now=NOW.isoformat,
        )
        self.confirmation = CoachProposalConfirmationService(
            self.database, now=lambda: self.clock[0]
        )
        self.execution = CoachProposalExecutionService(
            self.database,
            mock.Mock(),
            mock.Mock(),
            MaintenanceGate(),
            lambda: dispatcher,
            now=lambda: self.clock[0],
            utc_now=NOW.isoformat,
        )
        self.preparation = CoachStructuredToolPreparationService(
            CoachDialogueActionService(
                self.database,
                threading.RLock(),
                lambda: self.queue,
                mock.Mock(),
                lambda: date(2026, 11, 9),
            ),
            self.authority,
            frozenset(),
        )

    def entries(self, ids: list[str]) -> list[dict[str, str]]:
        with self.database.reader() as db:
            payloads = {
                row["local_id"]: row["payload"]
                for row in db.execute("SELECT local_id, payload FROM planned_units")
            }
        return [
            {
                "library_workout_id": local_id,
                "expected_payload_hash": hashlib.sha256(
                    payloads[local_id].encode()
                ).hexdigest(),
            }
            for local_id in ids
        ]

    def coach_tool_call(self, ids: list[str], *, scope: list[str]) -> dict[str, Any]:
        """The model's call: entries by id and hash, a request without unit tokens."""
        arguments: dict[str, Any] = {
            "entries": self.entries(ids),
            "reason": "Woche nach Intervals",
            "_request": {
                "summary": "Wochenplan nach Intervals.icu synchronisieren",
                "source_message_ids": [1],
                "target": "intervals",
                "scope": scope,
                "period": {"start": "2026-11-09", "end": "2026-11-15"},
                "constraints": [],
                "remote_write": True,
                "sync_scope": "selected",
            },
        }
        metadata = {
            "name": "start_intervals_plan_sync",
            "arguments": arguments,
            "action": {},
        }
        action = self.preparation.prepare(
            metadata,
            [],
            question="",
            cancelled=False,
            context={
                "messages": [{"id": 1, "role": "user"}],
                "current_user_message_id": 1,
            },
            allow_mutations=True,
        )
        return {"arguments": arguments, "action": action}

    def card(self, call: dict[str, Any]) -> dict[str, Any]:
        return self.creation.create_remote_write(
            "start_intervals_plan_sync",
            call["arguments"],
            call["action"],
            conversation_id=CONVERSATION,
            client_turn_id=TURN,
            session_csrf_hash=SESSION,
        )["proposed_action"]

    def approve(self, card: dict[str, Any]) -> dict[str, Any]:
        confirmed = self.confirmation.confirm(card["id"], SESSION)
        return self.execution.execute(
            confirmed["action_token"],
            SESSION,
            confirmed["proposed_action"]["payload_hash"],
        )

    def plan_push_jobs(self) -> list[dict[str, Any]]:
        with self.database.reader() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT provider, type, requested_by, payload FROM sync_jobs "
                    "WHERE type='plan_push'"
                )
            ]


class ApprovedCardAuthorizesItsUnitsTests(CoachPlanSyncCardFlowCase):
    def test_mixed_week_card_is_approved_and_queues_one_plan_push_job(self) -> None:
        ids = [local_id for local_id, _, _ in WEEK]
        call = self.coach_tool_call(ids, scope=["intervals_sync"])

        card = self.card(call)

        self.assertEqual("remote_coach_write", card["action_type"])
        self.assertEqual(sorted(ids), sorted(detail["id"] for detail in card["diff"]))
        self.assertEqual(
            {"WeightTraining": 3, "Run": 3, "VirtualRide": 1},
            {
                sport: [detail["sport"] for detail in card["diff"]].count(sport)
                for sport in ("WeightTraining", "Run", "VirtualRide")
            },
        )
        self.assertEqual([], self.plan_push_jobs())

        result = self.approve(card)

        self.assertEqual("queued", result["status"])
        jobs = self.plan_push_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual(
            ("intervals", "coach"), (jobs[0]["provider"], jobs[0]["requested_by"])
        )
        queued = json.loads(jobs[0]["payload"])["entries"]
        self.assertEqual(sorted(ids), sorted(e["library_workout_id"] for e in queued))
        self.assertNotIn(OTHER_UNIT, {e["library_workout_id"] for e in queued})

    def test_card_creation_rejects_a_unit_that_does_not_exist(self) -> None:
        call = self.coach_tool_call([WEEK[0][0]], scope=["intervals_sync"])
        call["arguments"]["entries"][0]["library_workout_id"] = (
            "00000000-0000-4000-8000-0000000000aa"
        )

        with self.assertRaises(AppError) as caught:
            self.card(call)

        self.assertEqual("request_object_missing", caught.exception.reason)

    def test_a_model_call_without_a_card_still_cannot_push(self) -> None:
        """No attended approval, no authorization: the guard is unchanged."""
        call = self.coach_tool_call([WEEK[0][0]], scope=["intervals_sync"])

        with self.assertRaises(AppError) as caught:
            self.sync_tools.execute(
                "start_intervals_plan_sync",
                call["arguments"],
                intent=call["action"],
                sync_job_ids=[],
            )

        self.assertEqual(
            (403, "intent_scope_denied"),
            (caught.exception.status, caught.exception.reason),
        )
        self.assertEqual([], self.plan_push_jobs())


if __name__ == "__main__":
    unittest.main()
