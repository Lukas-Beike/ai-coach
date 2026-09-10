"""A failed provider response must preserve an already queued sync."""
import json
import unittest
from unittest.mock import patch

import test_coach_dialogue as dialogue

server = dialogue.server


class CoachResponseFailureTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    workout = dialogue.CoachDialogueTests.workout
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call

    def test_background_rate_limit_retries_summary_with_parent_and_one_sync(self):
        server.save_workout_library_entries([self.workout("2026-09-08")])
        turn_id = "synthetic-sync-rate-retry"
        message = "Bitte den Plan erneut synchronisieren"
        server.enqueue_background_coach_job(message, turn_id, "synthetic-session")
        payloads = []

        def create(payload):
            payloads.append(payload)
            if len(payloads) == 1:
                return {**self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                                   target="intervals", remote_write=True, sync_scope="all_pending"),
                        "id": "resp_sync", "status": "completed"}
            if len(payloads) == 2:
                return {"id": "resp_limited", "status": "queued"}
            return {"id": "resp_final", "status": "completed", "output_text": "Sync beauftragt."}

        with patch.object(server, "ensure_conversation", return_value="synthetic-conversation"), \
                patch.object(server, "build_training_context", return_value="Synthetic local context"), \
                patch.object(server, "responses_request", side_effect=create), \
                patch.object(server, "http_json", return_value={"id": "resp_limited", "status": "failed", "error": {"code": "rate_limit_exceeded"}}), \
                patch.object(server.time, "sleep"), \
                patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:
            receipt = server.chat_with_coach(message, client_turn_id=turn_id,
                                           session_csrf_hash="synthetic-session", background_job=True)
        self.assertEqual(receipt["status"], "completed")
        enqueue.assert_called_once()
        self.assertEqual(len(payloads), 3)
        self.assertEqual(payloads[1], payloads[2])
        self.assertEqual(payloads[2]["previous_response_id"], "resp_sync")
        self.assertNotIn("conversation", payloads[0])
        self.assertNotIn("previous_response_id", payloads[0])

    def test_failed_background_answer_keeps_sync_and_reports_provider_code(self):
        server.save_workout_library_entries([self.workout("2026-09-08")])
        turn_id = "sync-provider-response-failure"
        message = "Sync zu intervals.icu durchführen"
        server.enqueue_background_coach_job(message, turn_id, "synthetic-session")
        responses = 0

        def create(payload):
            nonlocal responses
            responses += 1
            if responses == 1:
                return {**self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                                   target="intervals", remote_write=True, sync_scope="all_pending"),
                        "id": "resp_sync", "status": "completed"}
            self.assertEqual(responses, 2)
            return {"id": "resp_summary", "status": "queued"}

        failed_response = {"id": "resp_summary", "status": "failed", "error": {
            "code": "server_error", "message": "DO_NOT_EXPORT_PROVIDER_CONTENT",
        }}
        with patch.object(server, "ensure_conversation", return_value="synthetic-conversation"), \
                patch.object(server, "build_training_context", return_value="Synthetic local context"), \
                patch.object(server, "responses_request", side_effect=create), \
                patch.object(server, "http_json", return_value=failed_response) as retrieve, \
                patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:
            receipt = server.chat_with_coach(message, client_turn_id=turn_id,
                                           session_csrf_hash="synthetic-session", background_job=True)
            replay = server.chat_with_coach(message, client_turn_id=turn_id,
                                          session_csrf_hash="synthetic-session", background_job=True)
        enqueue.assert_called_once()
        retrieve.assert_called_once()
        self.assertEqual(receipt, replay)
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["pending_operations"], [])
        self.assertEqual(receipt["diagnostic_error"]["reason"], "response_error")
        self.assertEqual(receipt["diagnostic_error"]["provider_error_code"], "server_error")
        self.assertIn("KI-Dienst konnte die Antwort nicht fertigstellen", receipt["message"]["content"])
        self.assertIn("erneut", receipt["message"]["content"])
        self.assertIn("Plansynchronisierung beauftragt", receipt["message"]["content"])
        self.assertIn("noch nicht bestätigt", receipt["message"]["content"])
        self.assertEqual(server.sync_job_state(receipt["sync_job_ids"][0])["status"], "queued")
        history = server.coach_diagnostic_history()
        self.assertEqual(history[0]["error"]["provider_error_code"], "server_error")
        status = json.loads(server.get_kv(server.OPENAI_STATUS_KEY))
        self.assertEqual(status["provider_error_code"], "server_error")
        self.assertNotIn("DO_NOT_EXPORT_PROVIDER_CONTENT", json.dumps([receipt, history, status]))

    def test_unknown_response_error_codes_and_messages_are_not_exported(self):
        for code in ("DO_NOT_EXPORT_PROVIDER_CONTENT", ["server_error"], {"secret": "content"}, None):
            with self.subTest(code_type=type(code).__name__), self.assertRaises(server.AppError) as raised:
                server._validate_openai_response("/responses", {"error": {
                    "code": code, "message": "DO_NOT_EXPORT_PROVIDER_CONTENT",
                }})
            self.assertEqual(raised.exception.reason, "response_error")
            metadata = server._safe_diagnostic_error(raised.exception)
            self.assertNotIn("provider_error_code", metadata)
            status = json.loads(server.get_kv(server.OPENAI_STATUS_KEY))
            self.assertNotIn("provider_error_code", status)
            self.assertNotIn("DO_NOT_EXPORT_PROVIDER_CONTENT", json.dumps([metadata, status]))
