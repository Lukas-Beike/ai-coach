"""A failed provider response must preserve an already queued sync."""
import json
import unittest
from unittest.mock import Mock, patch

import test_coach_dialogue as dialogue

server = dialogue.server


class CoachResponseFailureTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    workout = dialogue.CoachDialogueTests.workout
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call

    def test_background_rate_limit_retries_summary_with_parent_and_one_sync(self):
        server.local_plan_creation_service().save([self.workout("2026-09-08")])
        turn_id = "synthetic-sync-rate-retry"
        message = "Bitte den Plan erneut synchronisieren"
        server.coach_job_submission_service().enqueue(message, turn_id, "synthetic-session")
        payloads = []

        def create(payload, **kwargs):
            payloads.append(payload)
            if kwargs.get("on_response_id") is not None:
                kwargs["on_response_id"](f"resp_{len(payloads)}")
            if len(payloads) == 1:
                return {**self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                                   target="intervals", remote_write=True, sync_scope="all_pending"),
                        "id": "resp_sync", "status": "completed"}
            if len(payloads) == 2:
                raise server.AppError(429, "rate limited", reason="rate_limit_exceeded")
            return {"id": "resp_final", "status": "completed", "output_text": "Sync beauftragt."}

        with patch.object(server, "coach_conversation_provision_service", return_value=Mock(ensure=Mock(return_value="synthetic-conversation"))), \
                patch("backend.coach.context.CoachTrainingContextService.build", return_value="Synthetic local context"), \
                patch.object(server.openai_provider.OpenAIResponsesClient, "background", side_effect=create), \
                patch.object(server.time, "sleep"), \
                patch.object(
                    server.SyncJobQueueService,
                    "enqueue",
                    wraps=server.sync_job_queue_service().enqueue,
                ) as enqueue:
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
        server.local_plan_creation_service().save([self.workout("2026-09-08")])
        turn_id = "sync-provider-response-failure"
        message = "Sync zu intervals.icu durchführen"
        server.coach_job_submission_service().enqueue(message, turn_id, "synthetic-session")
        responses = 0

        def create(payload, **kwargs):
            nonlocal responses
            responses += 1
            if kwargs.get("on_response_id") is not None:
                kwargs["on_response_id"](f"resp_{responses}")
            if responses == 1:
                return {**self.call("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"],
                                   target="intervals", remote_write=True, sync_scope="all_pending"),
                        "id": "resp_sync", "status": "completed"}
            self.assertEqual(responses, 2)
            return server.provider_state_service().validate_openai_response("/responses", failed_response)

        failed_response = {"id": "resp_summary", "status": "failed", "error": {
            "code": "server_error", "message": "DO_NOT_EXPORT_PROVIDER_CONTENT",
        }}
        with patch.object(server, "coach_conversation_provision_service", return_value=Mock(ensure=Mock(return_value="synthetic-conversation"))), \
                patch("backend.coach.context.CoachTrainingContextService.build", return_value="Synthetic local context"), \
                patch.object(server.openai_provider.OpenAIResponsesClient, "background", side_effect=create), \
                patch.object(
                    server.SyncJobQueueService,
                    "enqueue",
                    wraps=server.sync_job_queue_service().enqueue,
                ) as enqueue:
            receipt = server.chat_with_coach(message, client_turn_id=turn_id,
                                           session_csrf_hash="synthetic-session", background_job=True)
            replay = server.chat_with_coach(message, client_turn_id=turn_id,
                                          session_csrf_hash="synthetic-session", background_job=True)
        enqueue.assert_called_once()
        self.assertEqual(responses, 2)
        self.assertEqual(receipt, replay)
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["pending_operations"], [])
        self.assertEqual(receipt["diagnostic_error"]["reason"], "response_error")
        self.assertEqual(receipt["diagnostic_error"]["provider_error_code"], "server_error")
        self.assertIn("KI-Dienst konnte die Antwort nicht fertigstellen", receipt["message"]["content"])
        self.assertIn("erneut", receipt["message"]["content"])
        self.assertIn("Plansynchronisierung beauftragt", receipt["message"]["content"])
        self.assertIn("noch nicht bestätigt", receipt["message"]["content"])
        self.assertEqual(
            server.sync_job_queue_service().state(receipt["sync_job_ids"][0])[
                "status"
            ],
            "queued",
        )
        history = server.coach_diagnostic_history_service().history()
        self.assertEqual(history[0]["error"]["provider_error_code"], "server_error")
        status = server.provider_state_service().summary("openai")["status"]
        self.assertEqual(status["provider_error_code"], "server_error")
        self.assertNotIn("DO_NOT_EXPORT_PROVIDER_CONTENT", json.dumps([receipt, history, status]))

    def test_unknown_response_error_codes_and_messages_are_not_exported(self):
        for code in ("DO_NOT_EXPORT_PROVIDER_CONTENT", ["server_error"], {"secret": "content"}, None):
            with self.subTest(code_type=type(code).__name__), self.assertRaises(server.AppError) as raised:
                server.provider_state_service().validate_openai_response("/responses", {"error": {
                    "code": code, "message": "DO_NOT_EXPORT_PROVIDER_CONTENT",
                }})
            self.assertEqual(raised.exception.reason, "response_error")
            metadata = server.observability.safe_diagnostic_error(raised.exception)
            self.assertNotIn("provider_error_code", metadata)
            status = server.provider_state_service().summary("openai")["status"]
            self.assertNotIn("provider_error_code", status)
            self.assertNotIn("DO_NOT_EXPORT_PROVIDER_CONTENT", json.dumps([metadata, status]))
