"""Coach sync from tool call to approved card to queued provider job.

The athlete approves a card that lists the units. That card authorizes exactly
those units; the model's own scope tokens are not what decides it. Real services
run on a temporary SQLite database: dialogue classification, tool preparation,
card creation, confirmation, one-shot execution, plan selection, planning
authority, nutrition manifests and the job queue. Every card kind of the Coach
and every provider refresh target is driven through that chain. No network, no
real ``.env``.
"""

from __future__ import annotations

import hashlib
import json
import threading
import unittest
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from unittest import mock

from nutrition_service_support import build_nutrition_services
from support import temp_database

from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_models import REMOTE_COACH_WRITE_TOOLS
from backend.coach.proposal_read import CoachProposalConfirmationService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import planned_units
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.authority import PlanningAuthorityService
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.daily import DailySyncMarkerService
from backend.sync.jobs import SyncJobStore
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
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


RACE = "race-1"
STRENGTH_IDS = [WEEK[0][0], WEEK[2][0], WEEK[5][0]]
NUTRITION_DAY = "2026-11-09"
SELECTED = "selected"


@dataclass(frozen=True)
class CardFlow:
    """The real Coach services of one card chain over one temporary database."""

    database: DatabaseManager
    sync_tools: CoachSyncToolService
    creation: CoachProposalCreationService
    confirmation: CoachProposalConfirmationService
    execution: CoachProposalExecutionService
    preparation: CoachStructuredToolPreparationService
    inline_refreshes: dict[str, Any]
    queue: SyncJobQueueService
    tools: CoachStructuredToolExecutionService


def wire_card_flow(case: unittest.TestCase) -> CardFlow:
    """Build the real Coach card chain on a temporary database for one case."""
    database = temp_database(case, "coach.sqlite", row_factory=row_factory)
    # A refresh the descriptor makes the Coach wait for runs inline, not queued.
    inline_refreshes = {
        descriptor.provider_id: mock.Mock(
            refresh=mock.Mock(return_value={"ok": True, "status": "completed"})
        )
        for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
        if descriptor.coach_waits_for_completion
    }
    with database.unit_of_work() as db:
        initialize_schema(db)
        for local_id, day, sport in (*WEEK, (OTHER_UNIT, "2026-11-20", "Run")):
            db.execute(
                "INSERT INTO planned_units (local_id, payload, sync_dirty, sync_state, "
                "revision, tombstone, created_at, updated_at) "
                "VALUES (?, ?, 1, 'local', 1, 0, 'now', 'now')",
                (local_id, _payload(f"{sport} {day}", day, sport)),
            )
        db.execute(
            "INSERT INTO competitions (id, name, event_date, sport, priority, distance, "
            "target, course_profile, notes, created_at, updated_at) "
            "VALUES (?, 'Race', '2026-12-01', 'Run', 'A', '', '', '', '', 'now', 'now')",
            (RACE,),
        )
        db.execute(
            "INSERT INTO messages(id, role, content, client_turn_id, created_at) "
            "VALUES (1, 'user', 'Sync diese Woche', ?, 'now')",
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
    queue = SyncJobQueueService(
        SyncJobStore(database, NOW.isoformat, lambda: next(identifiers)),
        mock.Mock(spec=StateEventBuffer),
        MaintenanceGate(),
        threading.Event(),
        all_sync_days=-1,
        daily_sync_markers=DailySyncMarkerService(
            database, KeyValueRepository(NOW.isoformat), lambda: NOW
        ),
    )
    authority = PlanningAuthorityService(
        database, mock.Mock(), mock.Mock(), NOW.isoformat
    )
    diary, _library = build_nutrition_services(
        database, threading.RLock(), NOW.isoformat, lambda: NOW
    )
    plan_push = PlanPushCommandService(queue)
    sync_tools = CoachSyncToolService(
        queue,
        authority,
        SyncConflictCommandService(mock.Mock(), queue),
        StructuredPlanSyncService(database, authority, plan_push, 28),
        mock.Mock(),
        plan_push,
        ProviderRefreshCommandService(queue, inline_refreshes),
        diary,
    )
    dispatcher = mock.Mock()
    dispatcher.execute.side_effect = lambda name, arguments, **kwargs: (
        sync_tools.execute(
            name,
            arguments,
            intent=kwargs["intent"],
            sync_job_ids=kwargs["sync_job_ids"],
        )
    )
    clock = [1000.0]
    creation = CoachProposalCreationService(
        database,
        now=lambda: clock[0],
        utc_now=NOW.isoformat,
        nutrition_diary_service=lambda: diary,
        today=lambda: date(2026, 11, 9),
    )
    confirmation = CoachProposalConfirmationService(database, now=lambda: clock[0])
    execution = CoachProposalExecutionService(
        database,
        mock.Mock(),
        mock.Mock(),
        MaintenanceGate(),
        lambda: dispatcher,
        now=lambda: clock[0],
        utc_now=NOW.isoformat,
    )
    preparation = CoachStructuredToolPreparationService(
        CoachDialogueActionService(
            database,
            threading.RLock(),
            lambda: queue,
            mock.Mock(),
            lambda: date(2026, 11, 9),
        ),
        authority,
        frozenset(),
    )
    return CardFlow(
        database=database,
        sync_tools=sync_tools,
        creation=creation,
        confirmation=confirmation,
        execution=execution,
        preparation=preparation,
        inline_refreshes=inline_refreshes,
        queue=queue,
        tools=CoachStructuredToolExecutionService(
            database,
            threading.RLock(),
            KeyValueRepository(NOW.isoformat),
            mock.Mock(),
            mock.Mock(),
            creation,
            dispatcher,
            nullcontext(),
        ),
    )


def unit_entries(flow: CardFlow, ids: list[str]) -> list[dict[str, str]]:
    with flow.database.reader() as db:
        payloads = {
            row["local_id"]: row["payload"]
            for row in db.execute("SELECT local_id, payload FROM planned_units")
        }
    return [
        {
            "library_workout_id": local_id,
            # The content-only hash plan pushes record and check (#1916).
            "expected_payload_hash": planned_units.plan_push_payload_hash(
                payloads[local_id]
            ),
        }
        for local_id in ids
    ]


def request_for(
    target: str, scope: list[str], *, sync_scope: str | None, remote_write: bool = True
) -> dict[str, Any]:
    """The model's validated request: the athlete's message, target and scope."""
    return {
        "summary": "Auftrag des Athleten",
        "source_message_ids": [1],
        "target": target,
        "scope": scope,
        "period": {"start": "2026-11-09", "end": "2026-11-15"},
        "constraints": [],
        "remote_write": remote_write,
        "sync_scope": sync_scope,
    }


def prepared_call(
    flow: CardFlow, tool: str, arguments: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """The model's tool call after dialogue classification and tool preparation."""
    arguments = {**arguments, "_request": request}
    action = flow.preparation.prepare(
        {"name": tool, "arguments": arguments, "action": {}},
        [],
        question="",
        cancelled=False,
        context={
            "messages": [{"id": 1, "role": "user"}],
            "current_user_message_id": 1,
        },
        allow_mutations=True,
    )
    return {"tool": tool, "arguments": arguments, "action": action}


def create_card(flow: CardFlow, call: dict[str, Any]) -> dict[str, Any]:
    return flow.creation.create_remote_write(
        call["tool"],
        call["arguments"],
        call["action"],
        conversation_id=CONVERSATION,
        client_turn_id=TURN,
        session_csrf_hash=SESSION,
    )["proposed_action"]


def run_in_turn(flow: CardFlow, call: dict[str, Any]) -> dict[str, Any]:
    """Run the call as the Coach turn does, after the write gate allowed it."""
    return flow.tools.execute(
        {"name": call["tool"], "arguments": call["arguments"]},
        action=call["action"],
        context={},
        conversation_id=CONVERSATION,
        client_turn_id=TURN,
        session_csrf_hash=SESSION,
        sync_job_ids=[],
        cancel_event=None,
    )


def card_count(flow: CardFlow) -> int:
    with flow.database.reader() as db:
        return int(
            db.execute("SELECT COUNT(*) AS n FROM coach_action_proposals").fetchone()[
                "n"
            ]
        )


def approve_card(flow: CardFlow, card: dict[str, Any]) -> dict[str, Any]:
    confirmed = flow.confirmation.confirm(card["id"], SESSION)
    return flow.execution.execute(
        confirmed["action_token"], SESSION, confirmed["proposed_action"]["payload_hash"]
    )


def queued_jobs(flow: CardFlow, job_type: str | None = None) -> list[dict[str, Any]]:
    with flow.database.reader() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT id, provider, type, status, requested_by, payload "
                "FROM sync_jobs WHERE ? IS NULL OR type=? ORDER BY created_at, id",
                (job_type, job_type),
            )
        ]


def plan_sync_request(scope: list[str]) -> dict[str, Any]:
    return request_for("intervals", scope, sync_scope=SELECTED)


class ApprovedCardAuthorizesItsUnitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = wire_card_flow(self)

    def coach_tool_call(self, ids: list[str], *, scope: list[str]) -> dict[str, Any]:
        """The model's call: entries by id and hash, a request without unit tokens."""
        return prepared_call(
            self.flow,
            "start_intervals_plan_sync",
            {"entries": unit_entries(self.flow, ids), "reason": "Woche nach Intervals"},
            plan_sync_request(scope),
        )

    def plan_push_jobs(self) -> list[dict[str, Any]]:
        return queued_jobs(self.flow, "plan_push")

    def test_mixed_week_card_is_approved_and_queues_one_plan_push_job(self) -> None:
        ids = [local_id for local_id, _, _ in WEEK]
        call = self.coach_tool_call(ids, scope=["intervals_sync"])

        card = create_card(self.flow, call)

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

        result = approve_card(self.flow, card)

        self.assertEqual("queued", result["status"])
        jobs = self.plan_push_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual(
            ("intervals", "coach"), (jobs[0]["provider"], jobs[0]["requested_by"])
        )
        queued = json.loads(jobs[0]["payload"])["entries"]
        self.assertEqual(sorted(ids), sorted(e["library_workout_id"] for e in queued))
        self.assertNotIn(OTHER_UNIT, {e["library_workout_id"] for e in queued})

    def test_unit_tokens_from_the_model_never_widen_the_card(self) -> None:
        call = self.coach_tool_call(
            [WEEK[0][0]],
            scope=["intervals_sync", f"planned_unit:{OTHER_UNIT}"],
        )

        card = create_card(self.flow, call)
        approve_card(self.flow, card)

        queued = json.loads(self.plan_push_jobs()[0]["payload"])["entries"]
        self.assertEqual([WEEK[0][0]], [e["library_workout_id"] for e in queued])
        with self.flow.database.reader() as db:
            row = db.execute("SELECT payload FROM coach_action_proposals").fetchone()
        scope = json.loads(row["payload"])["intent"]["authorization_scope"]
        self.assertNotIn(f"planned_unit:{OTHER_UNIT}", scope)

    def test_without_a_card_the_request_scope_bounds_the_units(self) -> None:
        """No card shows the model's selection (#2342), so its own unit tokens
        bound what a card-free sync may push."""
        ids = [local_id for local_id, _, _ in WEEK]
        call = self.coach_tool_call(
            ids, scope=["intervals_sync", f"planned_unit:{WEEK[0][0]}"]
        )

        with self.assertRaises(AppError) as caught:
            run_in_turn(self.flow, call)

        self.assertEqual(
            (403, "intent_scope_denied"),
            (caught.exception.status, caught.exception.reason),
        )
        self.assertEqual([], self.plan_push_jobs())

    def test_card_creation_rejects_a_unit_that_does_not_exist(self) -> None:
        call = self.coach_tool_call([WEEK[0][0]], scope=["intervals_sync"])
        call["arguments"]["entries"][0]["library_workout_id"] = (
            "00000000-0000-4000-8000-0000000000aa"
        )

        with self.assertRaises(AppError) as caught:
            create_card(self.flow, call)

        self.assertEqual("request_object_missing", caught.exception.reason)

    def test_a_model_call_without_a_card_still_cannot_push(self) -> None:
        """No attended approval, no authorization: the guard is unchanged."""
        call = self.coach_tool_call([WEEK[0][0]], scope=["intervals_sync"])

        with self.assertRaises(AppError) as caught:
            self.flow.sync_tools.execute(
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


def _plan_sync_call(flow: CardFlow, *tokens: str) -> dict[str, Any]:
    return prepared_call(
        flow,
        "start_intervals_plan_sync",
        {"entries": unit_entries(flow, [WEEK[1][0]]), "reason": "Lauf"},
        plan_sync_request(["intervals_sync", *tokens]),
    )


def _named_plan_sync_call(flow: CardFlow) -> dict[str, Any]:
    """Without a card the model's own unit token authorizes the unit (#2342)."""
    return _plan_sync_call(flow, f"planned_unit:{WEEK[1][0]}")


def _garmin_call(flow: CardFlow) -> dict[str, Any]:
    return prepared_call(
        flow,
        "push_strength_to_garmin",
        {"entries": [{"local_id": local_id} for local_id in STRENGTH_IDS]},
        request_for(
            "garmin",
            ["garmin_sync", *(f"planned_unit:{local_id}" for local_id in STRENGTH_IDS)],
            sync_scope=SELECTED,
        ),
    )


def _competition_call(flow: CardFlow) -> dict[str, Any]:
    return prepared_call(
        flow,
        "sync_competitions",
        {"reason": "Wettkämpfe"},
        request_for(
            "intervals", ["local_competitions", "intervals_sync"], sync_scope=None
        ),
    )


def _nutrition_call(flow: CardFlow) -> dict[str, Any]:
    return prepared_call(
        flow,
        "sync_nutrition",
        {"date": NUTRITION_DAY},
        request_for(
            "intervals", ["local_nutrition", "intervals_sync"], sync_scope=None
        ),
    )


# Card kind -> (call builder, provider, job type, payload key the card binds).
CARD_KINDS: dict[str, tuple[Any, str, str, str]] = {
    "start_intervals_plan_sync": (_plan_sync_call, "intervals", "plan_push", "entries"),
    "push_strength_to_garmin": (_garmin_call, "garmin", "plan_push", "entries"),
    "sync_competitions": (
        _competition_call,
        "intervals",
        "competition_push",
        "approval_manifest",
    ),
    "sync_nutrition": (
        _nutrition_call,
        "intervals",
        "nutrition_sync",
        "approval_manifest",
    ),
}
# Remote-write tools that queue no job of their own kind: a retry requeues an
# existing job (tested below) and the adaptive apply changes local plans first.
OTHER_CARDS: dict[str, str] = {
    "resolve_training_sync_conflict": "retry of an existing job, below",
    "apply_adaptive_replan": "tests/test_coach_adaptive_apply.py",
}
REFRESH_TARGETS = ("calendar", "garmin", "wahoo", "weather")
WAITING_TARGETS = ("garmin", "wahoo")


class EveryCardKindQueuesItsProviderJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = wire_card_flow(self)

    def test_the_covered_card_kinds_are_all_remote_write_tools(self) -> None:
        self.assertEqual(REMOTE_COACH_WRITE_TOOLS, {*CARD_KINDS, *OTHER_CARDS})

    def test_each_card_kind_queues_its_provider_job_only_after_approval(self) -> None:
        for tool, (build, provider, job_type, bound) in CARD_KINDS.items():
            with self.subTest(tool=tool):
                self.flow = wire_card_flow(self)
                card = create_card(self.flow, build(self.flow))

                self.assertEqual("remote_coach_write", card["action_type"])
                self.assertEqual(provider, card["target_system"])
                self.assertEqual([], queued_jobs(self.flow))

                result = approve_card(self.flow, card)

                self.assertEqual("queued", result["status"], result)
                jobs = queued_jobs(self.flow)
                self.assertEqual(
                    [(provider, job_type, "coach")],
                    [(j["provider"], j["type"], j["requested_by"]) for j in jobs],
                )
                self.assertTrue(json.loads(jobs[0]["payload"])[bound])

    def test_a_named_sync_queues_the_same_job_without_a_card(self) -> None:
        """The athlete's named sync is the approval (#2342); the job binds the
        same stored state an approved card would."""
        for tool, (build, provider, job_type, bound) in CARD_KINDS.items():
            with self.subTest(tool=tool):
                self.flow = wire_card_flow(self)
                if tool == "start_intervals_plan_sync":
                    build = _named_plan_sync_call

                result = run_in_turn(self.flow, build(self.flow))

                self.assertEqual("queued", result["status"], result)
                self.assertEqual(0, card_count(self.flow))
                jobs = queued_jobs(self.flow)
                self.assertEqual(
                    [(provider, job_type, "coach")],
                    [(j["provider"], j["type"], j["requested_by"]) for j in jobs],
                )
                self.assertTrue(json.loads(jobs[0]["payload"])[bound])

    def test_an_explicit_garmin_removal_still_asks_on_a_card(self) -> None:
        call = prepared_call(
            self.flow,
            "push_strength_to_garmin",
            {"entries": [{"local_id": STRENGTH_IDS[0], "remove": True}]},
            request_for(
                "garmin",
                ["garmin_sync", f"planned_unit:{STRENGTH_IDS[0]}"],
                sync_scope=SELECTED,
            ),
        )

        result = run_in_turn(self.flow, call)

        self.assertEqual("approval_required", result["status"])
        self.assertEqual(1, card_count(self.flow))
        self.assertEqual([], queued_jobs(self.flow))

    def test_the_garmin_card_binds_each_selected_unit_to_its_payload_hash(self) -> None:
        card = create_card(self.flow, _garmin_call(self.flow))
        approve_card(self.flow, card)

        queued = json.loads(queued_jobs(self.flow, "plan_push")[0]["payload"])[
            "entries"
        ]

        self.assertEqual(unit_entries(self.flow, STRENGTH_IDS), queued)

    def test_a_garmin_selection_outside_the_request_scope_is_rejected(self) -> None:
        with self.assertRaises(AppError):
            prepared_call(
                self.flow,
                "push_strength_to_garmin",
                {"entries": [{"local_id": id_} for id_ in (*STRENGTH_IDS, OTHER_UNIT)]},
                request_for(
                    "garmin",
                    ["garmin_sync", *(f"planned_unit:{id_}" for id_ in STRENGTH_IDS)],
                    sync_scope=SELECTED,
                ),
            )

        self.assertEqual([], queued_jobs(self.flow))

    def test_the_competition_card_binds_the_dirty_competition(self) -> None:
        card = create_card(self.flow, _competition_call(self.flow))
        approve_card(self.flow, card)

        manifest = json.loads(queued_jobs(self.flow, "competition_push")[0]["payload"])[
            "approval_manifest"
        ]

        self.assertEqual(
            [("competition", RACE)], [(m["type"], m["id"]) for m in manifest]
        )

    def test_a_failed_intervals_push_is_retried_through_its_card(self) -> None:
        approve_card(self.flow, create_card(self.flow, _plan_sync_call(self.flow)))
        job = queued_jobs(self.flow, "plan_push")[0]
        with self.flow.database.unit_of_work() as db:
            db.execute("UPDATE sync_jobs SET status='failed' WHERE id=?", (job["id"],))
        retry = prepared_call(
            self.flow,
            "resolve_training_sync_conflict",
            {"job_id": job["id"]},
            request_for(
                "intervals",
                [f"sync_job:{job['id']}", "intervals_sync"],
                sync_scope=None,
            ),
        )

        result = approve_card(self.flow, create_card(self.flow, retry))

        self.assertEqual("queued", result["status"])
        self.assertEqual(
            [(job["id"], "queued")],
            [(j["id"], j["status"]) for j in queued_jobs(self.flow, "plan_push")],
        )

    def test_a_model_call_without_a_card_queues_no_card_job(self) -> None:
        for tool, (build, _provider, _job_type, _bound) in CARD_KINDS.items():
            with self.subTest(tool=tool):
                self.flow = wire_card_flow(self)
                call = build(self.flow)

                with self.assertRaises(AppError) as caught:
                    self.flow.sync_tools.execute(
                        tool,
                        call["arguments"],
                        intent=call["action"],
                        sync_job_ids=[],
                    )

                self.assertIn(caught.exception.status, {403, 409})
                self.assertEqual([], queued_jobs(self.flow))


# Provider -> (job type, label the athlete reads); each plan push is a remote
# write, each refresh a read.
RETRIED_JOBS = (
    ("intervals", "plan_push", "Intervals.icu"),
    ("garmin", "plan_push", "Garmin"),
    ("garmin", "refresh", "Garmin"),
    ("wahoo", "plan_push", "Wahoo"),
    ("wahoo", "refresh", "Wahoo"),
)


def failed_job(flow: CardFlow, provider: str, job_type: str) -> dict[str, Any]:
    """Queue one job of the provider and type and mark it failed."""
    if job_type == "plan_push":
        entries = unit_entries(flow, STRENGTH_IDS)
        if provider != "intervals":
            entries = [
                {"local_id": entry["library_workout_id"], **entry} for entry in entries
            ]
        job = flow.queue.enqueue(
            provider,
            "plan_push",
            {"entries": entries, "reason": "Synthetic retry"},
            requested_by="coach",
            item_operations=[
                {
                    "item_key": entry["library_workout_id"],
                    "operation": "plan_push",
                    "payload_hash": entry["expected_payload_hash"],
                }
                for entry in unit_entries(flow, STRENGTH_IDS)
            ],
        )
    else:
        job = flow.queue.enqueue(
            provider, "refresh", {"reason": "Synthetic retry", "days": 7}
        )
    with flow.database.unit_of_work() as db:
        db.execute("UPDATE sync_jobs SET status='failed' WHERE id=?", (job["id"],))
    return job


def retry_call(
    flow: CardFlow, job: dict[str, Any], *, target: str, scope: str, push: bool
) -> dict[str, Any]:
    return prepared_call(
        flow,
        "resolve_training_sync_conflict",
        {"job_id": job["id"]},
        request_for(
            target, [f"sync_job:{job['id']}", scope], sync_scope=None, remote_write=push
        ),
    )


def job_status(flow: CardFlow, job_id: str) -> str:
    return next(j["status"] for j in queued_jobs(flow) if j["id"] == job_id)


class RetryByJobProviderTests(unittest.TestCase):
    """A retry takes its target and sync scope from the job it retries."""

    def setUp(self) -> None:
        self.flow = wire_card_flow(self)

    def test_every_provider_and_job_type_retries_with_its_own_scope(self) -> None:
        for provider, job_type, label in RETRIED_JOBS:
            with self.subTest(provider=provider, job_type=job_type):
                self.flow = wire_card_flow(self)
                job = failed_job(self.flow, provider, job_type)
                push = job_type == "plan_push"
                call = retry_call(
                    self.flow,
                    job,
                    target=provider,
                    scope=f"{provider}_{'sync' if push else 'refresh'}",
                    push=push,
                )

                if push:
                    card = create_card(self.flow, call)
                    self.assertEqual(provider, card["target_system"])
                    self.assertIn(label, card["diff"][0]["name"])
                    for other in {"Intervals.icu", "Garmin", "Wahoo"} - {label}:
                        self.assertNotIn(other, card["diff"][0]["name"])
                    self.assertEqual("failed", job_status(self.flow, job["id"]))
                    result = approve_card(self.flow, card)
                    self.assertEqual("queued", result["status"], result)
                else:
                    jobs: list[str] = []
                    self.flow.sync_tools.execute(
                        "resolve_training_sync_conflict",
                        call["arguments"],
                        intent=call["action"],
                        sync_job_ids=jobs,
                    )
                    self.assertEqual([job["id"]], jobs)
                self.assertEqual("queued", job_status(self.flow, job["id"]))

    def test_a_named_push_retry_runs_without_a_card_unless_it_removes_from_garmin(
        self,
    ) -> None:
        # A retry is a named sync (#2342); a Garmin removal keeps its card.
        for provider, removes, expected in (
            ("intervals", False, "queued"),
            ("garmin", False, "queued"),
            ("garmin", True, "approval_required"),
        ):
            with self.subTest(provider=provider, removes=removes):
                self.flow = wire_card_flow(self)
                job = failed_job(self.flow, provider, "plan_push")
                if removes:
                    payload = json.loads(queued_jobs(self.flow)[0]["payload"])
                    payload["entries"][0] = {
                        "library_workout_id": STRENGTH_IDS[0],
                        "remove": True,
                    }
                    with self.flow.database.unit_of_work() as db:
                        db.execute(
                            "UPDATE sync_jobs SET payload=? WHERE id=?",
                            (json.dumps(payload), job["id"]),
                        )
                call = retry_call(
                    self.flow, job, target=provider, scope=f"{provider}_sync", push=True
                )

                result = run_in_turn(self.flow, call)

                self.assertEqual(expected, result["status"], result)
                self.assertEqual(int(removes), card_count(self.flow))

    def test_a_push_retry_without_the_job_providers_sync_scope_is_denied(self) -> None:
        for provider, job_type, label in RETRIED_JOBS:
            if job_type != "plan_push":
                continue
            wrong = "garmin_sync" if provider != "garmin" else "intervals_sync"
            with self.subTest(provider=provider):
                job = failed_job(self.flow, provider, job_type)
                with self.assertRaises(AppError) as caught:
                    retry_call(self.flow, job, target=provider, scope=wrong, push=True)
                self.assertEqual(
                    (403, "remote_scope_denied"),
                    (caught.exception.status, caught.exception.reason),
                )
                self.assertIn(label, str(caught.exception))
                self.assertEqual("failed", job_status(self.flow, job["id"]))

    def test_a_retry_aimed_at_another_provider_is_denied_by_name(self) -> None:
        for provider, target in (("garmin", "intervals"), ("wahoo", "garmin")):
            with self.subTest(provider=provider):
                job = failed_job(self.flow, provider, "plan_push")
                with self.assertRaises(AppError) as caught:
                    retry_call(
                        self.flow,
                        job,
                        target=target,
                        scope=f"{target}_sync",
                        push=True,
                    )
                self.assertEqual("request_target", caught.exception.reason)
                self.assertIn(provider.capitalize(), str(caught.exception))

    def test_a_push_retry_declared_as_a_read_is_denied(self) -> None:
        for provider in ("garmin", "wahoo"):
            with self.subTest(provider=provider):
                job = failed_job(self.flow, provider, "plan_push")
                with self.assertRaises(AppError) as caught:
                    retry_call(
                        self.flow,
                        job,
                        target=provider,
                        scope=f"{provider}_refresh",
                        push=False,
                    )
                self.assertEqual("remote_scope_denied", caught.exception.reason)
                self.assertEqual("failed", job_status(self.flow, job["id"]))


class ProviderRefreshByCoachTests(unittest.TestCase):
    """A read-only refresh needs no card; each Coach refresh target reaches the queue."""

    def test_the_refresh_targets_are_the_registry_coach_targets(self) -> None:
        self.assertEqual(
            REFRESH_TARGETS,
            tuple(sorted(DEFAULT_PROVIDER_REGISTRY.coach_refresh_targets())),
        )

    def refresh(self, provider: str) -> tuple[dict[str, Any], list[str]]:
        self.flow = wire_card_flow(self)
        call = prepared_call(
            self.flow,
            "start_provider_refresh",
            {"reason": "aktuelle Daten"},
            request_for(
                provider, [f"{provider}_refresh"], sync_scope=None, remote_write=False
            ),
        )
        job_ids: list[str] = []
        result = self.flow.sync_tools.execute(
            "start_provider_refresh",
            call["arguments"],
            intent=call["action"],
            sync_job_ids=job_ids,
        )
        assert result is not None
        return result, job_ids

    def test_the_providers_the_coach_waits_for_are_garmin_and_wahoo(self) -> None:
        self.flow = wire_card_flow(self)
        self.assertEqual(WAITING_TARGETS, tuple(sorted(self.flow.inline_refreshes)))

    def test_each_other_target_queues_a_refresh_job_requested_by_the_coach(
        self,
    ) -> None:
        for provider in sorted(set(REFRESH_TARGETS) - set(WAITING_TARGETS)):
            with self.subTest(provider=provider):
                result, job_ids = self.refresh(provider)

                self.assertEqual("queued", result["status"])
                jobs = queued_jobs(self.flow)
                self.assertEqual(
                    [(provider, "refresh", "coach")],
                    [(j["provider"], j["type"], j["requested_by"]) for j in jobs],
                )
                self.assertEqual([jobs[0]["id"]], job_ids)

    def test_a_waited_for_target_refreshes_inline_without_a_job(self) -> None:
        for provider in WAITING_TARGETS:
            with self.subTest(provider=provider):
                result, job_ids = self.refresh(provider)

                self.assertEqual("completed", result["status"])
                self.flow.inline_refreshes[provider].refresh.assert_called_once()
                self.assertEqual(([], []), (queued_jobs(self.flow), job_ids))


if __name__ == "__main__":
    unittest.main()
