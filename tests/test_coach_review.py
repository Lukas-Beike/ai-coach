"""Fresh-state regressions for Coach actions and recoverable outcomes."""

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import server_test_support as fixtures
from support import reset_application_state

from backend.coach.authorization import coach_session_key
from backend.coach.proposal_models import (
    COACH_ACTION_TTL_SECONDS,
    prune_expired_coach_proposals,
)
from backend.errors import AppError
from backend.planning import workouts as planning_workouts
from backend.runtime import clock as runtime_clock

server = fixtures.server


class CoachReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coach-review-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, value in (
            ("CONFIG", replace(server.CONFIG, app_password="")),
            ("DATA_DIR", root),
            ("DB_PATH", root / "test.db"),
            ("LOG_PATH", root / "test.log"),
        ):
            context = patch.object(server, name, value)
            context.start()
            self.addCleanup(context.stop)
        server.initialise_database()
        reset_application_state(server)

    def intent(self, operation, scope, follow=()):
        return {
            "intent": "local_action",
            "operation": operation,
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": list(scope),
            "follow_up_operations": list(follow),
        }

    def call(self, name, arguments, call_id="call-1"):
        return {
            "type": "function_call",
            "name": name,
            "call_id": call_id,
            "arguments": json.dumps(arguments),
        }

    def history_preview(self, change_id, session_csrf_hash="review-session"):
        preview = server.HISTORY.undo_service().preview(change_id)
        proposal = server.COACH_PROPOSALS.creation_service().create(
            preview.pop("proposal"), session_csrf_hash
        )
        return {**preview, "proposed_action": proposal["proposed_action"]}

    def workout(self, offset=0, sport="Run"):
        return {
            "date": (
                server.ATHLETE_CLOCK.now().date() + timedelta(days=50 + offset)
            ).isoformat(),
            "sport": sport,
            "name": "Synthetic session",
            "description": "- 30m 60% Easy session",
            "duration_minutes": 30,
            "target": "AUTO",
        }

    def test_resumed_effect_is_preserved_but_incomplete_summary_is_partial(self):
        csrf_hash = server.session_auth_service().session_token_hash(
            "csrf-summary-recovery"
        )
        client_turn_id = "summary-recovery"
        intent = self.intent("manage_training_templates", ["local_template"])
        message = "Speichere die Vorlage und erstelle einen Trainingsplan fuer die naechsten acht Wochen."
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            message, client_turn_id, csrf_hash, operation_id="summary-recovery-op"
        )
        persisted_receipt = {
            "mode": "background",
            "phase": "preparing",
            "session_key": coach_session_key(csrf_hash),
            "command_receipts": [
                {
                    "call_id": "template-success",
                    "tool": "manage_training_templates",
                    "effect_key": "template-success",
                    "result": {"ok": True, "status": "completed"},
                }
            ],
        }
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE coach_commands SET intent=?, receipt=? WHERE client_turn_id=?",
                (json.dumps(intent), json.dumps(persisted_receipt), client_turn_id),
            )
        with (
            fixtures.patch_coach_conversation(
                "provision_service",
                return_value=Mock(
                    binding=Mock(return_value="summary-recovery-conversation")
                ),
            ),
            patch(
                "backend.coach.context.CoachTrainingContextService.build",
                return_value="Synthetic summary context",
            ),
            fixtures.patch_coach_conversation(
                "response_transport"
            ) as transport_factory,
        ):
            transport_factory.return_value.stream_request.side_effect = AppError(
                503, "Model unavailable"
            )
            result = server.COACH_TURNS.chat_turn_service().run(
                message,
                client_turn_id=client_turn_id,
                session_csrf_hash=csrf_hash,
                background_job=True,
            )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pending_operations"], [])
        self.assertIn("Bereits erfolgreich", result["message"]["content"])

    def test_plan_sport_survives_storage_and_provider_projection(self):
        sports = ["Run", "Swim", "WeightTraining", "VirtualRide", "Ride"]
        entries = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [self.workout(i, sport) for i, sport in enumerate(sports)]
        )
        stored = ["run", "swim", "strength", "ride", "ride"]
        environments = ["unknown", "unknown", "unknown", "virtual", "unknown"]
        self.assertEqual([entry["sport"] for entry in entries], stored)
        self.assertEqual([entry["environment"] for entry in entries], environments)
        self.assertTrue(all("type" not in entry for entry in entries))
        self.assertEqual(
            [
                entry["sport"]
                for entry in sorted(
                    server.PLANNING_DATA.planned_unit().list(), key=lambda x: x["date"]
                )
            ],
            stored,
        )
        self.assertEqual(
            [
                planning_workouts.workout_event_payload(
                    entry["id"], entry, today=server.ATHLETE_CLOCK.now().date()
                )["type"]
                for entry in entries
            ],
            sports,
        )

    def test_artifact_commits_complete_bounded_plan_and_replays_without_duplicates(
        self,
    ):
        for count in (28, 29, 56, 366):
            with self.subTest(count=count):
                self.setUp()
                payload = {
                    "plan_name": "Synthetic plan",
                    "workouts": [self.workout(i) for i in range(count)],
                }
                artifact = (
                    server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
                        {"payload": payload}, "review-conversation", "stage"
                    )
                )
                intent = self.intent(
                    "commit_training_plan", ["artifact:" + artifact["artifact_id"]]
                )
                intent["artifact_id"] = artifact["artifact_id"]
                kwargs = {
                    "intent": intent,
                    "conversation_id": "review-conversation",
                    "client_turn_id": "commit",
                    "session_csrf_hash": "review-session",
                    "sync_job_ids": [],
                }
                result = server.COACH_TOOL_DISPATCH.service().execute(
                    "commit_training_plan",
                    {"artifact_id": artifact["artifact_id"]},
                    **kwargs,
                )
                replay = server.COACH_TOOL_DISPATCH.service().execute(
                    "commit_training_plan",
                    {"artifact_id": artifact["artifact_id"]},
                    **kwargs,
                )
                self.assertEqual(len(result["library_entry_ids"]), count)
                self.assertEqual(
                    len(server.PLANNING_DATA.planned_unit().list(1000)), count
                )
                self.assertEqual(replay["status"], "already_applied")

    def test_artifact_late_failure_rolls_back_entire_plan_and_revision(self):
        workouts = [self.workout(i) for i in range(56)]
        artifact = server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
            {"payload": {"workouts": workouts, "plan_name": "Atomic"}},
            "review-conversation",
            "stage",
        )
        workouts[-1]["date"] = workouts[0]["date"]
        workouts[-1]["starts_at_local"] = workouts[0]["date"] + "T08:00:00"
        workouts[-1]["duration_minutes"] = 60
        workouts[0]["starts_at_local"] = workouts[0]["date"] + "T08:30:00"
        workouts[0]["duration_minutes"] = 30
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE coach_plan_artifacts SET payload=? WHERE id=?",
                (
                    json.dumps({"workouts": workouts, "plan_name": "Atomic"}),
                    artifact["artifact_id"],
                ),
            )
        intent = self.intent(
            "commit_training_plan", ["artifact:" + artifact["artifact_id"]]
        )
        intent["artifact_id"] = artifact["artifact_id"]
        with self.assertRaises(AppError):
            server.COACH_TOOL_DISPATCH.service().execute(
                "commit_training_plan",
                {"artifact_id": artifact["artifact_id"]},
                intent=intent,
                conversation_id="review-conversation",
                client_turn_id="commit",
                session_csrf_hash="review-session",
                sync_job_ids=[],
            )
        self.assertEqual(server.PLANNING_DATA.planned_unit().list(), [])
        self.assertEqual(server.PLANNING_DATA.training_plan().list(), [])
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(
                db.execute(
                    "SELECT status FROM coach_plan_artifacts WHERE id=?",
                    (artifact["artifact_id"],),
                ).fetchone()["status"],
                "draft",
            )

    def test_plan_draft_rejects_an_occupied_date_before_storing_artifact(self):
        workout = self.workout()
        server.PLANNING_DATA.competition().save(
            {"name": "Race", "event_date": workout["date"], "sport": "Ride"}
        )
        intent = self.intent(
            "stage_training_plan", ["local_plan"], ("commit_training_plan",)
        )
        with self.assertRaises(AppError) as error:
            server.COACH_TOOL_DISPATCH.service().execute(
                "stage_training_plan",
                {
                    "payload": {
                        "plan_name": "Conflict",
                        "goal": "Base",
                        "workouts": [workout],
                    }
                },
                intent=intent,
                conversation_id="review-conversation",
                client_turn_id="conflict",
                session_csrf_hash="review-session",
                sync_job_ids=[],
            )
        self.assertEqual(error.exception.reason, "plan_date_conflict")
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS n FROM coach_plan_artifacts").fetchone()[
                    "n"
                ],
                0,
            )

    def test_template_batch_invalid_second_or_last_has_no_partial_writes(self):
        for position in (1, 2):
            with self.subTest(position=position):
                templates = [
                    {
                        "name": "Synthetic template",
                        "sport": "Run",
                        "duration_minutes": 30,
                    }
                    for _ in range(3)
                ]
                templates[position]["duration_minutes"] = "invalid"
                with self.assertRaises(AppError):
                    server.COACH_TOOL_DISPATCH.service().execute(
                        "manage_training_templates",
                        {"templates": templates},
                        intent=self.intent(
                            "manage_training_templates", ["local_template"]
                        ),
                        conversation_id="review-conversation",
                        client_turn_id="batch",
                        session_csrf_hash="review-session",
                        sync_job_ids=[],
                    )
                self.assertEqual(server.PLANNING_DATA.workout_library().list(), [])

    def test_created_refresh_job_is_readable_only_by_own_turn(self):
        intent = {
            **self.intent(
                "start_provider_refresh", ["garmin_refresh"], ("get_sync_job",)
            ),
            "intent": "remote_sync",
            "target_system": "garmin",
        }
        ids = []
        kwargs = {
            "intent": intent,
            "conversation_id": "review-conversation",
            "client_turn_id": "refresh",
            "session_csrf_hash": "review-session",
            "sync_job_ids": ids,
        }
        job = server.COACH_TOOL_DISPATCH.service().execute(
            "start_provider_refresh", {}, **kwargs
        )
        status = server.COACH_TOOL_DISPATCH.service().execute(
            "get_sync_job", {"job_id": job["sync_job_id"]}, **kwargs
        )
        self.assertEqual(status["job"]["id"], job["sync_job_id"])
        with self.assertRaises(AppError):
            server.COACH_TOOL_DISPATCH.service().execute(
                "get_sync_job",
                {"job_id": job["sync_job_id"]},
                **{**kwargs, "sync_job_ids": []},
            )

    def test_running_foreign_command_is_neither_executed_nor_closed(self):
        identity = {"session_key": coach_session_key("owner"), "status": "running"}
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) VALUES ('foreign', 'foreign', 'review-conversation', '{}', 'local', 'running', ?, ?, ?)",
                (
                    json.dumps(identity),
                    runtime_clock.utc_now(),
                    runtime_clock.utc_now(),
                ),
            )
        with self.assertRaises(AppError) as error:
            server.COACH_TURNS.structured_turn_service().run(
                "Edit",
                intent=self.intent("save_checkin", ["local_checkin"]),
                conversation_id="review-conversation",
                client_turn_id="foreign",
                session_csrf_hash="intruder",
            )
        self.assertEqual(error.exception.status, 403)
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(
                db.execute(
                    "SELECT status FROM coach_commands WHERE client_turn_id='foreign'"
                ).fetchone()["status"],
                "running",
            )

    def test_current_undo_token_enforces_session_hash_expiry_and_competing_execution(
        self,
    ):
        template = server.PLANNING_DATA.workout_library().create_template(
            {
                "name": "Protected synthetic",
                "sport": "Run",
                "description": "- 30m 60%",
                "duration_minutes": 30,
            }
        )
        change = next(
            row
            for row in server.HISTORY.change_history_service().list()
            if row["entity_id"] == template["id"]
        )
        proposal = self.history_preview(change["id"])["proposed_action"]
        with self.assertRaises(AppError):
            server.COACH_PROPOSALS.confirmation_service().confirm(
                proposal["id"], "other-session"
            )
        confirmed = server.COACH_PROPOSALS.confirmation_service().confirm(
            proposal["id"], "review-session"
        )
        token = confirmed["action_token"]
        with self.assertRaises(AppError):
            server.COACH_PROPOSALS.execution_service().execute(
                token, "other-session", proposal["payload_hash"]
            )
        with self.assertRaises(AppError):
            server.COACH_PROPOSALS.execution_service().execute(
                token, "review-session", "0" * 64
            )
        self.assertEqual(len(server.PLANNING_DATA.workout_library().list()), 1)
        barrier = threading.Barrier(2)

        def execute():
            barrier.wait(timeout=5)
            try:
                server.COACH_PROPOSALS.execution_service().execute(
                    token, "review-session", proposal["payload_hash"]
                )
                return "applied"
            except AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: execute(), range(2)))
        self.assertCountEqual(results, ["applied", "rejected"])
        self.assertEqual(server.PLANNING_DATA.workout_library().list(), [])
        template = server.PLANNING_DATA.workout_library().create_template(
            {
                "name": "Expiry synthetic",
                "sport": "Run",
                "description": "- 30m 60%",
                "duration_minutes": 30,
            }
        )
        change = next(
            row
            for row in server.HISTORY.change_history_service().list()
            if row["entity_id"] == template["id"]
        )
        proposal = self.history_preview(change["id"])["proposed_action"]
        confirmed = server.COACH_PROPOSALS.confirmation_service().confirm(
            proposal["id"], "review-session"
        )
        with (
            patch.object(
                time,
                "time",
                return_value=time.time() + COACH_ACTION_TTL_SECONDS + 1,
            ),
            self.assertRaises(AppError),
        ):
            server.COACH_PROPOSALS.execution_service().execute(
                confirmed["action_token"], "review-session", proposal["payload_hash"]
            )
        self.assertEqual(len(server.PLANNING_DATA.workout_library().list()), 1)

    def test_reload_preserves_pending_undo_but_changed_target_rejects_application(self):
        template = server.PLANNING_DATA.workout_library().create_template(
            {
                "name": "Synthetic original",
                "sport": "Run",
                "description": "- 30m 60%",
                "duration_minutes": 30,
            }
        )
        change = next(
            row
            for row in server.HISTORY.change_history_service().list()
            if row["entity_id"] == template["id"]
        )
        proposal = self.history_preview(change["id"])["proposed_action"]
        history = server.HTTP_API.chat_history_page_service().page(
            session_csrf_hash="review-session"
        )
        self.assertEqual(history["proposed_actions"][0]["id"], proposal["id"])
        self.assertEqual(
            server.HTTP_API.chat_history_page_service().page(
                session_csrf_hash="other-session"
            )["proposed_actions"],
            [],
        )
        server.PLANNING_DATA.workout_library().update(
            template["id"], {"action": "update", "name": "Synthetic changed"}
        )
        confirmed = server.COACH_PROPOSALS.confirmation_service().confirm(
            proposal["id"], "review-session"
        )
        with self.assertRaises(AppError):
            server.COACH_PROPOSALS.execution_service().execute(
                confirmed["action_token"], "review-session", proposal["payload_hash"]
            )
        self.assertEqual(
            server.PLANNING_DATA.workout_library().list()[0]["name"],
            "Synthetic changed",
        )

    def test_adaptive_apply_after_day_change_preserves_now_past_unit(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        planned = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [
                {
                    **self.workout(),
                    "date": today,
                    "description": "- 60m 60%",
                    "duration_minutes": 60,
                }
            ]
        )[0]
        server.ATHLETE_DATA.checkin().save({"soreness": 8})
        preview = server.PLANNING_WORKFLOWS.adaptive_replan_preview_service().preview()
        self.assertTrue(preview["changes"])
        advanced = server.ATHLETE_CLOCK.now() + timedelta(days=2)
        with patch.object(server.ATHLETE_CLOCK, "now", return_value=advanced):
            applied = server.SYNC_COMMANDS.illness_pause().apply(preview["id"])
        self.assertEqual(applied["status"], "stale")
        self.assertEqual(applied["updated"], 0)
        self.assertEqual(applied["stale"][0]["reason"], "past")
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list()[0]["duration_minutes"],
            planned["duration_minutes"],
        )

    def test_expired_proposal_gc_and_confirmation_serialize_without_losing_drafts(self):
        template = server.PLANNING_DATA.workout_library().create_template(
            {
                "name": "GC synthetic",
                "sport": "Run",
                "description": "- 30m 60%",
                "duration_minutes": 30,
            }
        )
        change = next(
            row
            for row in server.HISTORY.change_history_service().list()
            if row["entity_id"] == template["id"]
        )
        expired = self.history_preview(change["id"])["proposed_action"]
        active = self.history_preview(change["id"])["proposed_action"]
        draft = server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
            {"payload": {"workouts": [self.workout()]}},
            "review-conversation",
            "draft",
        )
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE coach_action_proposals SET expires_at=? WHERE id=?",
                (time.time() - 1, expired["id"]),
            )
        barrier = threading.Barrier(2)

        def collect():
            barrier.wait(timeout=5)
            with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                return prune_expired_coach_proposals(db, time.time())

        def confirm():
            barrier.wait(timeout=5)
            try:
                server.COACH_PROPOSALS.confirmation_service().confirm(
                    expired["id"], "review-session"
                )
                return "accepted"
            except AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            gc_result, confirmation = executor.submit(collect), executor.submit(confirm)
            self.assertEqual(gc_result.result(), 1)
            self.assertEqual(confirmation.result(), "rejected")
        self.assertEqual(
            [
                item["id"]
                for item in server.COACH_PROPOSALS.read_service().current(
                    "review-session"
                )
            ],
            [active["id"]],
        )
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(
                db.execute(
                    "SELECT status FROM coach_plan_artifacts WHERE id=?",
                    (draft["artifact_id"],),
                ).fetchone()["status"],
                "draft",
            )

    def test_explicit_reconfirmation_after_reload_rotates_only_unused_token(self):
        template = server.PLANNING_DATA.workout_library().create_template(
            {
                "name": "Token recovery",
                "sport": "Run",
                "description": "- 30m 60%",
                "duration_minutes": 30,
            }
        )
        change = next(
            row
            for row in server.HISTORY.change_history_service().list()
            if row["entity_id"] == template["id"]
        )
        proposal = self.history_preview(change["id"])["proposed_action"]
        first = server.COACH_PROPOSALS.confirmation_service().confirm(
            proposal["id"], "review-session"
        )
        self.assertEqual(
            server.COACH_PROPOSALS.read_service().current("review-session")[0][
                "status"
            ],
            "ready",
        )
        second = server.COACH_PROPOSALS.confirmation_service().confirm(
            proposal["id"], "review-session"
        )
        with self.assertRaises(AppError):
            server.COACH_PROPOSALS.execution_service().execute(
                first["action_token"], "review-session", proposal["payload_hash"]
            )
        server.COACH_PROPOSALS.execution_service().execute(
            second["action_token"], "review-session", proposal["payload_hash"]
        )
        with self.assertRaises(AppError):
            server.COACH_PROPOSALS.confirmation_service().confirm(
                proposal["id"], "review-session"
            )
        self.assertEqual(server.PLANNING_DATA.workout_library().list(), [])
