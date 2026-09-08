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
from unittest.mock import patch
import test_server as fixtures

server = fixtures.server


class CoachReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coach-review-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, value in (("CONFIG",replace(server.CONFIG,app_password="")),("DATA_DIR",root),("DB_PATH",root/"test.db"),("LOG_PATH",root/"test.log")):
            context=patch.object(server,name,value);context.start();self.addCleanup(context.stop)
        server.initialise_database()
        fixtures.CoachTests.setUp(self)

    def intent(self, operation, scope, follow=()):
        return {"intent": "local_action", "operation": operation, "target_system": "local", "artifact_id": None, "ambiguities": [], "authorization_scope": list(scope), "follow_up_operations": list(follow)}

    def call(self, name, arguments, call_id="call-1"):
        return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(arguments)}


    def workout(self, offset=0, sport="Run"):
        return {"date": (date.today() + timedelta(days=50+offset)).isoformat(), "sport": sport, "name": "Synthetic session", "description": "Easy session", "duration_minutes": 30, "target": "AUTO"}


    def test_waited_full_refresh_preserves_all_time_window(self):
        server.set_kv("last_sync_at", "old-sync")
        server.set_kv("last_sync_activity_days", str(server.ALL_SYNC_DAYS))
        server.SYNC_LOCK.acquire()
        previous_sync_read = threading.Event()
        original_get_kv = server.get_kv

        def observe_previous_sync_read(key, db=None):
            value = original_get_kv(key, db)
            if key == "last_sync_at" and threading.current_thread() is threading.main_thread():
                previous_sync_read.set()
            return value

        def finish_active_sync():
            try:
                previous_sync_read.wait(timeout=2)
                server.set_kv("last_sync_at", "new-sync")
            finally:
                server.SYNC_LOCK.release()

        worker = threading.Thread(target=finish_active_sync)
        worker.start()
        try:
            with patch.object(server, "get_kv", side_effect=observe_previous_sync_read):
                result = server.sync_intervals("full refresh test", activity_days=server.ALL_SYNC_DAYS, wait_for_existing=True)
        finally:
            worker.join(timeout=2)
            if server.SYNC_LOCK.locked():
                server.SYNC_LOCK.release()
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
        with patch.object(server, "sync_intervals") as sync:
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
            server,
            "sync_intervals",
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
        csrf_hash = server.session_token_hash("csrf-summary-recovery")
        client_turn_id = "summary-recovery"
        intent = self.intent("manage_training_templates", ["local_template"])
        message = "Speichere die Vorlage und erstelle einen Trainingsplan fuer die naechsten acht Wochen."
        server.enqueue_background_coach_job(message, client_turn_id, csrf_hash, operation_id="summary-recovery-op")
        persisted_receipt = {
            "mode": "background", "phase": "preparing", "session_key": server._coach_session_key(csrf_hash),
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
        with patch.object(server, "ensure_conversation", return_value="summary-recovery-conversation"), patch.object(
            server, "build_training_context", return_value="Synthetic summary context"
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
        entries = server.save_workout_library_entries([self.workout(i, sport) for i, sport in enumerate(sports)])
        self.assertEqual([entry["sport"] for entry in entries], sports)
        self.assertEqual([entry["type"] for entry in entries], sports)
        self.assertEqual([entry["sport"] for entry in sorted(server.list_planned_units(), key=lambda x:x["date"])], sports)
        self.assertEqual([server.workout_event_payload(entry["id"], entry)["type"] for entry in entries], sports)

    def test_artifact_commits_complete_bounded_plan_and_replays_without_duplicates(self):
        for count in (28, 29, 56, 366):
            with self.subTest(count=count):
                self.setUp()
                payload = {"plan_name": "Synthetic plan", "workouts": [self.workout(i) for i in range(count)]}
                artifact = server._stage_coach_artifact("review-conversation", "stage", payload)
                intent = self.intent("commit_training_plan", ["artifact:"+artifact["artifact_id"]]); intent["artifact_id"] = artifact["artifact_id"]
                kwargs = dict(intent=intent, conversation_id="review-conversation", client_turn_id="commit", session_csrf_hash="review-session", sync_job_ids=[])
                result = server._structured_coach_tool_result("commit_training_plan", {"artifact_id":artifact["artifact_id"]}, **kwargs)
                replay = server._structured_coach_tool_result("commit_training_plan", {"artifact_id":artifact["artifact_id"]}, **kwargs)
                self.assertEqual(len(result["library_entry_ids"]),count)
                self.assertEqual(len(server.list_planned_units(1000)),count)
                self.assertEqual(replay["status"],"already_applied")

    def test_artifact_late_failure_rolls_back_entire_plan_and_revision(self):
        workouts=[self.workout(i) for i in range(56)];workouts[-1]["date"]=workouts[0]["date"]
        artifact=server._stage_coach_artifact("review-conversation","stage",{"workouts":workouts,"plan_name":"Atomic"})
        intent=self.intent("commit_training_plan",["artifact:"+artifact["artifact_id"]]);intent["artifact_id"]=artifact["artifact_id"]
        with self.assertRaises(server.AppError):
            server._structured_coach_tool_result("commit_training_plan",{"artifact_id":artifact["artifact_id"]},intent=intent,conversation_id="review-conversation",client_turn_id="commit",session_csrf_hash="review-session",sync_job_ids=[])
        self.assertEqual(server.list_planned_units(),[])
        self.assertEqual(server.list_training_plans(),[])
        with server.database() as db:self.assertEqual(db.execute("SELECT status FROM coach_plan_artifacts WHERE id=?",(artifact["artifact_id"],)).fetchone()["status"],"draft")

    def test_plan_draft_rejects_an_occupied_date_before_storing_artifact(self):
        workout = self.workout()
        server.create_local_planned_unit(workout)
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
                self.assertEqual(server.list_workout_library(),[])


    def test_created_refresh_job_is_readable_only_by_own_turn(self):
        intent={**self.intent("start_provider_refresh",["garmin_refresh"],("get_sync_job",)),"intent":"remote_sync","target_system":"garmin"}
        ids=[];kwargs=dict(intent=intent,conversation_id="review-conversation",client_turn_id="refresh",session_csrf_hash="review-session",sync_job_ids=ids)
        job=server._structured_coach_tool_result("start_provider_refresh",{},**kwargs)
        status=server._structured_coach_tool_result("get_sync_job",{"job_id":job["sync_job_id"]},**kwargs)
        self.assertEqual(status["job"]["id"],job["sync_job_id"])
        with self.assertRaises(server.AppError):server._structured_coach_tool_result("get_sync_job",{"job_id":job["sync_job_id"]},**{**kwargs,"sync_job_ids":[]})


    def test_running_foreign_command_is_neither_executed_nor_closed(self):
        identity = {"session_key": server._coach_session_key("owner"), "status": "running"}
        with server.database() as db:
            db.execute("INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) VALUES ('foreign', 'foreign', 'review-conversation', '{}', 'local', 'running', ?, ?, ?)", (json.dumps(identity), server.utc_now(), server.utc_now()))
        with self.assertRaises(server.AppError) as error:
            server._chat_with_structured_coach("Edit", intent=self.intent("save_checkin", ["local_checkin"]), conversation_id="review-conversation", client_turn_id="foreign", session_csrf_hash="intruder")
        self.assertEqual(error.exception.status, 403)
        with server.database() as db:
            self.assertEqual(db.execute("SELECT status FROM coach_commands WHERE client_turn_id='foreign'").fetchone()["status"], "running")


    def test_current_undo_token_enforces_session_hash_expiry_and_competing_execution(self):
        template = server.create_local_library_template({"name": "Protected synthetic", "sport": "Run"})
        change = next(row for row in server.list_change_history() if row["entity_id"] == template["id"])
        proposal = server._history_preview(change["id"], "review-session")["proposed_action"]
        with self.assertRaises(server.AppError):
            server.confirm_coach_action_preview(proposal["id"], "other-session")
        confirmed = server.confirm_coach_action_preview(proposal["id"], "review-session")
        token = confirmed["action_token"]
        with self.assertRaises(server.AppError):
            server.execute_coach_action(token, "other-session", proposal["payload_hash"])
        with self.assertRaises(server.AppError):
            server.execute_coach_action(token, "review-session", "0" * 64)
        self.assertEqual(len(server.list_workout_library()), 1)
        barrier = threading.Barrier(2)

        def execute():
            barrier.wait(timeout=5)
            try:
                server.execute_coach_action(token, "review-session", proposal["payload_hash"])
                return "applied"
            except server.AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: execute(), range(2)))
        self.assertCountEqual(results, ["applied", "rejected"])
        self.assertEqual(server.list_workout_library(), [])
        template = server.create_local_library_template({"name": "Expiry synthetic", "sport": "Run"})
        change = next(row for row in server.list_change_history() if row["entity_id"] == template["id"])
        proposal = server._history_preview(change["id"], "review-session")["proposed_action"]
        confirmed = server.confirm_coach_action_preview(proposal["id"], "review-session")
        with patch.object(server.time, "time", return_value=time.time() + server.COACH_ACTION_TTL_SECONDS + 1):
            with self.assertRaises(server.AppError):
                server.execute_coach_action(confirmed["action_token"], "review-session", proposal["payload_hash"])
        self.assertEqual(len(server.list_workout_library()), 1)

    def test_reload_preserves_pending_undo_but_changed_target_rejects_application(self):
        template = server.create_local_library_template({"name": "Synthetic original", "sport": "Run"})
        change = next(row for row in server.list_change_history() if row["entity_id"] == template["id"])
        proposal = server._history_preview(change["id"], "review-session")["proposed_action"]
        history = server.paged_chat_history(session_csrf_hash="review-session")
        self.assertEqual(history["proposed_actions"][0]["id"], proposal["id"])
        self.assertEqual(server.paged_chat_history(session_csrf_hash="other-session")["proposed_actions"], [])
        server.update_workout_library_entry(template["id"], {"action": "update", "name": "Synthetic changed"})
        confirmed = server.confirm_coach_action_preview(proposal["id"], "review-session")
        with self.assertRaises(server.AppError):
            server.execute_coach_action(confirmed["action_token"], "review-session", proposal["payload_hash"])
        self.assertEqual(server.list_workout_library()[0]["name"], "Synthetic changed")

    def test_adaptive_apply_after_day_change_preserves_now_past_unit(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        planned = server.save_workout_library_entries([{**self.workout(), "date": tomorrow, "duration_minutes": 60}])[0]
        server.save_checkin({"soreness": 8})
        preview = server.adaptive_replan_preview()
        self.assertTrue(preview["changes"])
        advanced = server.local_now() + timedelta(days=2)
        with patch.object(server, "local_now", return_value=advanced):
            applied = server.apply_adaptive_replan(preview["id"])
        self.assertEqual(applied["status"], "stale")
        self.assertEqual(applied["updated"], 0)
        self.assertEqual(applied["stale"][0]["reason"], "past")
        self.assertEqual(server.list_planned_units()[0]["duration_minutes"], planned["duration_minutes"])

    def test_expired_proposal_gc_and_confirmation_serialize_without_losing_drafts(self):
        template = server.create_local_library_template({"name": "GC synthetic", "sport": "Run"})
        change = next(row for row in server.list_change_history() if row["entity_id"] == template["id"])
        expired = server._history_preview(change["id"], "review-session")["proposed_action"]
        active = server._history_preview(change["id"], "review-session")["proposed_action"]
        draft = server._stage_coach_artifact("review-conversation", "draft", {"workouts": [self.workout()]})
        with server.database() as db:
            db.execute("UPDATE coach_action_proposals SET expires_at=? WHERE id=?", (time.time() - 1, expired["id"]))
        barrier = threading.Barrier(2)

        def collect():
            barrier.wait(timeout=5)
            with server.DB_LOCK, server.database() as db:
                return server.prune_expired_coach_proposals(db, time.time())

        def confirm():
            barrier.wait(timeout=5)
            try:
                server.confirm_coach_action_preview(expired["id"], "review-session")
                return "accepted"
            except server.AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            gc_result, confirmation = executor.submit(collect), executor.submit(confirm)
            self.assertEqual(gc_result.result(), 1)
            self.assertEqual(confirmation.result(), "rejected")
        self.assertEqual([item["id"] for item in server.current_coach_proposals("review-session")], [active["id"]])
        with server.database() as db:
            self.assertEqual(db.execute("SELECT status FROM coach_plan_artifacts WHERE id=?", (draft["artifact_id"],)).fetchone()["status"], "draft")


    def test_explicit_reconfirmation_after_reload_rotates_only_unused_token(self):
        template = server.create_local_library_template({"name": "Token recovery", "sport": "Run"})
        change = next(row for row in server.list_change_history() if row["entity_id"] == template["id"])
        proposal = server._history_preview(change["id"], "review-session")["proposed_action"]
        first = server.confirm_coach_action_preview(proposal["id"], "review-session")
        self.assertEqual(server.current_coach_proposals("review-session")[0]["status"], "ready")
        second = server.confirm_coach_action_preview(proposal["id"], "review-session")
        with self.assertRaises(server.AppError):
            server.execute_coach_action(first["action_token"], "review-session", proposal["payload_hash"])
        server.execute_coach_action(second["action_token"], "review-session", proposal["payload_hash"])
        with self.assertRaises(server.AppError):
            server.confirm_coach_action_preview(proposal["id"], "review-session")
        self.assertEqual(server.list_workout_library(), [])
