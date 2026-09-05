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

    def run_turn(self, intent, responses, turn="review-turn", session="review-session"):
        with patch.object(server, "request_coach_intent", return_value=intent), patch.object(server, "ensure_conversation", return_value="review-conversation"), patch.object(server, "build_training_context", return_value="Synthetic context"), patch.object(server, "responses_request", side_effect=responses):
            return server.chat_with_coach("Speichere die angegebenen lokalen Aenderungen", client_turn_id=turn, session_csrf_hash=session)

    def workout(self, offset=0, sport="Run"):
        return {"date": (date.today() + timedelta(days=50+offset)).isoformat(), "sport": sport, "name": "Synthetic session", "description": "Easy session", "duration_minutes": 30, "target": "AUTO"}

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

    def test_failed_plan_draft_can_be_corrected_and_committed_in_same_turn(self):
        bad = self.call("stage_training_plan", {"payload": {"plan_name": "Retry", "goal": "Base", "workouts": []}}, "bad-stage")
        good_workout = self.workout()
        good = self.call("stage_training_plan", {"payload": {"plan_name": "Retry", "goal": "Base", "workouts": [good_workout]}}, "good-stage")
        commit = self.call("commit_training_plan", {}, "commit")
        receipt = self.run_turn(
            self.intent("stage_training_plan", ["local_plan"], ("commit_training_plan",)),
            [{"output": [bad]}, {"output": [good]}, {"output": [commit]}, {"output_text": "Der Plan ist gespeichert."}],
            turn="retry-plan",
        )
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([item["result"]["ok"] for item in receipt["command_receipts"]], [False, True, True])
        self.assertEqual(len(server.list_planned_units()), 1)

    def test_same_plan_payload_with_new_call_id_stages_fresh_artifact_after_revision_change(self):
        intent = self.intent("stage_training_plan", ["local_plan"], ("commit_training_plan",))
        payload = {"payload": {"plan_name": "Retry", "goal": "Base", "workouts": [self.workout()]}}
        stage_one = self.call("stage_training_plan", payload, "stage-one")
        stage_two = self.call("stage_training_plan", payload, "stage-two")
        commit = self.call("commit_training_plan", {}, "commit")
        responses = [{"output": [stage_one]}, {"output": [stage_two]}, {"output": [commit]}, {"output_text": "Der Plan ist gespeichert."}]
        original = server._structured_coach_tool_result
        staged = []

        def execute(name, arguments, **kwargs):
            result = original(name, arguments, **kwargs)
            if name == "stage_training_plan":
                staged.append(result["artifact_id"])
                if len(staged) == 1:
                    with server.DB_LOCK, server.database() as db:
                        db.execute("UPDATE planning_state SET revision=revision+1 WHERE id=1")
            return result

        with patch.object(server, "_structured_coach_tool_result", side_effect=execute):
            receipt = self.run_turn(intent, responses, turn="fresh-stage-after-revision")
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(len(staged), 2)
        self.assertNotEqual(*staged)
        self.assertEqual(len(server.list_planned_units()), 1)

    def test_same_plan_payload_with_new_call_id_reuses_current_draft(self):
        intent = self.intent("stage_training_plan", ["local_plan"], ("commit_training_plan",))
        payload = {"payload": {"plan_name": "Retry", "goal": "Base", "workouts": [self.workout()]}}
        stage_one = self.call("stage_training_plan", payload, "stage-one")
        stage_two = self.call("stage_training_plan", payload, "stage-two")
        commit = self.call("commit_training_plan", {}, "commit")
        receipt = self.run_turn(
            intent,
            [{"output": [stage_one]}, {"output": [stage_two]}, {"output": [commit]}, {"output_text": "Der Plan ist gespeichert."}],
            turn="reuse-current-stage",
        )
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual([item["tool"] for item in receipt["command_receipts"]], ["stage_training_plan", "commit_training_plan"])
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM coach_plan_artifacts").fetchone()["n"], 1)
        self.assertEqual(len(server.list_planned_units()), 1)

    def test_tool_round_limit_submits_last_outputs_for_final_summary(self):
        read = self.call("read_training_state", {}, "read")
        with patch.object(server, "COACH_TOOL_MAX_ROUNDS", 1):
            receipt = self.run_turn(
                self.intent("stage_training_plan", ["local_plan"]),
                [{"output": [read]}, {"output_text": "Der Auftrag ist noch nicht abgeschlossen."}],
                turn="round-limit",
            )
        self.assertIn("noch nicht abgeschlossen", receipt["message"]["content"])

    def test_tool_round_limit_keeps_the_captured_provider_and_model(self):
        read = self.call("read_training_state", {}, "read")
        intent = self.intent("stage_training_plan", ["local_plan"])
        responses = [{"output": [read]}, {"output_text": "Zusammenfassung."}]
        with patch.object(server, "COACH_TOOL_MAX_ROUNDS", 1), patch.object(server, "selected_ai_provider", return_value="gemini"), patch.object(server, "selected_model", return_value="gemini-3.8-flash"), patch.object(server, "selected_thinking_level", return_value="low"), patch.object(server, "request_coach_intent", return_value=intent), patch.object(server, "ensure_conversation", return_value="gemini-conversation"), patch.object(server, "build_training_context", return_value="Synthetic context"), patch.object(server, "responses_request", side_effect=responses) as request:
            server.chat_with_coach("Speichere die angegebenen lokalen Aenderungen", client_turn_id="round-limit-gemini", session_csrf_hash="review-session")

        summary_payload = request.call_args_list[1].args[0]
        self.assertEqual(summary_payload["_ai_provider"], "gemini")
        self.assertEqual(summary_payload["model"], "gemini-3.8-flash")
        self.assertEqual(summary_payload["reasoning"], {"effort": "low"})

    def test_empty_final_summary_reports_only_unresolved_plan_step(self):
        bad = self.call("stage_training_plan", {"payload": {"plan_name": "Retry", "goal": "Base", "workouts": []}}, "bad-stage")
        good_workout = self.workout()
        good = self.call("stage_training_plan", {"payload": {"plan_name": "Retry", "goal": "Base", "workouts": [good_workout]}}, "good-stage")
        failed_commit = self.call("commit_training_plan", {}, "failed-commit")
        responses = [{"output": [bad]}, {"output": [good]}, {"output": [failed_commit]}, {"output": []}]
        conflict = server.AppError(409, "Final commit conflict", reason="planning_revision_conflict")
        original = server._structured_coach_tool_result

        def execute(name, arguments, **kwargs):
            if name == "commit_training_plan":
                raise conflict
            return original(name, arguments, **kwargs)

        with patch.object(server, "_structured_coach_tool_result", side_effect=execute):
            receipt = self.run_turn(
                self.intent("stage_training_plan", ["local_plan"], ("commit_training_plan",)),
                responses,
                turn="empty-final-summary",
            )
        content = receipt["message"]["content"]
        self.assertIn("nicht vollstaendig abgeschlossen", content)
        self.assertIn("Trainingsplan speichern: Final commit conflict", content)
        self.assertNotIn("Planentwurf erstellen", content)
        self.assertNotIn("Ergebnis: Planentwurf gespeichert", content)

    def test_final_summary_failure_with_no_pending_operations_uses_completed_receipt(self):
        operation = self.call("manage_training_templates", {"templates": [{"name": "Saved template", "sport": "Run"}]})
        receipt = self.run_turn(
            self.intent("manage_training_templates", ["local_template"]),
            [{"output": [operation]}, server.AppError(503, "Model unavailable")],
            turn="completed-effect-final-summary-failure",
        )
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["pending_operations"], [])
        self.assertIn("Ergebnis: Trainingsvorlagen bearbeitet", receipt["message"]["content"])
        self.assertNotIn("Zusammenfassung ist fehlgeschlagen", receipt["message"]["content"])

    def test_interrupted_multi_effect_turn_keeps_partial_status(self):
        today = date.today()
        first = self.call("save_checkin", {"payload": {"checkin_date": today.isoformat(), "notes": "First"}}, "first")
        second = self.call("save_checkin", {"payload": {"checkin_date": (today - timedelta(days=1)).isoformat(), "notes": "Second"}}, "second")
        original = server._structured_coach_tool_result
        calls = []

        def execute(name, arguments, **kwargs):
            calls.append(name)
            if len(calls) > 1:
                raise RuntimeError("process interrupted")
            return original(name, arguments, **kwargs)

        with patch.object(server, "_structured_coach_tool_result", side_effect=execute):
            receipt = self.run_turn(
                self.intent("save_checkin", ["local_checkin"]),
                [{"output": [first, second]}],
                turn="interrupted-multi-effect",
            )
        self.assertEqual(receipt["status"], "partial")
        self.assertIn("Tages-Check-in gespeichert", receipt["message"]["content"])
        self.assertIn("Nicht erfolgreich abgeschlossen", receipt["message"]["content"])
        self.assertEqual(len(server.list_checkins()), 1)

    def test_late_cancellation_reports_committed_effect(self):
        operation = self.call("manage_training_templates", {"templates": [{"name": "Cancelled late", "sport": "Run"}]})
        receipt = self.run_turn(
            self.intent("manage_training_templates", ["local_template"]),
            [{"output": [operation]}, server.AppError(499, "Cancelled", reason="chat_cancelled")],
            turn="late-cancelled-effect",
        )
        self.assertEqual(receipt["status"], "completed")
        self.assertIn("Ergebnis: Trainingsvorlagen bearbeitet", receipt["message"]["content"])
        self.assertNotIn("abgebrochen", receipt["message"]["content"])

    def test_template_batch_invalid_second_or_last_has_no_partial_writes(self):
        for position in (1,2):
            with self.subTest(position=position):
                templates=[{"name":"Synthetic template","sport":"Run","duration_minutes":30} for _ in range(3)]
                templates[position]["duration_minutes"]="invalid"
                with self.assertRaises(server.AppError):
                    server._structured_coach_tool_result("manage_training_templates",{"templates":templates},intent=self.intent("manage_training_templates",["local_template"]),conversation_id="review-conversation",client_turn_id="batch",session_csrf_hash="review-session",sync_job_ids=[])
                self.assertEqual(server.list_workout_library(),[])

    def test_successful_write_followup_failure_is_recoverable_with_one_message_pair(self):
        operation=self.call("manage_training_templates",{"templates":[{"name":"One saved template","sport":"Run","duration_minutes":30}]})
        receipt=self.run_turn(self.intent("manage_training_templates",["local_template"]),[{"output":[operation]},server.AppError(503,"Model unavailable")])
        self.assertEqual(receipt["status"],"completed")
        self.assertTrue(receipt["command_receipts"][0]["result"]["ok"])
        self.assertEqual(len(server.list_workout_library()),1)
        recovered=server.coach_command_receipt("review-turn","review-session")
        self.assertEqual(recovered["message"]["id"],receipt["message"]["id"])
        history=server.paged_chat_history()["messages"]
        self.assertEqual([m["client_turn_id"] for m in history],["review-turn","review-turn"])
        with patch.object(server,"responses_request") as response:
            replay=server.chat_with_coach("Speichere",client_turn_id="review-turn",session_csrf_hash="review-session")
        response.assert_not_called();self.assertEqual(replay["message"]["id"],receipt["message"]["id"])
        with self.assertRaises(server.AppError) as error:server.coach_command_receipt("review-turn","other-session")
        self.assertEqual(error.exception.status,403)

    def test_distinct_same_tool_effects_execute_once_and_repeated_call_replays(self):
        today=date.today()
        one=self.call("save_checkin",{"payload":{"checkin_date":today.isoformat(),"notes":"Synthetic today"}},"first")
        two=self.call("save_checkin",{"payload":{"checkin_date":(today-timedelta(days=1)).isoformat(),"notes":"Synthetic yesterday"}},"second")
        receipt=self.run_turn(self.intent("save_checkin",["local_checkin"]),[{"output":[one,two,one]},{"output_text":"Gespeichert"}])
        self.assertEqual(receipt["status"],"completed")
        self.assertEqual(len(receipt["command_receipts"]),2)
        with server.database() as db:self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM athlete_checkins").fetchone()["n"],2)

    def test_same_call_id_cannot_be_rebound_to_a_new_effect_or_session(self):
        one=self.call("manage_training_templates",{"templates":[{"name":"One","sport":"Run"}]})
        two=self.call("manage_training_templates",{"templates":[{"name":"Two","sport":"Run"}]})
        receipt=self.run_turn(self.intent("manage_training_templates",["local_template"]),[{"output":[one,two]}])
        self.assertEqual(receipt["status"],"completed");self.assertEqual(len(server.list_workout_library()),1)
        with self.assertRaises(server.AppError):server.chat_with_coach("Speichere",client_turn_id="review-turn",session_csrf_hash="other-session")
        self.assertEqual(server.coach_command_receipt("review-turn","review-session")["message"]["id"],receipt["message"]["id"])

    def test_created_refresh_job_is_readable_only_by_own_turn(self):
        intent={**self.intent("start_provider_refresh",["garmin_refresh"],("get_sync_job",)),"intent":"remote_sync","target_system":"garmin"}
        ids=[];kwargs=dict(intent=intent,conversation_id="review-conversation",client_turn_id="refresh",session_csrf_hash="review-session",sync_job_ids=ids)
        job=server._structured_coach_tool_result("start_provider_refresh",{},**kwargs)
        status=server._structured_coach_tool_result("get_sync_job",{"job_id":job["sync_job_id"]},**kwargs)
        self.assertEqual(status["job"]["id"],job["sync_job_id"])
        with self.assertRaises(server.AppError):server._structured_coach_tool_result("get_sync_job",{"job_id":job["sync_job_id"]},**{**kwargs,"sync_job_ids":[]})

    def test_named_competition_scope_is_narrowed_and_ambiguity_clarifies(self):
        refs=[{"kind":"competition","id":"one","name":"Synthetic race","date":"2099-01-01"}]
        intent=self.intent("save_competition",["local_competitions"])
        resolved=server.resolve_intent_objects(intent,"Benenne Synthetic race um",refs)
        self.assertEqual(resolved["authorization_scope"],["competition:one"])
        duplicate=server.resolve_intent_objects(intent,"Benenne Synthetic race um",refs+[{**refs[0],"id":"two","date":"2099-02-01"}])
        self.assertEqual(duplicate["intent"],"needs_clarification");self.assertEqual(len(duplicate["ambiguities"]),1)
        overlapping = [
            {"kind": "competition", "id": "short-id", "name": "Marathon", "date": "2099-01-01"},
            {"kind": "competition", "id": "long-id", "name": "Berlin Marathon", "date": "2099-02-01"},
        ]
        selected = server.resolve_intent_objects(intent, "Benenne Berlin Marathon um", overlapping)
        self.assertEqual(selected["authorization_scope"], ["competition:long-id"])
        selected = server.resolve_intent_objects(intent, "Benenne Marathon und Berlin Marathon um", overlapping)
        self.assertCountEqual(selected["authorization_scope"], ["competition:long-id", "competition:short-id"])

    def test_undo_proposal_is_top_level_recoverable_and_keeps_hash_guard(self):
        template=server.create_local_library_template({"name":"Synthetic undo","sport":"Run"})
        change=next(row for row in server.list_change_history() if row["entity_id"]==template["id"])
        receipt=self.run_turn(self.intent("undo_training_change",["change:"+change["id"]]),[{"output":[self.call("undo_training_change",{"change_id":change["id"]})]},{"output_text":"Bitte freigeben"}])
        self.assertEqual(len(receipt["proposed_actions"]),1)
        recovered=server.coach_command_receipt("review-turn","review-session")
        proposal=recovered["proposed_actions"][0]
        confirmed=server.confirm_coach_action_preview(proposal["id"],"review-session")
        server.execute_coach_action(confirmed["action_token"],"review-session",proposal["payload_hash"])
        self.assertEqual(server.list_workout_library(),[])
        with self.assertRaises(server.AppError):server.execute_coach_action(confirmed["action_token"],"review-session",proposal["payload_hash"])

    def test_named_competition_rename_runs_without_user_supplied_identifier(self):
        saved = server.save_coach_competition({"name": "Synthetic race", "event_date": "2099-01-01", "sport": "Running"})
        identifier = saved["competition"]["id"]
        message = "Benenne Synthetic race in Synthetic goal um"
        intent = self.intent("save_competition", ["local_competitions"])
        requests = []

        def respond(payload):
            requests.append(payload)
            if payload.get("text", {}).get("format", {}).get("name") == "coach_intent":
                refs = json.loads(payload["input"])["object_refs"]
                self.assertTrue(any(ref["id"] == identifier for ref in refs))
                return {"output_text": json.dumps(intent)}
            if len(requests) == 2:
                return {"output": [self.call("save_competition", {"payload": {"competition_id": identifier, "name": "Synthetic goal"}})]}
            return {"output_text": "Wettkampf umbenannt"}

        with patch.object(server, "ensure_conversation", return_value="review-conversation"), patch.object(server, "responses_request", side_effect=respond), patch.object(server, "build_training_context", return_value="Synthetic context"):
            result = server.chat_with_coach(message, client_turn_id="rename", session_csrf_hash="review-session")
        self.assertTrue(result["command_receipts"][0]["result"]["ok"])
        self.assertEqual(server.list_competitions()[0]["name"], "Synthetic goal")
        self.assertEqual(result["intent"]["authorization_scope"], ["competition:" + identifier])

    def test_automatic_read_only_turn_cannot_execute_model_mutation(self):
        mutation = self.call("save_checkin", {"payload": {"checkin_date": date.today().isoformat(), "notes": "Must not write"}})
        with patch.object(server, "request_coach_intent") as classifier, patch.object(server, "ensure_conversation", return_value="review-conversation"), patch.object(server, "build_training_context", return_value="Synthetic context"), patch.object(server, "responses_request", return_value={"output": [mutation]}):
            result = server.chat_with_coach("Gib einen kurzen Tageshinweis", allow_mutations=False, client_turn_id="morning:synthetic")
        classifier.assert_not_called()
        self.assertEqual(result["status"], "failed")
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM athlete_checkins").fetchone()["n"], 0)

    def test_same_build_restart_recovers_completed_local_effect_without_reexecution(self):
        operation = self.call("manage_training_templates", {"templates": [{"name": "Durable result", "sport": "Run"}]})
        receipt = self.run_turn(self.intent("manage_training_templates", ["local_template"]), [{"output": [operation]}, server.AppError(503, "Model unavailable")])
        with server.database() as db:
            stored = json.loads(db.execute("SELECT receipt FROM coach_commands WHERE client_turn_id='review-turn'").fetchone()["receipt"])
            db.execute("DELETE FROM messages WHERE id=?", (stored["message"]["id"],))
            stored["message"] = None
            stored["status"] = "running"
            db.execute("UPDATE coach_commands SET status='running', receipt=? WHERE client_turn_id='review-turn'", (json.dumps(stored),))
        server.resume_interrupted_coach_jobs()
        recovered = server.coach_command_receipt("review-turn", "review-session")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(len(server.list_workout_library()), 1)
        self.assertEqual(len(server.paged_chat_history()["messages"]), 2)

    def test_running_foreign_command_is_neither_executed_nor_closed(self):
        identity = {"session_key": server._coach_session_key("owner"), "status": "running"}
        with server.database() as db:
            db.execute("INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) VALUES ('foreign', 'foreign', 'review-conversation', '{}', 'local', 'running', ?, ?, ?)", (json.dumps(identity), server.utc_now(), server.utc_now()))
        with self.assertRaises(server.AppError) as error:
            server._chat_with_structured_coach("Edit", intent=self.intent("save_checkin", ["local_checkin"]), conversation_id="review-conversation", client_turn_id="foreign", session_csrf_hash="intruder")
        self.assertEqual(error.exception.status, 403)
        with server.database() as db:
            self.assertEqual(db.execute("SELECT status FROM coach_commands WHERE client_turn_id='foreign'").fetchone()["status"], "running")

    def test_cancelled_partial_tool_payload_has_no_local_effect(self):
        cancel = threading.Event()

        def stream(*args, **kwargs):
            cancel.set()
            return {"output": [{"type": "function_call", "name": "save_checkin", "call_id": "partial", "arguments": '{"payload":'}]}

        with patch.object(server, "request_coach_intent", return_value=self.intent("save_checkin", ["local_checkin"])), patch.object(server, "ensure_conversation", return_value="review-conversation"), patch.object(server, "build_training_context", return_value="Synthetic context"), patch.object(server, "responses_stream_request", side_effect=stream):
            receipt = server.chat_with_coach("Speichere meinen Check-in", client_turn_id="cancelled-partial", session_csrf_hash="review-session", on_text_delta=lambda _: None, cancel_event=cancel)
        self.assertEqual(receipt["status"], "cancelled")
        self.assertEqual(receipt["command_receipts"], [])
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM athlete_checkins").fetchone()["n"], 0)

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
        self.assertTrue(any(item["id"] == draft["artifact_id"] for item in server.coach_intent_artifact_refs("review-conversation")))

    def test_garmin_refresh_turn_resolves_its_own_job_and_reports_queue_state(self):
        intent = {**self.intent("start_provider_refresh", ["garmin_refresh"], ["get_sync_job"]), "intent": "remote_sync", "target_system": "garmin"}
        stages = []

        def respond(payload):
            if payload.get("text", {}).get("format", {}).get("name") == "coach_intent":
                stages.append("classified")
                self.assertIn("garmin", json.loads(payload["input"])["allowed_targets"])
                return {"output_text": json.dumps(intent)}
            if isinstance(payload["input"], str):
                stages.append("enqueue")
                return {"output": [self.call("start_provider_refresh", {}, "refresh")]}
            result = json.loads(payload["input"][0]["output"])
            if "sync_job_id" in result:
                stages.append("status")
                return {"output": [self.call("get_sync_job", {"job_id": result["sync_job_id"]}, "status")]}
            stages.append("answer")
            self.assertEqual(result["job"]["status"], "queued")
            return {"output_text": "Garmin-Aktualisierung ist beauftragt und wartet auf die Verarbeitung."}

        with patch.object(server, "CONFIG", replace(server.CONFIG, garmin_email="synthetic@example.invalid")), patch.object(server, "ensure_conversation", return_value="review-conversation"), patch.object(server, "build_training_context", return_value="Synthetic context"), patch.object(server, "responses_request", side_effect=respond), patch.object(server, "sync_garmin") as provider:
            receipt = server.chat_with_coach("Aktualisiere Garmin und melde das Ergebnis", client_turn_id="garmin-refresh", session_csrf_hash="review-session")
        provider.assert_not_called()
        self.assertEqual(stages, ["classified", "enqueue", "status", "answer"])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["command_receipts"][1]["result"]["job"]["id"], receipt["sync_job_ids"][0])

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
