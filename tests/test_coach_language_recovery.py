"""Execution regressions with synthetic model outputs, not an LLM accuracy eval."""
import json
import threading
import unittest
from unittest.mock import patch

from test_coach_dialogue import DialogueHarness, server
from backend.providers.workout_text import canonical_workout_zones, structured_steps


def limited(_):
    error = server.AppError(502, "Synthetic provider error", reason="response_error")
    error.provider_error_code = "rate_limit_exceeded"
    raise error


class CoachLanguageRecoveryTests(DialogueHarness, unittest.TestCase):
    def test_response_chain_stops_at_turn_boundary_and_keeps_local_dialogue(self):
        def read(_):
            return {**self.call("read_training_state"), "id": "resp_read"}
        first, model = self.turn("Zeig mir den Plan", [read, {"id": "resp_final", "output_text": "Montag ist ein Lauf geplant."}])
        initial, followup = [call.args[0] for call in model.call_args_list]
        self.assertNotIn("conversation", initial)
        self.assertNotIn("previous_response_id", initial)
        self.assertEqual(followup["previous_response_id"], "resp_read")
        self.assertNotIn("conversation", followup)
        self.assertTrue(followup["instructions"])
        _, next_model = self.turn("Den bitte sehr locker", [{"output_text": "Der Lauf ist gemeint."}])
        fresh = next_model.call_args.args[0]
        self.assertNotIn("previous_response_id", fresh)
        self.assertNotIn("conversation", fresh)
        dialogue = json.loads(fresh["input"])["dialogue"]
        self.assertTrue(any(row["content"] == first["message"]["content"] for row in dialogue["messages"]))

    def test_rate_limit_retries_response_after_sync_without_requeuing(self):
        server.save_workout_library_entries([self.workout()])
        def sync(_):
            return {**self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                                target="intervals", remote_write=True, sync_scope="all_pending"), "id": "resp_sync"}
        with patch.object(server.time, "sleep") as sleep, patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:
            result, model = self.turn("Bitte den Plan nochmal übertragen", [sync, limited, {"id": "resp_final", "output_text": "Sync beauftragt."}])
        self.assertEqual(result["status"], "completed")
        enqueue.assert_called_once()
        sleep.assert_called_once_with(5)
        self.assertEqual(model.call_args_list[1].args[0], model.call_args_list[2].args[0])
        self.assertEqual(model.call_args.args[0]["previous_response_id"], "resp_sync")
        self.assertEqual(server.sync_job_state(result["sync_job_ids"][0])["status"], "queued")
        _, next_model = self.turn("Und, ist er fertig?", [{"output_text": "Ich prüfe den Auftrag."}])
        previous = json.loads(next_model.call_args.args[0]["input"])["dialogue"]["confirmed_results"][0]
        self.assertEqual(previous["sync_job_ids"], result["sync_job_ids"])
        self.assertIn("intervals_sync", previous["steps"][0]["scope"])

    def test_rate_limit_exhaustion_has_specific_message_and_no_false_effect(self):
        with patch.object(server.time, "sleep") as sleep:
            result, model = self.turn("Bitte synchronisieren", [limited, limited, limited])
        self.assertEqual(model.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(result["status"], "failed")
        self.assertIn("Anfragelimit", result["message"]["content"])
        self.assertEqual(result["sync_job_ids"], [])

    def test_rate_limit_wait_can_be_cancelled(self):
        event = threading.Event()
        with patch.object(event, "wait", side_effect=lambda _: event.set()):
            result, model = self.turn("Bitte synchronisieren", [limited], cancel_event=event)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "cancelled")

    def test_background_recovery_retries_same_tool_output_with_same_parent(self):
        turn = "synthetic-retry-recovery"
        server.enqueue_background_coach_job("Bitte fortsetzen", turn, "synthetic-session")
        outputs = [{"type": "function_call_output", "call_id": "saved", "output": '{"ok":true}'}]
        server._merge_coach_command_receipt(turn, {"openai_response_id": "resp_waiting", "response_input": outputs,
                                                   "previous_response_id": "resp_tool"})
        with patch.object(server.time, "sleep"):
            result, model = self.turn("Bitte fortsetzen", [limited, {"id": "resp_final", "output_text": "Fertig."}], turn=turn, background_job=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_args_list[0].kwargs["response_id"], "resp_waiting")
        self.assertIsNone(model.call_args_list[1].kwargs["response_id"])
        self.assertEqual(model.call_args.args[0]["input"], outputs)
        self.assertEqual(model.call_args.args[0]["previous_response_id"], "resp_tool")

    def test_failed_answer_keeps_observed_sync_status(self):
        server.save_workout_library_entries([self.workout()])
        job = server.enqueue_sync_job("intervals", "plan_push", {"entries": server._pending_plan_push_entries()})
        with server.database() as db:
            db.execute("UPDATE sync_jobs SET status='completed' WHERE id=?", (job["id"],))
        with patch.object(server.time, "sleep"):
            result, _ = self.turn("Ist der Plan übertragen?", [lambda _: self.call("get_sync_job", {"job_id": job["id"]}), limited, limited, limited])
        self.assertIn("erfolgreich abgeschlossen", result["message"]["content"])
        self.assertIn("Anfragelimit", result["message"]["content"])
        self.assertEqual(result["sync_job_ids"], [])

    def test_workout_repair_finishes_in_same_turn_preserving_identity_and_distance(self):
        original = {**self.workout("2026-09-14", "Optionaler Recovery Run"), "sport": "Run",
                    "description": "- 6km Z1 HR", "target": "HR", "duration_minutes": 40}
        unit = server.save_workout_library_entries([original])[0]
        before = self.state()
        args = {"expected_revision": before["planning_revision"], "changes": [{
            "local_id": unit["id"], "expected_payload_hash": before["planned_units"][0]["expected_payload_hash"],
            "action": "update", "description": "- 1km locker\n- 6km Z1 HR\n- 1km locker", "duration_minutes": 50,
        }]}
        def change(_):
            return self.call("apply_training_patch", args, ["planned_unit:" + unit["id"]], {"start": "2026-09-14", "end": "2026-09-14"})
        def repair(payload):
            self.assertEqual(self.state(), before)
            self.assertEqual(json.loads(payload["input"][0]["output"])["reason"], "missing_workout_target")
            args["changes"][0]["description"] = "- 1km Z1 HR\n- 6km Z1 HR\n- 1km Z1 HR"
            return change(payload)
        result, _ = self.turn("Passe den Lauf am Montag auf 8km sehr locker an.", [change, repair, {"output_text": "8 km sehr locker in deiner HF-Zone 1 gespeichert."}])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["command_receipts"][0]["resolved"])
        saved = self.state()["planned_units"][0]
        self.assertEqual(saved["local_id"], unit["id"])
        self.assertEqual(saved["name"], original["name"])
        with server.database() as db:
            payload = json.loads(db.execute("SELECT payload FROM planned_units WHERE local_id=?", (unit["id"],)).fetchone()["payload"])
        self.assertEqual(sum(step["distance"] for step in structured_steps(payload["description"])), 8000)
        self.assertEqual(result["sync_job_ids"], [])

    def test_explicit_zone_range_is_normalized_before_local_save(self):
        for spelling in ("Zone 1-2 HR", "Z1–2 HR", "Zone 1 – Zone 2 HR", "Z1-Z2 HR"):
            with self.subTest(spelling=spelling):
                workout = server.normalize_workout({**self.workout(), "sport": "Run", "target": "HR", "description": "- 8km " + spelling})
                server.validate_workout_description(workout)
                self.assertEqual(workout["description"], "- 8km Z1-Z2 HR")
        self.assertEqual(canonical_workout_zones("- 8km locker\nHinweis: Zone 1-2 HR"), "- 8km locker\nHinweis: Zone 1-2 HR")

    def test_zone_normalization_does_not_rewrite_cues_or_non_endurance_prose(self):
        description = "- 10m Zone 1 HR stay below Zone 2\n- 5m Zone 2 Pace"
        self.assertEqual(
            canonical_workout_zones(description),
            "- 10m Z1 HR stay below Zone 2\n- 5m Z2 Pace",
        )
        strength = "- 10m Zone 1 HR mobility circuit"
        self.assertEqual(canonical_workout_zones(strength, endurance=False), strength)

    def test_exhausted_workout_repair_does_not_ask_athlete_for_syntax(self):
        result = server.coach_failure_lines([{"tool": "apply_training_patch", "result": {
            "ok": False, "reason": "missing_workout_target", "error": "Use Z1 HR; locker is not valid"}}], {"apply_training_patch"})
        self.assertNotIn("Use Z1 HR", result)
        self.assertIn("Coach", result)
        self.assertIn("nicht gespeichert", result)
