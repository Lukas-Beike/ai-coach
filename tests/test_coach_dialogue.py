"""Synthetic multi-turn dialogue contracts; model replies are deliberately mocked.

These regressions verify execution, not a language model's recognition quality.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import test_server as fixtures
from backend.coach.dialogue import validate_request

server = fixtures.server


class DialogueHarness:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coach-dialogue-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, value in (("CONFIG", replace(server.CONFIG, app_password="")), ("DATA_DIR", root),
                            ("DB_PATH", root / "test.db"), ("LOG_PATH", root / "test.log")):
            context = patch.object(server, name, value)
            context.start()
            self.addCleanup(context.stop)
        server.initialise_database()
        fixtures.CoachTests.setUp(self)
        fixed = patch.object(server, "local_now", return_value=datetime(2026, 9, 7, 12, tzinfo=timezone.utc))
        fixed.start()
        self.addCleanup(fixed.stop)
        self.counter = 0

    def workout(self, day="2026-09-09", name="Oberkörper moderat + Core"):
        return {"date": day, "name": name, "sport": "WeightTraining", "description": "Synthetic easy workout",
                "duration_minutes": 30, "target": "AUTO", "rationale": "Synthetic training goal"}

    def request(self, scope, target="local", period=None, remote_write=False, sync_scope=None):
        current = [item for item in server.list_messages() if item["role"] == "user"][-1]
        return {"summary": "Synthetic current request", "source_message_ids": [current["id"]],
                "target": target, "scope": scope, "period": period, "constraints": [],
                "remote_write": remote_write, "sync_scope": sync_scope}

    def call(self, name, arguments=None, scope=None, period=None, target="local", remote_write=False, sync_scope=None, call_id=None):
        self.counter += 1
        arguments = dict(arguments or {})
        if scope is not None:
            arguments["_request"] = self.request(scope, target, period, remote_write, sync_scope)
        return {"output": [{"type": "function_call", "name": name, "call_id": call_id or f"call-{self.counter}",
                            "arguments": json.dumps(arguments)}]}

    def turn(self, message, steps, turn=None, **kwargs):
        steps = iter(steps)
        self.counter += 1
        def response(payload, *args, **extra):
            step = next(steps)
            return step(payload) if callable(step) else step
        with patch.object(server, "ensure_conversation", return_value="synthetic-conversation"), patch.object(
            server, "build_training_context", return_value="Synthetic local data"
        ), patch.object(server, "responses_request", side_effect=response) as model, patch.object(server, "responses_background_request", side_effect=response) as background_model:
            receipt = server.chat_with_coach(message, client_turn_id=turn or f"turn-{self.counter}", session_csrf_hash="synthetic-session", **kwargs)
        return receipt, background_model if kwargs.get("background_job") else model

    def state(self):
        return server._structured_training_state()


class CoachDialogueTests(DialogueHarness, unittest.TestCase):

    def test_profile_proposal_acceptance_preserves_existing_fields_and_replays_once(self):
        server.save_profile({"name": "Synthetic Athlete", "training_background": "Regular cycling.", "equipment": "Indoor bike"})
        self.turn("Ich gehe täglich spazieren.", [{"output_text": "Soll ich die tägliche Alltagsbewegung dauerhaft im Profil ergänzen?"}])
        change = {"field": "training_background", "expected_value": "Regular cycling.", "value": "Regular cycling. Daily easy walks."}
        result, _ = self.turn("Ja bitte füge das dauerhaft in mein Profil hinzu", [
            lambda _: self.call("read_profile"),
            lambda _: self.call("update_profile", {"changes": [change]}, ["local_profile"]),
            {"output_text": "Im Profil gespeichert."},
        ], turn="profile-acceptance")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(server.get_profile()["equipment"], "Indoor bike")
        self.assertEqual(server.get_profile()["name"], "Synthetic Athlete")
        self.assertEqual(server.get_profile()["training_background"], change["value"])
        replay, model = self.turn("Ja bitte füge das dauerhaft in mein Profil hinzu", [], turn="profile-acceptance")
        model.assert_not_called()
        self.assertEqual(replay, result)
        self.assertEqual(result["sync_job_ids"], [])

    def test_profile_patch_conflict_is_atomic_and_can_be_repaired(self):
        server.save_profile({"name": "Synthetic", "training_background": "Current facts"})
        original = server.get_profile()
        changes = [{"field": "name", "expected_value": "Synthetic", "value": "Updated"},
                   {"field": "training_background", "expected_value": "Old facts", "value": "New facts"}]
        def repair(_):
            self.assertEqual(server.get_profile(), original)
            return self.call("update_profile", {"changes": [changes[0], {"field": "training_background", "expected_value": "Current facts", "value": "Current facts. Daily walking."}]}, ["local_profile"])
        result, _ = self.turn("Bitte dauerhaft merken", [
            lambda _: self.call("update_profile", {"changes": changes}, ["local_profile"]),
            lambda _: self.call("read_profile"), repair, {"output_text": "Gespeichert."},
        ])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["command_receipts"][0]["resolved"])
        self.assertEqual(server.get_profile()["name"], "Updated")

    def test_profile_conflict_repair_does_not_hide_an_independent_field_failure(self):
        server.save_profile({"name": "Synthetic", "training_background": "Current facts"})
        result, _ = self.turn("Bitte speichere beide Profilangaben", [
            lambda _: self.call("update_profile", {"changes": [
                {"field": "training_background", "expected_value": "Old facts", "value": "New facts"},
            ]}, ["local_profile"]),
            lambda _: self.call("update_profile", {"changes": [
                {"field": "name", "expected_value": "Synthetic", "value": "Updated"},
            ]}, ["local_profile"]),
            {"output_text": "Teilweise gespeichert."},
        ])
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["command_receipts"][0].get("resolved"))
        self.assertEqual(server.get_profile()["name"], "Updated")
        self.assertEqual(server.get_profile()["training_background"], "Current facts")

    def test_profile_rejects_unknown_duplicate_invalid_and_unscoped_changes(self):
        good = {"field": "name", "expected_value": "", "value": "Synthetic"}
        cases = [([good], ["local_checkin"]), ([good, good], ["local_profile"]),
                 ([{**good, "field": "api_key"}], ["local_profile"]),
                 ([{**good, "value": None}], ["local_profile"]),
                 ([{**good, "value": "x" * 4001}], ["local_profile"]),
                 ([good, {"field": "timezone", "expected_value": server.get_profile()["timezone"], "value": "Mars/Test"}], ["local_profile"])]
        before = server.get_profile()
        for changes, scope in cases:
            result, _ = self.turn("Bitte speichern", [lambda _, c=changes, s=scope: self.call("update_profile", {"changes": c}, s), {"output_text": "Nicht gespeichert."}])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(server.get_profile(), before)

    def test_sync_invalid_id_repair_clears_error_and_queues_only_selected_unit(self):
        units = server.save_workout_library_entries([self.workout("2026-09-09"), self.workout("2026-09-11")])
        entry = next(item for item in server._pending_plan_push_entries() if item["library_workout_id"] == units[0]["id"])
        scope = ["intervals_sync", f"planned_unit:{units[0]['id']}"]
        self.turn("Freitag bitte lockerer", [{"output_text": "Die lokale Planung ist gespeichert."}])
        result, _ = self.turn("Bitte zu intervals.icu synchronisieren", [
            lambda _: self.call("start_intervals_plan_sync", {"entries": [{"local_id": units[0]["id"], "expected_payload_hash": entry["expected_payload_hash"]}]}, scope,
                                target="intervals", remote_write=True, sync_scope="selected"),
            lambda _: self.call("read_training_state"),
            lambda _: self.call("start_intervals_plan_sync", {"entries": [entry]}, list(reversed(scope)),
                                target="intervals", remote_write=True, sync_scope="selected"),
            {"output_text": "Synchronisierung beauftragt."},
        ])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["command_receipts"][0]["resolved"])
        self.assertEqual(result["pending_operations"], [])
        with server.database() as db:
            job = db.execute("SELECT payload FROM sync_jobs WHERE id=?", (result["sync_job_ids"][0],)).fetchone()
        self.assertEqual([item["library_workout_id"] for item in json.loads(job["payload"])["entries"]], [units[0]["id"]])

    def test_selected_sync_validates_hash_before_changing_state(self):
        unit = server.save_workout_library_entries([self.workout()])[0]
        before = self.state()
        result, _ = self.turn("Diese Einheit übertragen", [lambda _: self.call("start_intervals_plan_sync", {
            "entries": [{"library_workout_id": unit["id"], "expected_payload_hash": "0" * 64}]},
            ["intervals_sync", f"planned_unit:{unit['id']}"], target="intervals", remote_write=True, sync_scope="selected"),
            {"output_text": "Nicht übertragen."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state(), before)
        self.assertEqual(result["sync_job_ids"], [])

    def test_sync_conflict_resolution_queues_hash_of_validated_updated_payload(self):
        unit = server.save_workout_library_entries([self.workout()])[0]
        with server.database() as db:
            row = db.execute("SELECT payload FROM planned_units WHERE local_id=?", (unit["id"],)).fetchone()
            payload = json.loads(row["payload"])
            payload["sync_status"] = "conflict"
            db.execute("UPDATE planned_units SET payload=?, sync_state='conflict' WHERE local_id=?", (json.dumps(payload), unit["id"]))
        before = self.state()["planned_units"][0]
        result, _ = self.turn("Diese lokale Einheit zu Intervals übertragen", [lambda _: self.call("start_intervals_plan_sync", {
            "entries": [{"library_workout_id": unit["id"], "expected_payload_hash": before["expected_payload_hash"]}]},
            ["intervals_sync", f"planned_unit:{unit['id']}"], target="intervals", remote_write=True, sync_scope="selected"),
            {"output_text": "Beauftragt."}])
        self.assertEqual(result["status"], "completed")
        with server.database() as db:
            job = db.execute("SELECT payload FROM sync_jobs WHERE id=?", (result["sync_job_ids"][0],)).fetchone()
        queued = json.loads(job["payload"])["entries"][0]["expected_payload_hash"]
        self.assertNotEqual(queued, before["expected_payload_hash"])
        self.assertEqual(queued, self.state()["planned_units"][0]["expected_payload_hash"])

    def test_success_on_other_object_does_not_hide_failed_step(self):
        entries = [
            {"tool": "start_intervals_plan_sync", "step_key": "first", "request": {"target": "intervals", "scope": ["planned_unit:first"], "sync_scope": "selected"}, "result": {"ok": False, "reason": "tool_arguments_invalid"}},
            {"tool": "start_intervals_plan_sync", "step_key": "second", "request": {"target": "intervals", "scope": ["planned_unit:second"], "sync_scope": "selected"}, "result": {"ok": True}},
        ]
        self.assertEqual(server._unresolved_coach_steps(entries), [entries[0]])
        entries[1]["request"].update(scope=["local_plan", "intervals_sync"], sync_scope="all_pending")
        self.assertEqual(server._unresolved_coach_steps(entries), [])

    def test_retry_uses_original_job_provider_and_write_authority(self):
        for provider, kind, remote, scope in (("intervals", "plan_push", True, "intervals_sync"),
                                              ("garmin", "refresh", False, "garmin_refresh")):
            payload = {"reason": "Synthetic retry", "days": 7}
            if remote:
                server.save_workout_library_entries([self.workout()])
                payload = {"reason": "Synthetic retry", "entries": server._pending_plan_push_entries()}
            job = server.enqueue_sync_job(provider, kind, payload, requested_by="coach")
            with server.database() as db:
                db.execute("UPDATE sync_jobs SET status='failed' WHERE id=?", (job["id"],))
            result, _ = self.turn("Bitte nochmal versuchen", [lambda _, j=job: self.call("resolve_training_sync_conflict", {"job_id": j["id"]}, [f"sync_job:{j['id']}"]),
                                                    {"output_text": "Noch nicht gestartet."}])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(server.sync_job_state(job["id"])["status"], "failed")
            result, _ = self.turn("Ja, bei dem Anbieter nochmal versuchen", [
                lambda _, j=job: self.call("get_sync_job", {"job_id": j["id"]}),
                lambda _, j=job, p=provider, r=remote, s=scope: self.call("resolve_training_sync_conflict", {"job_id": j["id"]},
                    [f"sync_job:{j['id']}", s], target=p, remote_write=r), {"output_text": "Erneut beauftragt."},
            ])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(server.sync_job_state(job["id"])["status"], "queued")
            self.assertEqual(result["sync_job_ids"], [job["id"]])

    def test_every_tool_exposes_nested_object_fields_and_rejects_advice_writes(self):
        def inspect(schema, name):
            if schema.get("type") == "object":
                self.assertIn("properties", schema, name)
                for value in schema["properties"].values():
                    inspect(value, name)
            if "items" in schema:
                inspect(schema["items"], name)
        with server.database() as db:
            server.CHAT_REPOSITORY.add(db, "user", "Synthetic current request", client_turn_id="tool-audit")
        context = server.coach_dialogue_context("tool-audit")
        for tool in server.COACH_DIALOGUE_TOOLS:
            with self.subTest(tool=tool["name"]):
                inspect(tool["parameters"], tool["name"])
                if tool["name"] not in server.STRUCTURED_READ_ONLY_TOOLS | {"clarify_coach_request", "cancel_coach_request"}:
                    with self.assertRaises(server.AppError):
                        server._dialogue_action(tool["name"], {}, context, allow_mutations=False)
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_receipt_cards_show_only_unresolved_failures(self):
        subprocess.run(["node", "--test", str(Path(__file__).with_name("coach-receipts.test.cjs"))], check=True)

    def test_coach_starts_with_tools_and_local_dialogue_without_classifier(self):
        result, model = self.turn("Was hältst du von Mittwoch?", [{"output_text": "Ein lockerer Lauf wäre möglich."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_count, 1)
        payload = model.call_args.args[0]
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(any(tool["name"] == "apply_training_patch" for tool in payload["tools"]))
        context = json.loads(payload["input"])["dialogue"]
        self.assertEqual(context["local_date"], "2026-09-07")
        self.assertEqual(context["messages"][-1]["role"], "user")
        self.assertFalse(hasattr(server, "request_coach_intent"))
        self.assertEqual(self.state()["planned_units"], [])

    def test_request_period_matches_existing_730_day_plan_contract(self):
        request = {
            "summary": "Sparse long plan", "source_message_ids": [1], "target": "local",
            "scope": ["local_plan"], "period": {"start": "2026-09-07", "end": "2028-09-06"},
            "constraints": [], "remote_write": False, "sync_scope": None,
        }
        self.assertEqual(validate_request(request, {1}, 1)["period"]["end"], "2028-09-06")
        request["period"]["end"] = "2028-09-07"
        with self.assertRaises(ValueError):
            validate_request(request, {1}, 1)

    def test_screenshot_followup_moves_and_adds_atomically_without_literal_name(self):
        existing = server.save_workout_library_entries([self.workout()], plan_name="September")[0]
        def question(_):
            current = server.list_messages()[-1]["id"]
            return self.call("clarify_coach_request", {"source_message_ids": [current],
                "summary": "Diese Woche anpassen, Donnerstag bleibt frei.", "question": "Wie soll ich Dienstag und Mittwoch anpassen?"})
        first, _ = self.turn("Diese Woche müssen wir etwas anpassen.", [question, {"output_text": "Wie soll ich Dienstag und Mittwoch anpassen?"}])
        self.assertIn("Dienstag", first["message"]["content"])
        before = self.state()
        period = {"start": "2026-09-08", "end": "2026-09-09"}
        def apply(payload):
            self.assertIsNotNone(json.loads(payload["input"])["dialogue"]["pending_request"])
            return self.call("apply_training_patch", {"changes": [{"local_id": existing["id"], "action": "update", "date": "2026-09-08",
                "expected_payload_hash": before["planned_units"][0]["expected_payload_hash"]}],
                "workouts": [{**self.workout(name="Lockerer 10-km-Lauf"), "sport": "Run"}],
                "expected_revision": before["planning_revision"]}, [f"planned_unit:{existing['id']}", "local_plan"], period)
        result, _ = self.turn("Morgen die Oberkörper Kraft + Mobility Einheit. Mittwoch ein lockerer 10km Lauf.", [apply, {"output_text": "Oberkörper ist Dienstag, der Lauf Mittwoch."}])
        self.assertEqual(result["status"], "completed", [entry.get("result", {}).get("error") for entry in result["command_receipts"]])
        units = self.state()["planned_units"]
        self.assertEqual([(item["date"], item["name"]) for item in units], [("2026-09-08", "Oberkörper moderat + Core"), ("2026-09-09", "Lockerer 10-km-Lauf")])
        self.assertEqual(units[0]["local_id"], existing["id"])
        self.assertIsNone(json.loads(server.get_kv("coach_pending_request")))

    def test_failed_addition_rolls_back_move_and_revision(self):
        existing = server.save_workout_library_entries([self.workout()])[0]
        before = self.state()
        def action(_):
            return self.call("apply_training_patch", {"changes": [{"local_id": existing["id"], "action": "update", "date": "2026-09-08",
                "expected_payload_hash": before["planned_units"][0]["expected_payload_hash"]}],
                "workouts": [self.workout("2026-09-08", "Collision")], "expected_revision": before["planning_revision"]},
                [f"planned_unit:{existing['id']}", "local_plan"], {"start": "2026-09-08", "end": "2026-09-09"})
        result, _ = self.turn("Dann Dienstag beides", [action, {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state(), before)
        self.assertNotEqual(result["message"]["content"], "Gespeichert.")

    def test_stale_hash_rolls_back_whole_patch(self):
        existing = server.save_workout_library_entries([self.workout()])[0]
        before = self.state()
        result, _ = self.turn("Dann morgen", [lambda _: self.call("apply_training_patch", {
            "changes": [{"local_id": existing["id"], "date": "2026-09-08", "action": "update", "expected_payload_hash": "0" * 64}],
            "workouts": [], "expected_revision": before["planning_revision"]}, [f"planned_unit:{existing['id']}"],
            {"start": "2026-09-08", "end": "2026-09-09"}), {"output_text": "Bitte erneut prüfen."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state(), before)

    def test_bounded_giro_rebuild_preserves_later_units_and_plan_constraints(self):
        entries = server.save_workout_library_entries([self.workout(), self.workout("2026-10-05", "Nach dem Giro")], plan_name="Alter Plan")
        before = self.state()
        def rebuild(_):
            response = self.call("replace_training_plan", {"expected_revision": before["planning_revision"], "payload": {
                "plan_name": "Bis zum Giro", "goal": "Tapering", "workouts": [self.workout("2026-09-08"), self.workout("2026-09-11")]}},
                ["local_plan"], {"start": "2026-09-07", "end": "2026-10-03"})
            args = json.loads(response["output"][0]["arguments"])
            args["_request"]["constraints"] = ["Zweimal Oberkörper pro Woche", "10.09. frei", "Tapering zum Giro"]
            response["output"][0]["arguments"] = json.dumps(args)
            return response
        result, _ = self.turn("Bitte bis zum Giro durchplanen, zweimal Oberkörper pro Woche.", [rebuild, {"output_text": "Der Zeitraum ist geplant."}])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(any(item["local_id"] == entries[1]["id"] for item in self.state()["planned_units"]))
        old_plan = next(item for item in server.list_training_plans() if item["name"] == "Alter Plan")
        self.assertNotEqual(old_plan["status"], "archived")
        new_plan = next(item for item in server.list_training_plans() if item["name"] == "Bis zum Giro")
        self.assertIn("Zweimal Oberkörper pro Woche", new_plan["constraints"])

    def test_out_of_period_change_is_rejected(self):
        existing = server.save_workout_library_entries([self.workout("2026-10-05")])[0]
        before = self.state()
        result, _ = self.turn("Bis zum Giro", [lambda _: self.call("apply_training_patch", {
            "changes": [{"local_id": existing["id"], "action": "delete", "expected_payload_hash": before["planned_units"][0]["expected_payload_hash"]}],
            "expected_revision": before["planning_revision"]}, [f"planned_unit:{existing['id']}"],
            {"start": "2026-09-07", "end": "2026-10-03"}), {"output_text": "Nicht geändert."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state(), before)

    def test_provider_switch_retains_pending_question(self):
        def question(_):
            return self.call("clarify_coach_request", {"source_message_ids": [server.list_messages()[-1]["id"]],
                "summary": "Eine von zwei Einheiten verschieben", "question": "Die lockere oder die intensive Einheit?"})
        self.turn("Die Einheit verschieben", [question, {"output_text": "Welche Einheit?"}])
        with patch.object(server, "selected_ai_provider", return_value="gemini"):
            result, model = self.turn("Die zweite", [{"output_text": "Du meinst die intensive Einheit."}])
        context = json.loads(model.call_args.args[0]["input"])["dialogue"]
        self.assertIn("intensive", context["pending_request"]["question"])
        self.assertEqual(result["status"], "completed")

    def test_cancel_and_chat_reset_close_pending_request(self):
        server.set_kv("coach_pending_request", json.dumps({"summary": "Synthetic", "source_message_ids": []}))
        result, _ = self.turn("Lass es doch", [lambda _: self.call("cancel_coach_request"), {"output_text": "Abgebrochen."}])
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(json.loads(server.get_kv("coach_pending_request")))
        server.set_kv("coach_pending_request", json.dumps({"summary": "Synthetic", "source_message_ids": []}))
        server.reset_coach_chat()
        self.assertIsNone(json.loads(server.get_kv("coach_pending_request")))

    def test_remote_write_requires_per_step_sync_authority(self):
        with patch.object(server, "enqueue_sync_job") as enqueue:
            result, _ = self.turn("Ja, speichern", [lambda _: self.call("start_intervals_plan_sync", {}, ["local_plan"],
                target="intervals", sync_scope="all_pending"), {"output_text": "Nicht synchronisiert."}])
        enqueue.assert_not_called()
        self.assertEqual(result["status"], "failed")

    def test_current_refresh_runs_before_next_model_response_without_trigger_gate(self):
        with patch.object(server, "sync_intervals", return_value={"status": "ok", "activity_days": 7}) as sync:
            result, model = self.turn("Sind die Zahlen wirklich von heute? Bitte damit bewerten.", [
                lambda _: self.call("start_provider_refresh", {"days": 7}, ["intervals_refresh"], target="intervals"),
                lambda _: {"output_text": "Aktuelle Daten bewertet."} if sync.called else self.fail("refresh must finish first"),
            ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_count, 2)
        sync.assert_called_once()

    def test_idempotent_client_turn_does_not_repeat_effect(self):
        steps = [lambda _: self.call("save_checkin", {"payload": {"notes": "Synthetic tired legs"}}, ["local_checkin"]), {"output_text": "Gespeichert."}]
        result, _ = self.turn("Die Beine sind heute schwer", steps, turn="same-turn")
        replay, model = self.turn("Die Beine sind heute schwer", [], turn="same-turn")
        self.assertEqual(result, replay)
        model.assert_not_called()

    def test_automatic_advice_cannot_write(self):
        result, model = self.turn("Morgen-Check-in", [lambda _: self.call("save_checkin", {"payload": {}}, ["local_checkin"]),
            {"output_text": "Beratung."}], allow_mutations=False)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(all(tool["name"] in server.STRUCTURED_READ_ONLY_TOOLS for tool in model.call_args_list[0].args[0]["tools"]))

    def test_invalid_arguments_can_be_repaired_in_same_dialogue(self):
        result, model = self.turn("Beine schwer", [
            lambda _: self.call("save_checkin", {"payload": {"notes": "Synthetic"}}),
            lambda _: self.call("save_checkin", {"payload": {"notes": "Synthetic"}}, ["local_checkin"]),
            {"output_text": "Gespeichert."},
        ])
        self.assertEqual(model.call_count, 3)
        self.assertTrue(result["command_receipts"][-1]["result"]["ok"])
        self.assertEqual(result["status"], "completed")

    def test_repaired_planning_scope_finishes_without_false_failure_and_replays(self):
        period = {"start": "2026-09-12", "end": "2026-09-14"}
        workouts = [
            {**self.workout("2026-09-12", "100 km flach"), "sport": "Ride"},
            {**self.workout("2026-09-14", "Recovery 7 km"), "sport": "Run"},
        ]
        def apply(scope):
            return self.call("apply_training_patch", {
                "workouts": workouts, "changes": [], "expected_revision": self.state()["planning_revision"],
            }, scope, period)
        result, _ = self.turn("Samstag 100 km flach, Montag Recoverylauf", [
            lambda _: apply(["workout:new"]), lambda _: self.call("read_training_state"),
            lambda _: apply(["local_plan"]), {"output_text": "Beide Einheiten sind gespeichert."},
        ], turn="scope-repaired")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["pending_operations"], [])
        self.assertEqual(result["message"]["content"], "Beide Einheiten sind gespeichert.")
        failed = result["command_receipts"][0]
        self.assertEqual(failed["result"]["reason"], "request_scope")
        self.assertTrue(failed["resolved"])
        self.assertEqual(len(self.state()["planned_units"]), 2)
        self.assertIsNone(json.loads(server.get_kv("coach_pending_request")))
        replay, model = self.turn("Samstag 100 km flach, Montag Recoverylauf", [], turn="scope-repaired")
        model.assert_not_called()
        self.assertEqual(replay, result)
        self.assertEqual(len(self.state()["planned_units"]), 2)

    def test_other_workout_success_does_not_resolve_invalid_scope(self):
        period = {"start": "2026-09-12", "end": "2026-09-14"}
        def apply(day, scope):
            return self.call("apply_training_patch", {
                "workouts": [self.workout(day)], "changes": [],
                "expected_revision": self.state()["planning_revision"],
            }, scope, period)
        result, _ = self.turn("Samstag und Montag planen", [
            lambda _: apply("2026-09-12", ["workout:new"]),
            lambda _: apply("2026-09-14", ["local_plan"]), {"output_text": "Alles gespeichert."},
        ])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pending_operations"], ["apply_training_patch"])
        self.assertFalse(result["command_receipts"][0]["resolved"])
        self.assertIn("Ein Teil des Auftrags", result["message"]["content"])
        self.assertEqual([unit["date"] for unit in self.state()["planned_units"]], ["2026-09-14"])

    def test_invalid_scope_after_success_remains_an_unresolved_failure(self):
        period = {"start": "2026-09-12", "end": "2026-09-12"}
        def apply(scope):
            return self.call("apply_training_patch", {
                "workouts": [self.workout("2026-09-12")], "changes": [],
                "expected_revision": self.state()["planning_revision"],
            }, scope, period)
        result, _ = self.turn("Samstag planen", [lambda _: apply(["local_plan"]),
            lambda _: apply(["workout:new"]), {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["command_receipts"][-1]["resolved"])
        self.assertEqual(len(self.state()["planned_units"]), 1)

    def test_request_provenance_rejects_assistant_or_missing_current_message(self):
        server.add_message("user", "Synthetic request")
        value = self.request(["local_checkin"])
        current = value["source_message_ids"][0]
        for ids in ([current + 1], [current - 1], [], [True]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_request({**value, "source_message_ids": ids}, {current}, current)

    def test_foreign_drafts_are_not_candidates(self):
        server._stage_coach_artifact("foreign", "foreign-turn", {"workouts": [self.workout()], "plan_name": "Foreign"})
        self.assertEqual(server.coach_dialogue_artifact_refs(), [])

    def test_all_mutating_tool_schemas_carry_request_provenance(self):
        exempt = server.STRUCTURED_READ_ONLY_TOOLS | {"clarify_coach_request", "cancel_coach_request"}
        for tool in server.COACH_DIALOGUE_TOOLS:
            if tool["name"] not in exempt:
                self.assertIn("_request", tool["parameters"]["required"], tool["name"])

    def test_short_conversational_variants_do_not_need_keyword_permission(self):
        for message in ("Ja, so", "dann Mittwoch", "mach die Woche etwas leichter", "oberkrper bitte dienstag", "Die zweite", "nicht Donnerstag, Dienstag"):
            with self.subTest(message=message):
                result, model = self.turn(message, [lambda _: self.call("list_planned_workouts"), {"output_text": "Aktuellen Plan gelesen."}])
                self.assertEqual(result["status"], "completed")
                self.assertEqual(model.call_args_list[0].args[0]["tool_choice"], "auto")
                self.assertEqual(result["command_receipts"][0]["tool"], "list_planned_workouts")

    def test_hypothetical_reply_preserves_pending_request_without_writes(self):
        server.set_kv("coach_pending_request", json.dumps({"source_message_ids": [], "summary": "Einheit verschieben", "question": "Dienstag oder Mittwoch?"}))
        result, _ = self.turn("Was wäre wenn ich stattdessen ausruhe?", [{"output_text": "Ein Ruhetag wäre eine Option."}])
        self.assertEqual(result["command_receipts"], [])
        self.assertIsNotNone(json.loads(server.get_kv("coach_pending_request")))

    def test_two_matching_units_can_be_disambiguated_by_question(self):
        server.save_workout_library_entries([self.workout("2026-09-08"), self.workout("2026-09-11")])
        before = self.state()
        def question(_):
            return self.call("clarify_coach_request", {"source_message_ids": [server.list_messages()[-1]["id"]],
                "summary": "Oberkörper verschieben", "question": "Meinst du Oberkörper am Dienstag oder Freitag?"})
        result, _ = self.turn("Die Oberkörpereinheit bitte verschieben", [lambda _: self.call("read_training_state"), question, {"output_text": "Welche?"}])
        self.assertEqual(result["message"]["content"], "Meinst du Oberkörper am Dienstag oder Freitag?")
        self.assertEqual(self.state(), before)

    def test_competition_edit_uses_resolved_id_without_literal_name(self):
        competition = server.save_coach_competition({"name": "Synthetic Giro", "event_date": "2026-10-03", "sport": "Ride", "priority": "A"})
        competition_id = competition.get("competition", competition).get("id")
        if not competition_id:
            competition_id = server.list_competitions()[0]["id"]
        result, _ = self.turn("Den bitte einen Tag später", [lambda _: self.call("save_competition", {
            "payload": {"competition_id": competition_id, "event_date": "2026-10-04"}}, [f"competition:{competition_id}"]), {"output_text": "Auf den 4. Oktober verschoben."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(server.list_competitions()[0]["event_date"], "2026-10-04")

    def test_different_target_id_cannot_escape_action_scope(self):
        for name in ("First", "Second"):
            server.save_coach_competition({"name": name, "event_date": "2026-10-03", "sport": "Ride", "priority": "A"})
        one, two = server.list_competitions()
        result, _ = self.turn("Den ersten entfernen", [lambda _: self.call("delete_competition", {"competition_id": two["id"]},
            [f"competition:{one['id']}"]), {"output_text": "Nicht entfernt."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(server.list_competitions()), 2)

    def test_plan_create_and_explicit_sync_use_separate_step_targets(self):
        before = self.state()
        def create(_):
            return self.call("apply_training_patch", {"changes": [], "workouts": [self.workout("2026-09-08")],
                "expected_revision": before["planning_revision"]}, ["local_plan"], {"start": "2026-09-08", "end": "2026-09-08"})
        result, _ = self.turn("Morgen Oberkörper, danach zu Intervals übertragen", [create,
            lambda _: self.call("start_intervals_plan_sync", {}, ["intervals_sync"], target="intervals", remote_write=True, sync_scope="created"),
            {"output_text": "Lokal gespeichert, Synchronisierung beauftragt."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([step["request"]["target"] for step in result["command_receipts"]], ["local", "intervals"])
        self.assertEqual(len(result["sync_job_ids"]), 1)
        with server.database() as db:
            job = db.execute("SELECT payload FROM sync_jobs WHERE id=?", (result["sync_job_ids"][0],)).fetchone()
        self.assertEqual(len(json.loads(job["payload"])["entries"]), 1)

    def test_sync_followup_can_read_job_and_inspect_duplicates(self):
        server.save_workout_library_entries([self.workout("2026-09-08")])
        def inspect(payload):
            output = json.loads(payload["input"][0]["output"])
            return self.call("get_sync_job", {"job_id": output["sync_job_id"]})
        result, _ = self.turn("Sync zu intervals.icu durchführen", [
            lambda _: self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                               target="intervals", remote_write=True, sync_scope="all_pending"),
            inspect, lambda _: self.call("inspect_activity_duplicates"),
            {"output_text": "Synchronisierung beauftragt."},
        ])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(all(step["result"]["ok"] for step in result["command_receipts"]))
        self.assertEqual(server.sync_job_state(result["sync_job_ids"][0])["status"], "queued")

    def test_sync_followup_failure_distinguishes_coach_interruption_and_keeps_job(self):
        server.save_workout_library_entries([self.workout("2026-09-08")])
        def broken(_):
            raise server.AppError(503, "Synthetic model unavailable", reason="provider_unavailable")
        with patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:
            result, _ = self.turn("Sync zu intervals.icu durchführen", [
                lambda _: self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                                   target="intervals", remote_write=True, sync_scope="all_pending"), broken,
            ], turn="sync-followup-failure")
            replay, model = self.turn("Sync zu intervals.icu durchführen", [], turn="sync-followup-failure")
        enqueue.assert_called_once()
        model.assert_not_called()
        self.assertEqual(replay, result)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pending_operations"], [])
        self.assertEqual(result["diagnostic_error"]["reason"], "provider_unavailable")
        text = result["message"]["content"]
        self.assertIn("Die weitere Coach-Verarbeitung wurde unterbrochen", text)
        self.assertIn("Plansynchronisierung beauftragt", text)
        self.assertIn("unabhängig vom Coach", text)
        self.assertIn("noch nicht bestätigt", text)
        self.assertNotIn("Der Coach-Auftrag konnte nicht abgeschlossen werden", text)
        self.assertEqual(server.sync_job_state(result["sync_job_ids"][0])["status"], "queued")

    def test_failed_plan_cannot_sync_created_entries(self):
        with patch.object(server, "enqueue_sync_job") as enqueue:
            result, _ = self.turn("Planen und übertragen", [lambda _: self.call("start_intervals_plan_sync", {}, ["intervals_sync"],
                target="intervals", remote_write=True, sync_scope="created"), {"output_text": "Noch nicht gespeichert."}])
        enqueue.assert_not_called()
        self.assertEqual(result["status"], "failed")

    def test_all_pending_sync_is_not_narrowed_to_model_entries(self):
        server.save_workout_library_entries([self.workout("2026-09-08"), self.workout("2026-09-09")])
        result, _ = self.turn("Alle offenen Einheiten übertragen", [lambda _: self.call("start_intervals_plan_sync", {"entries": []},
            ["intervals_sync", "local_plan"], target="intervals", remote_write=True, sync_scope="all_pending"), {"output_text": "Alle beauftragt."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["command_receipts"][0]["result"]["entries"], 2)

    def test_selected_existing_planned_unit_sync_accepts_planned_unit_scope(self):
        planned = server.save_workout_library_entries([self.workout("2026-09-08")])[0]
        entry = server._pending_plan_push_entries()[0]
        result, _ = self.turn("Nur diese Einheit übertragen", [lambda _: self.call(
            "start_intervals_plan_sync", {"entries": [entry]},
            ["intervals_sync", f"planned_unit:{planned['id']}"], target="intervals",
            remote_write=True, sync_scope="selected",
        ), {"output_text": "Synchronisierung beauftragt."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["sync_job_ids"]), 1)

    def test_successful_morning_quick_action_is_marked_complete_without_word_matching(self):
        server.enqueue_background_coach_job(
            "Natural wording without a fixed trigger", "morning-quick", "synthetic-session",
            request_kind="morning_checkin",
        )
        job = server._claim_background_coach_job()
        def complete_command(*args, **kwargs):
            with server.database() as db:
                db.execute("UPDATE coach_commands SET status='completed' WHERE client_turn_id='morning-quick'")
            return {"status": "completed", "message": {"id": 1}}
        with patch.object(server, "_restore_coach_session_csrf_hash", return_value="synthetic-session"), patch.object(
            server, "chat_with_coach", side_effect=complete_command,
        ):
            server._run_background_coach_job(job)
        self.assertEqual(server.get_kv("morning_checkin_date"), "2026-09-07")
        self.assertEqual(server.get_kv("morning_checkin_status"), "ready")
        self.assertFalse(server.coach_quick_actions_state()["morning_checkin"])
        with server.database() as db:
            row = db.execute("SELECT receipt FROM coach_commands WHERE client_turn_id='morning-quick'").fetchone()
        self.assertFalse(json.loads(row["receipt"])["coach_quick_actions"]["morning_checkin"])

    def test_morning_quick_action_stays_pending_while_coach_awaits_clarification(self):
        server.enqueue_background_coach_job(
            "Natural wording without a fixed trigger", "morning-question", "synthetic-session",
            request_kind="morning_checkin",
        )
        job = server._claim_background_coach_job()

        def complete_with_question(*args, **kwargs):
            with server.database() as db:
                db.execute("UPDATE coach_commands SET status='completed' WHERE client_turn_id='morning-question'")
            return {"status": "completed", "message": {"id": 1}, "awaiting_clarification": True}

        with patch.object(server, "_restore_coach_session_csrf_hash", return_value="synthetic-session"), patch.object(
            server, "chat_with_coach", side_effect=complete_with_question,
        ):
            server._run_background_coach_job(job)
        self.assertNotEqual(server.get_kv("morning_checkin_status"), "ready")
        self.assertTrue(server.coach_quick_actions_state()["morning_checkin"])

    def test_chat_reset_cancels_queued_background_turn_without_reappearing_message(self):
        job = server.enqueue_background_coach_job(
            "Plan something", "queued-before-reset", "synthetic-session",
            operation_id="operation-before-reset",
        )
        self.assertEqual(job["status"], "queued")
        server.reset_coach_chat()
        self.assertIsNone(server._claim_background_coach_job())
        self.assertEqual(server.list_messages(), [])
        with server.database() as db:
            command = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id='queued-before-reset'"
            ).fetchone()
        self.assertEqual(command["status"], "completed")
        self.assertEqual(json.loads(command["receipt"])["status"], "cancelled")
        self.assertTrue(server.COACH_JOB_CANCEL_EVENTS["operation-before-reset"].is_set())

    def test_same_effect_and_call_are_idempotent_inside_turn(self):
        def save(_):
            return self.call("save_checkin", {"payload": {"notes": "Synthetic tired"}}, ["local_checkin"], call_id="same-call")
        with patch.object(server, "save_coach_checkin", wraps=server.save_coach_checkin) as save_checkin:
            result, _ = self.turn("Müde heute", [save, save, {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "completed")
        save_checkin.assert_called_once()

    def test_same_call_id_with_changed_payload_is_rejected(self):
        result, _ = self.turn("Müde heute", [
            lambda _: self.call("save_checkin", {"payload": {"notes": "First"}}, ["local_checkin"], call_id="same-call"),
            lambda _: self.call("save_checkin", {"payload": {"notes": "Second"}}, ["local_checkin"], call_id="same-call"),
            {"output_text": "Nicht erneut gespeichert."},
        ])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["command_receipts"][-1]["result"]["reason"], "tool_call_conflict")

    def test_background_resumes_response_and_committed_effect_without_replaying(self):
        turn_id = "background-resume"
        server.enqueue_background_coach_job("Müde heute", turn_id, "synthetic-session")
        call = self.call("save_checkin", {"payload": {"notes": "Synthetic tired"}}, ["local_checkin"], call_id="saved-call")["output"][0]
        args = json.loads(call["arguments"])
        prior = {"call_id": call["call_id"], "tool": call["name"], "effect_key": server._dialogue_effect_key(call["name"], args),
                 "result": {"ok": True, "status": "saved"}}
        server._merge_coach_command_receipt(turn_id, {"openai_response_id": "synthetic-response", "command_receipts": [prior]})
        with patch.object(server, "_structured_coach_tool_result", side_effect=AssertionError("must not replay")):
            result, model = self.turn("Müde heute", [{"output": [call]}, {"output_text": "Bereits gespeichert."}], turn=turn_id, background_job=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_args_list[0].kwargs["response_id"], "synthetic-response")

    def test_background_replays_checkpointed_outputs_before_new_response(self):
        turn_id = "background-outputs"
        server.enqueue_background_coach_job("Wie geht es weiter?", turn_id, "synthetic-session")
        outputs = [{"type": "function_call_output", "call_id": "read", "output": '{"ok":true}'}]
        server._merge_coach_command_receipt(turn_id, {"openai_response_id": "old-response", "pending_tool_outputs": outputs})
        result, model = self.turn("Wie geht es weiter?", [{"output_text": "Fortgesetzt."}], turn=turn_id, background_job=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_args.args[0]["input"], outputs)
        self.assertIsNone(model.call_args.kwargs["response_id"])

    def test_tool_round_limit_submits_outputs_and_keeps_provider_selection(self):
        with patch.object(server, "COACH_TOOL_MAX_ROUNDS", 1):
            result, model = self.turn("Plan ansehen", [lambda _: self.call("read_training_state"), {"output_text": "Plan gelesen."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_args_list[1].args[0]["tool_choice"], "none")
        self.assertEqual(model.call_args_list[1].args[0]["input"][0]["type"], "function_call_output")
        self.assertEqual(model.call_args_list[0].args[0]["model"], model.call_args_list[1].args[0]["model"])

    def test_unknown_tool_and_malformed_arguments_have_no_effect(self):
        before = self.state()
        result, _ = self.turn("Weiter", [{"output": [{"type": "function_call", "name": "unknown", "call_id": "bad", "arguments": "{"}]},
            {"output_text": "Nicht ausgeführt."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(before, self.state())

    def test_summary_failure_preserves_effect_and_replays_receipt(self):
        def broken(_):
            raise server.AppError(503, "Synthetic model unavailable", reason="provider_unavailable")
        result, _ = self.turn("Heute müde", [lambda _: self.call("save_checkin", {"payload": {"notes": "Synthetic tired"}},
            ["local_checkin"]), broken], turn="summary-failure")
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["command_receipts"][0]["result"]["ok"])
        replay, model = self.turn("Heute müde", [], turn="summary-failure")
        model.assert_not_called()
        self.assertEqual(replay, result)

    def test_cancel_before_tools_has_no_local_effect(self):
        import threading
        cancelled = threading.Event()
        def cancel(_):
            cancelled.set()
            return self.call("save_checkin", {"payload": {"notes": "Synthetic"}}, ["local_checkin"])
        with patch.object(server, "save_coach_checkin") as save:
            result, _ = self.turn("Heute müde", [cancel], cancel_event=cancelled)
        save.assert_not_called()
        self.assertEqual(result["status"], "cancelled")

    def test_foreign_session_cannot_replay_receipt(self):
        self.turn("Wie geht es weiter?", [{"output_text": "Synthetic advice"}], turn="owned-turn")
        with self.assertRaises(server.AppError) as raised:
            server.chat_with_coach("Weiter", client_turn_id="owned-turn", session_csrf_hash="other-session")
        self.assertEqual(raised.exception.reason, "command_scope_denied")

    def test_local_draft_commit_survives_provider_conversation_recovery(self):
        server.add_message("user", "Ein Entwurf bitte")
        with server.database() as db:
            origin = server.CHAT_REPOSITORY.add(db, "user", "Synthetic draft", client_turn_id="draft-source")
        draft = server._stage_coach_artifact("old-conversation", "draft-source", {"plan_name": "Synthetic", "workouts": [self.workout()]})
        def commit(_):
            call = self.call("commit_training_plan", {"artifact_id": draft["artifact_id"]}, ["artifact:" + draft["artifact_id"]],
                {"start": "2026-09-09", "end": "2026-09-09"})
            args = json.loads(call["output"][0]["arguments"])
            args["_request"]["source_message_ids"].append(origin["id"])
            call["output"][0]["arguments"] = json.dumps(args)
            return call
        def stale(_):
            raise server.AppError(400, "Synthetic stale conversation", reason="conversation_state_invalid")
        with patch.object(server, "replace_stale_openai_conversation", return_value="new-conversation"):
            result, _ = self.turn("Ja, so übernehmen", [stale, commit, {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.state()["planned_units"]), 1)
        with server.database() as db:
            row = db.execute("SELECT conversation_id FROM coach_plan_artifacts WHERE id=?", (draft["artifact_id"],)).fetchone()
        self.assertEqual(row["conversation_id"], "new-conversation")

    def test_garmin_refresh_and_job_read_use_current_tool_results(self):
        def job(_):
            with server.database() as db:
                row = db.execute("SELECT id FROM sync_jobs WHERE provider='garmin'").fetchone()
            return self.call("get_sync_job", {"job_id": row["id"]})
        result, _ = self.turn("Bitte Garmin aktualisieren", [lambda _: self.call("start_provider_refresh", {"days": 3},
            ["garmin_refresh"], target="garmin"), job, {"output_text": "Der Abruf ist beauftragt."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["command_receipts"][0]["result"]["status"], "queued")
        self.assertTrue(result["command_receipts"][1]["result"]["ok"])

    def test_revision_conflict_can_be_corrected_after_reading_current_state(self):
        before = self.state()
        def apply(revision):
            return self.call("apply_training_patch", {"expected_revision": revision, "workouts": [self.workout()], "changes": []},
                ["local_plan"], {"start": "2026-09-09", "end": "2026-09-09"})
        result, _ = self.turn("Dann Mittwoch Oberkörper", [lambda _: apply(before["planning_revision"] + 1),
            lambda _: self.call("read_training_state"), lambda _: apply(before["planning_revision"]), {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.state()["planned_units"]), 1)

    def test_repeated_read_fetches_current_revision_instead_of_cached_state(self):
        initial = self.state()["planning_revision"]
        def reread(_):
            with server.database() as db:
                server._bump_planning_revision(db)
            return self.call("read_training_state")
        result, _ = self.turn("Bitte den aktuellen Stand prüfen", [lambda _: self.call("read_training_state"), reread,
            {"output_text": "Aktuellen Stand gelesen."}])
        self.assertEqual([step["result"]["planning_revision"] for step in result["command_receipts"]], [initial, initial + 1])

    def test_rephrasing_request_metadata_does_not_duplicate_same_write(self):
        def again(_):
            response = self.call("save_checkin", {"payload": {"notes": "Synthetic tired"}}, ["local_checkin"])
            args = json.loads(response["output"][0]["arguments"])
            args["_request"]["summary"] = "Same request rephrased by the model"
            response["output"][0]["arguments"] = json.dumps(args)
            return response
        with patch.object(server, "save_coach_checkin", wraps=server.save_coach_checkin) as save:
            result, _ = self.turn("Müde heute", [lambda _: self.call("save_checkin", {"payload": {"notes": "Synthetic tired"}},
                ["local_checkin"]), again, {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "completed")
        save.assert_called_once()

    def test_new_workout_requires_local_creation_scope(self):
        before = self.state()
        result, _ = self.turn("Morgen Oberkörper", [lambda _: self.call("apply_training_patch", {
            "workouts": [self.workout("2026-09-08")], "expected_revision": before["planning_revision"]}, [],
            {"start": "2026-09-08", "end": "2026-09-08"}), {"output_text": "Nicht gespeichert."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state(), before)

    def test_failed_local_step_blocks_following_all_pending_push(self):
        server.save_workout_library_entries([self.workout()])
        result, _ = self.turn("Plan ändern und alles übertragen", [lambda _: self.call("apply_training_patch", {
            "workouts": [self.workout()], "expected_revision": -1}, ["local_plan"],
            {"start": "2026-09-09", "end": "2026-09-09"}),
            lambda _: self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"], target="intervals",
                remote_write=True, sync_scope="all_pending"), {"output_text": "Nicht übertragen."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["sync_job_ids"], [])

    def test_archived_plan_cannot_be_replaced_as_current_plan(self):
        server.save_workout_library_entries([self.workout()], plan_name="Archived")
        plan = server.list_training_plans()[0]
        with server.database() as db:
            db.execute("UPDATE training_plans SET status='archived' WHERE id=?", (plan["id"],))
        before = self.state()
        result, _ = self.turn("Diesen Plan ersetzen", [lambda _: self.call("replace_training_plan", {
            "payload": {"plan_name": "New", "workouts": [self.workout("2026-09-08")]}, "expected_revision": before["planning_revision"]},
            [f"training_plan:{plan['id']}"], {"start": "2026-09-08", "end": "2026-09-09"}), {"output_text": "Nicht ersetzt."}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
