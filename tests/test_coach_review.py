"""Fresh-state regressions for Coach actions and recoverable outcomes."""
import json
import unittest
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import Mock, patch
import test_server as fixtures
from backend.planning import workouts as planning_workouts
from backend.coach.proposals import COACH_ACTION_TTL_SECONDS, prune_expired_coach_proposals
from backend.coach.authorization import coach_session_key
from backend.sync.intervals import IntervalsSyncService
from backend.sync.intervals_lock import INTERVALS_SYNC_LOCK
from support import reset_application_state

server = fixtures.server


class CoachReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coach-review-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, value in (("CONFIG",replace(server.CONFIG,app_password="")),("DATA_DIR",root),("DB_PATH",root/"test.db"),("LOG_PATH",root/"test.log")):
            context=patch.object(server,name,value);context.start();self.addCleanup(context.stop)
        server.initialise_database()
        reset_application_state(server)

    def intent(self, operation, scope, follow=()):
        return {"intent": "local_action", "operation": operation, "target_system": "local", "artifact_id": None, "ambiguities": [], "authorization_scope": list(scope), "follow_up_operations": list(follow)}

    def call(self, name, arguments, call_id="call-1"):
        return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(arguments)}

    def history_preview(self, change_id, session_csrf_hash="review-session"):
        preview = server.history_undo_service().preview(change_id)
        proposal = server.coach_proposal_creation_service().create(
            preview.pop("proposal"), session_csrf_hash
        )
        return {**preview, "proposed_action": proposal["proposed_action"]}


    def workout(self, offset=0, sport="Run"):
        return {"date": (date.today() + timedelta(days=50+offset)).isoformat(), "sport": sport, "name": "Synthetic session", "description": "- 30m 60% Easy session", "duration_minutes": 30, "target": "AUTO"}


    def test_waited_full_refresh_preserves_all_time_window(self):
        server.set_kv("last_sync_at", "old-sync")
        server.set_kv("last_sync_activity_days", str(server.ALL_SYNC_DAYS))
        previous_sync_read = threading.Event()
        service = server.intervals_sync_service()
        original_get_value = service._status.get
        INTERVALS_SYNC_LOCK.acquire()

        def observe_previous_sync_read(key):
            value = original_get_value(key)
            if key == "last_sync_at" and threading.current_thread() is threading.main_thread():
                previous_sync_read.set()
            return value

        def finish_active_sync():
            try:
                previous_sync_read.wait(timeout=2)
                server.set_kv("last_sync_at", "new-sync")
            finally:
                INTERVALS_SYNC_LOCK.release()

        worker = threading.Thread(target=finish_active_sync)
        worker.start()
        try:
            with patch.object(service._status, "get", side_effect=observe_previous_sync_read):
                result = service.sync(
                    "full refresh test",
                    activity_days=server.ALL_SYNC_DAYS,
                    wait_for_existing=True,
                )
        finally:
            worker.join(timeout=2)
            if INTERVALS_SYNC_LOCK.locked():
                INTERVALS_SYNC_LOCK.release()
        self.assertEqual(result["activity_days"], server.ALL_SYNC_DAYS)


    def test_synchronous_refresh_rejects_windows_beyond_job_limit(self):
        intent = {**self.intent("start_provider_refresh", ["intervals_refresh"]), "intent": "remote_sync", "target_system": "intervals"}
        kwargs = {
            "intent": intent,
            "conversation_id": "wide-sync-validation",
            "client_turn_id": "wide-sync-validation",
            "session_csrf_hash": "review-session",
            "sync_job_ids": [],
        }
        with patch.object(IntervalsSyncService, "sync") as sync:
            with self.assertRaises(server.AppError) as error:
                server._structured_coach_tool_result(
                    "start_provider_refresh",
                    {"days": 3661, "_wait_for_completion": True},
                    **kwargs,
                )
        self.assertEqual(error.exception.reason, "invalid_refresh_request")
        sync.assert_not_called()

    def test_synchronous_refresh_retries_after_waiting_for_narrower_sync(self):
        intent = {**self.intent("start_provider_refresh", ["intervals_refresh"]), "intent": "remote_sync", "target_system": "intervals"}
        kwargs = {
            "intent": intent,
            "conversation_id": "wide-sync-retry",
            "client_turn_id": "wide-sync-retry",
            "session_csrf_hash": "review-session",
            "sync_job_ids": [],
        }
        with patch.object(
            IntervalsSyncService,
            "sync",
            side_effect=[{"status": "ok", "waited_for_existing": True, "activity_days": 3}, {"status": "ok", "activity_days": 365}],
        ) as sync:
            result = server._structured_coach_tool_result(
                "start_provider_refresh",
                {"days": 365, "_wait_for_completion": True},
                **kwargs,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["activity_days"], 365)
        self.assertEqual(sync.call_count, 2)
        self.assertFalse(sync.call_args_list[1].kwargs["wait_for_existing"])


    def test_resumed_effect_is_preserved_but_incomplete_summary_is_partial(self):
        csrf_hash = server.session_auth_service().session_token_hash("csrf-summary-recovery")
        client_turn_id = "summary-recovery"
        intent = self.intent("manage_training_templates", ["local_template"])
        message = "Speichere die Vorlage und erstelle einen Trainingsplan fuer die naechsten acht Wochen."
        server.coach_job_submission_service().enqueue(message, client_turn_id, csrf_hash, operation_id="summary-recovery-op")
        persisted_receipt = {
            "mode": "background", "phase": "preparing", "session_key": coach_session_key(csrf_hash),
            "command_receipts": [{
                "call_id": "template-success", "tool": "manage_training_templates", "effect_key": "template-success",
                "result": {"ok": True, "status": "completed"},
            }],
        }
        with server.DB_LOCK, server.database() as db:
            db.execute(
                "UPDATE coach_commands SET intent=?, receipt=? WHERE client_turn_id=?",
                (json.dumps(intent), json.dumps(persisted_receipt), client_turn_id),
            )
        with patch.object(server, "coach_conversation_provision_service", return_value=Mock(ensure=Mock(return_value="summary-recovery-conversation"))), patch(
            "backend.coach.context.CoachTrainingContextService.build", return_value="Synthetic summary context"
        ), patch.object(
            server, "responses_background_request", side_effect=server.AppError(503, "Model unavailable")
        ):
            result = server.chat_with_coach(
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
        entries = server.local_plan_creation_service().save([self.workout(i, sport) for i, sport in enumerate(sports)])
        self.assertEqual([entry["sport"] for entry in entries], sports)
        self.assertEqual([entry["type"] for entry in entries], sports)
        self.assertEqual([entry["sport"] for entry in sorted(server.planned_unit_service().list(), key=lambda x:x["date"])], sports)
        self.assertEqual(
            [
                planning_workouts.workout_event_payload(
                    entry["id"], entry, today=server.local_now().date()
                )["type"]
                for entry in entries
            ],
            sports,
        )

    def test_artifact_commits_complete_bounded_plan_and_replays_without_duplicates(self):
        for count in (28, 29, 56, 366):
            with self.subTest(count=count):
                self.setUp()
                payload = {"plan_name": "Synthetic plan", "workouts": [self.workout(i) for i in range(count)]}
                artifact = server.training_plan_artifact_service().stage(
                    {"payload": payload}, "review-conversation", "stage"
                )
                intent = self.intent("commit_training_plan", ["artifact:"+artifact["artifact_id"]]); intent["artifact_id"] = artifact["artifact_id"]
                kwargs = dict(intent=intent, conversation_id="review-conversation", client_turn_id="commit", session_csrf_hash="review-session", sync_job_ids=[])
                result = server._structured_coach_tool_result("commit_training_plan", {"artifact_id":artifact["artifact_id"]}, **kwargs)
                replay = server._structured_coach_tool_result("commit_training_plan", {"artifact_id":artifact["artifact_id"]}, **kwargs)
                self.assertEqual(len(result["library_entry_ids"]),count)
                self.assertEqual(len(server.planned_unit_service().list(1000)),count)
                self.assertEqual(replay["status"],"already_applied")

    def test_artifact_late_failure_rolls_back_entire_plan_and_revision(self):
        workouts = [self.workout(i) for i in range(56)]
        artifact = server.training_plan_artifact_service().stage(
            {"payload": {"workouts": workouts, "plan_name": "Atomic"}},
            "review-conversation",
            "stage",
        )
        workouts[-1]["date"] = workouts[0]["date"]
        with server.database() as db:
            db.execute(
                "UPDATE coach_plan_artifacts SET payload=? WHERE id=?",
                (json.dumps({"workouts": workouts, "plan_name": "Atomic"}), artifact["artifact_id"]),
            )
        intent=self.intent("commit_training_plan",["artifact:"+artifact["artifact_id"]]);intent["artifact_id"]=artifact["artifact_id"]
        with self.assertRaises(server.AppError):
            server._structured_coach_tool_result("commit_training_plan",{"artifact_id":artifact["artifact_id"]},intent=intent,conversation_id="review-conversation",client_turn_id="commit",session_csrf_hash="review-session",sync_job_ids=[])
        self.assertEqual(server.planned_unit_service().list(),[])
        self.assertEqual(server.training_plan_service().list(),[])
        with server.database() as db:self.assertEqual(db.execute("SELECT status FROM coach_plan_artifacts WHERE id=?",(artifact["artifact_id"],)).fetchone()["status"],"draft")

    def test_plan_draft_rejects_an_occupied_date_before_storing_artifact(self):
        workout = self.workout()
        server.planned_unit_service().create(workout)
        intent = self.intent("stage_training_plan", ["local_plan"], ("commit_training_plan",))
        with self.assertRaises(server.AppError) as error:
            server._structured_coach_tool_result(
                "stage_training_plan", {"payload": {"plan_name": "Conflict", "goal": "Base", "workouts": [workout]}},
                intent=intent, conversation_id="review-conversation", client_turn_id="conflict",
                session_csrf_hash="review-session", sync_job_ids=[],
            )
        self.assertEqual(error.exception.reason, "plan_date_conflict")
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM coach_plan_artifacts").fetchone()["n"], 0)


    def test_template_batch_invalid_second_or_last_has_no_partial_writes(self):
        for position in (1,2):
            with self.subTest(position=position):
                templates=[{"name":"Synthetic template","sport":"Run","duration_minutes":30} for _ in range(3)]
                templates[position]["duration_minutes"]="invalid"
                with self.assertRaises(server.AppError):
                    server._structured_coach_tool_result("manage_training_templates",{"templates":templates},intent=self.intent("manage_training_templates",["local_template"]),conversation_id="review-conversation",client_turn_id="batch",session_csrf_hash="review-session",sync_job_ids=[])
                self.assertEqual(server.workout_library_service().list(),[])


    def test_created_refresh_job_is_readable_only_by_own_turn(self):
        intent={**self.intent("start_provider_refresh",["garmin_refresh"],("get_sync_job",)),"intent":"remote_sync","target_system":"garmin"}
        ids=[];kwargs=dict(intent=intent,conversation_id="review-conversation",client_turn_id="refresh",session_csrf_hash="review-session",sync_job_ids=ids)
        job=server._structured_coach_tool_result("start_provider_refresh",{},**kwargs)
        status=server._structured_coach_tool_result("get_sync_job",{"job_id":job["sync_job_id"]},**kwargs)
        self.assertEqual(status["job"]["id"],job["sync_job_id"])
        with self.assertRaises(server.AppError):server._structured_coach_tool_result("get_sync_job",{"job_id":job["sync_job_id"]},**{**kwargs,"sync_job_ids":[]})


    def test_running_foreign_command_is_neither_executed_nor_closed(self):
        identity = {"session_key": coach_session_key("owner"), "status": "running"}
        with server.database() as db:
            db.execute("INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) VALUES ('foreign', 'foreign', 'review-conversation', '{}', 'local', 'running', ?, ?, ?)", (json.dumps(identity), server.utc_now(), server.utc_now()))
        with self.assertRaises(server.AppError) as error:
            server._chat_with_structured_coach("Edit", intent=self.intent("save_checkin", ["local_checkin"]), conversation_id="review-conversation", client_turn_id="foreign", session_csrf_hash="intruder")
        self.assertEqual(error.exception.status, 403)
        with server.database() as db:
            self.assertEqual(db.execute("SELECT status FROM coach_commands WHERE client_turn_id='foreign'").fetchone()["status"], "running")


    def test_current_undo_token_enforces_session_hash_expiry_and_competing_execution(self):
        template = server.workout_library_service().create_template({"name": "Protected synthetic", "sport": "Run", "description": "- 30m 60%", "duration_minutes": 30})
        change = next(row for row in server.change_history_service().list() if row["entity_id"] == template["id"])
        proposal = self.history_preview(change["id"])["proposed_action"]
        with self.assertRaises(server.AppError):
            server.coach_proposal_confirmation_service().confirm(proposal["id"], "other-session")
        confirmed = server.coach_proposal_confirmation_service().confirm(proposal["id"], "review-session")
        token = confirmed["action_token"]
        with self.assertRaises(server.AppError):
            server.coach_proposal_execution_service().execute(token, "other-session", proposal["payload_hash"])
        with self.assertRaises(server.AppError):
            server.coach_proposal_execution_service().execute(token, "review-session", "0" * 64)
        self.assertEqual(len(server.workout_library_service().list()), 1)
        barrier = threading.Barrier(2)

        def execute():
            barrier.wait(timeout=5)
            try:
                server.coach_proposal_execution_service().execute(token, "review-session", proposal["payload_hash"])
                return "applied"
            except server.AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: execute(), range(2)))
        self.assertCountEqual(results, ["applied", "rejected"])
        self.assertEqual(server.workout_library_service().list(), [])
        template = server.workout_library_service().create_template({"name": "Expiry synthetic", "sport": "Run", "description": "- 30m 60%", "duration_minutes": 30})
        change = next(row for row in server.change_history_service().list() if row["entity_id"] == template["id"])
        proposal = self.history_preview(change["id"])["proposed_action"]
        confirmed = server.coach_proposal_confirmation_service().confirm(proposal["id"], "review-session")
        with patch.object(server.time, "time", return_value=time.time() + COACH_ACTION_TTL_SECONDS + 1):
            with self.assertRaises(server.AppError):
                server.coach_proposal_execution_service().execute(confirmed["action_token"], "review-session", proposal["payload_hash"])
        self.assertEqual(len(server.workout_library_service().list()), 1)

    def test_reload_preserves_pending_undo_but_changed_target_rejects_application(self):
        template = server.workout_library_service().create_template({"name": "Synthetic original", "sport": "Run", "description": "- 30m 60%", "duration_minutes": 30})
        change = next(row for row in server.change_history_service().list() if row["entity_id"] == template["id"])
        proposal = self.history_preview(change["id"])["proposed_action"]
        history = server.chat_history_page_service().page(
            session_csrf_hash="review-session"
        )
        self.assertEqual(history["proposed_actions"][0]["id"], proposal["id"])
        self.assertEqual(
            server.chat_history_page_service()
            .page(session_csrf_hash="other-session")["proposed_actions"],
            [],
        )
        server.workout_library_service().update(template["id"], {"action": "update", "name": "Synthetic changed"})
        confirmed = server.coach_proposal_confirmation_service().confirm(proposal["id"], "review-session")
        with self.assertRaises(server.AppError):
            server.coach_proposal_execution_service().execute(confirmed["action_token"], "review-session", proposal["payload_hash"])
        self.assertEqual(server.workout_library_service().list()[0]["name"], "Synthetic changed")

    def test_adaptive_apply_after_day_change_preserves_now_past_unit(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        planned = server.local_plan_creation_service().save([{**self.workout(), "date": tomorrow, "description": "- 60m 60%", "duration_minutes": 60}])[0]
        server.checkin_service().save({"soreness": 8})
        preview = server.adaptive_replan_preview_service().preview()
        self.assertTrue(preview["changes"])
        advanced = server.local_now() + timedelta(days=2)
        with patch.object(server, "local_now", return_value=advanced):
            applied = server.illness_pause_sync_service().apply(preview["id"])
        self.assertEqual(applied["status"], "stale")
        self.assertEqual(applied["updated"], 0)
        self.assertEqual(applied["stale"][0]["reason"], "past")
        self.assertEqual(server.planned_unit_service().list()[0]["duration_minutes"], planned["duration_minutes"])

    def test_expired_proposal_gc_and_confirmation_serialize_without_losing_drafts(self):
        template = server.workout_library_service().create_template({"name": "GC synthetic", "sport": "Run", "description": "- 30m 60%", "duration_minutes": 30})
        change = next(row for row in server.change_history_service().list() if row["entity_id"] == template["id"])
        expired = self.history_preview(change["id"])["proposed_action"]
        active = self.history_preview(change["id"])["proposed_action"]
        draft = server.training_plan_artifact_service().stage(
            {"payload": {"workouts": [self.workout()]}},
            "review-conversation",
            "draft",
        )
        with server.database() as db:
            db.execute("UPDATE coach_action_proposals SET expires_at=? WHERE id=?", (time.time() - 1, expired["id"]))
        barrier = threading.Barrier(2)

        def collect():
            barrier.wait(timeout=5)
            with server.DB_LOCK, server.database() as db:
                return prune_expired_coach_proposals(db, time.time())

        def confirm():
            barrier.wait(timeout=5)
            try:
                server.coach_proposal_confirmation_service().confirm(expired["id"], "review-session")
                return "accepted"
            except server.AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            gc_result, confirmation = executor.submit(collect), executor.submit(confirm)
            self.assertEqual(gc_result.result(), 1)
            self.assertEqual(confirmation.result(), "rejected")
        self.assertEqual([item["id"] for item in server.coach_proposal_read_service().current("review-session")], [active["id"]])
        with server.database() as db:
            self.assertEqual(db.execute("SELECT status FROM coach_plan_artifacts WHERE id=?", (draft["artifact_id"],)).fetchone()["status"], "draft")


    def test_explicit_reconfirmation_after_reload_rotates_only_unused_token(self):
        template = server.workout_library_service().create_template({"name": "Token recovery", "sport": "Run", "description": "- 30m 60%", "duration_minutes": 30})
        change = next(row for row in server.change_history_service().list() if row["entity_id"] == template["id"])
        proposal = self.history_preview(change["id"])["proposed_action"]
        first = server.coach_proposal_confirmation_service().confirm(proposal["id"], "review-session")
        self.assertEqual(server.coach_proposal_read_service().current("review-session")[0]["status"], "ready")
        second = server.coach_proposal_confirmation_service().confirm(proposal["id"], "review-session")
        with self.assertRaises(server.AppError):
            server.coach_proposal_execution_service().execute(first["action_token"], "review-session", proposal["payload_hash"])
        server.coach_proposal_execution_service().execute(second["action_token"], "review-session", proposal["payload_hash"])
        with self.assertRaises(server.AppError):
            server.coach_proposal_confirmation_service().confirm(proposal["id"], "review-session")
        self.assertEqual(server.workout_library_service().list(), [])
