"""A failed provider response must preserve an already queued sync."""

import json
import unittest
from unittest.mock import Mock, patch

import test_coach_dialogue as dialogue

from backend.errors import AppError
from backend.providers import openai_stream
from backend.sync import queue as sync_queue

server = dialogue.server


class CoachResponseFailureTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    workout = dialogue.CoachDialogueTests.workout
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call

    @staticmethod
    def approve_remote_write():
        proposals = server.COACH_PROPOSALS.read_service().current("synthetic-session")
        if not proposals:
            raise AssertionError("expected a pending remote approval proposal")
        confirmation = server.COACH_PROPOSALS.confirmation_service().confirm(
            proposals[0]["id"], "synthetic-session"
        )
        return server.COACH_PROPOSALS.execution_service().execute(
            confirmation["action_token"],
            "synthetic-session",
            confirmation["proposed_action"]["payload_hash"],
        )

    def test_background_rate_limit_retries_summary_with_parent_and_one_sync(self):
        server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [self.workout("2026-09-08")]
        )
        turn_id = "synthetic-sync-rate-retry"
        message = "Bitte den Plan erneut synchronisieren"
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            message, turn_id, "synthetic-session"
        )
        payloads = []

        def create(payload, *_args, **kwargs):
            payloads.append(payload)
            if kwargs.get("on_response_id") is not None:
                kwargs["on_response_id"](f"resp_{len(payloads)}")
            if len(payloads) == 1:
                return {
                    **self.call(
                        "start_intervals_plan_sync",
                        {},
                        ["local_plan", "intervals_sync"],
                        target="intervals",
                        remote_write=True,
                        sync_scope="all_pending",
                    ),
                    "id": "resp_sync",
                    "status": "completed",
                }
            if len(payloads) == 2:
                raise AppError(429, "rate limited", reason="rate_limit_exceeded")
            return {
                "id": "resp_final",
                "status": "completed",
                "output_text": "Sync beauftragt.",
            }

        with (
            patch.object(
                server.COACH_CONVERSATION,
                "provision_service",
                return_value=Mock(binding=Mock(return_value="synthetic-conversation")),
            ),
            patch(
                "backend.coach.context.CoachTrainingContextService.build",
                return_value="Synthetic local context",
            ),
            patch.object(
                openai_stream.OpenAIStreamClient, "stream", side_effect=create
            ),
            patch.object(server.time, "sleep"),
            patch.object(
                sync_queue.SyncJobQueueService,
                "enqueue",
                wraps=server.SYNC_JOB_QUEUE.service().enqueue,
            ) as enqueue,
        ):
            receipt = server.COACH_TURNS.chat_turn_service().run(
                message,
                client_turn_id=turn_id,
                session_csrf_hash="synthetic-session",
                background_job=True,
            )
            self.assertEqual(receipt["status"], "completed")
            enqueue.assert_not_called()
            approved = self.approve_remote_write()
            enqueue.assert_called_once()
        self.assertEqual(len(payloads), 3)
        self.assertEqual(payloads[1], payloads[2])
        # The turn is stateless: the retry resends the sync call and its output.
        self.assertEqual(
            [item.get("name") or item.get("type") for item in payloads[2]["input"][1:]],
            ["start_intervals_plan_sync", "function_call_output"],
        )
        for payload in payloads:
            self.assertIs(payload["store"], False)
            self.assertNotIn("conversation", payload)
            self.assertNotIn("previous_response_id", payload)
        self.assertEqual(approved["status"], "queued")

    def test_failed_background_answer_keeps_sync_and_reports_provider_code(self):
        server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [self.workout("2026-09-08")]
        )
        turn_id = "sync-provider-response-failure"
        message = "Sync zu intervals.icu durchführen"
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            message, turn_id, "synthetic-session"
        )
        responses = 0

        def create(payload, *_args, **kwargs):
            nonlocal responses
            responses += 1
            if kwargs.get("on_response_id") is not None:
                kwargs["on_response_id"](f"resp_{responses}")
            if responses == 1:
                return {
                    **self.call(
                        "start_intervals_plan_sync",
                        {},
                        ["local_plan", "intervals_sync"],
                        target="intervals",
                        remote_write=True,
                        sync_scope="all_pending",
                    ),
                    "id": "resp_sync",
                    "status": "completed",
                }
            return server.provider_state_service().validate_openai_response(
                "/responses", failed_response
            )

        failed_response = {
            "id": "resp_summary",
            "status": "failed",
            "error": {
                "code": "server_error",
                "message": "DO_NOT_EXPORT_PROVIDER_CONTENT",
            },
        }
        with (
            patch.object(
                server.COACH_CONVERSATION,
                "provision_service",
                return_value=Mock(binding=Mock(return_value="synthetic-conversation")),
            ),
            patch(
                "backend.coach.context.CoachTrainingContextService.build",
                return_value="Synthetic local context",
            ),
            patch.object(
                openai_stream.OpenAIStreamClient, "stream", side_effect=create
            ),
            patch.object(server.time, "sleep"),
            patch.object(
                sync_queue.SyncJobQueueService,
                "enqueue",
                wraps=server.SYNC_JOB_QUEUE.service().enqueue,
            ) as enqueue,
        ):
            receipt = server.COACH_TURNS.chat_turn_service().run(
                message,
                client_turn_id=turn_id,
                session_csrf_hash="synthetic-session",
                background_job=True,
            )
            replay = server.COACH_TURNS.chat_turn_service().run(
                message,
                client_turn_id=turn_id,
                session_csrf_hash="synthetic-session",
                background_job=True,
            )
            enqueue.assert_not_called()
            # The sync call, then the answer's three attempts: nothing is stored
            # at the provider, so a failed answer is requested again.
            self.assertEqual(responses, 4)
            self.assertEqual(receipt, replay)
            self.assertEqual(receipt["status"], "partial")
            self.assertEqual(receipt["pending_operations"], [])
            self.assertEqual(receipt["diagnostic_error"]["reason"], "response_failed")
            self.assertEqual(
                receipt["diagnostic_error"]["provider_error_code"], "server_error"
            )
            self.assertIn(
                "KI-Dienst konnte die Antwort nicht fertigstellen",
                receipt["message"]["content"],
            )
            self.assertIn("erneut", receipt["message"]["content"])
            self.assertIn("wartet auf deine Freigabe", receipt["message"]["content"])
            self.assertNotIn(
                "Plansynchronisierung beauftragt", receipt["message"]["content"]
            )
            approved = self.approve_remote_write()
            enqueue.assert_called_once()
        self.assertEqual(
            server.SYNC_JOB_QUEUE.service().state(approved["sync_job_id"])["status"],
            "queued",
        )
        history = server.DIAGNOSTICS_ASSEMBLY.coach_history_service().history()
        self.assertEqual(history[0]["error"]["provider_error_code"], "server_error")
        status = server.provider_state_service().summary("openai")["status"]
        self.assertEqual(status["provider_error_code"], "server_error")
        self.assertNotIn(
            "DO_NOT_EXPORT_PROVIDER_CONTENT", json.dumps([receipt, history, status])
        )

    def test_unknown_response_error_codes_and_messages_are_not_exported(self):
        for code in (
            "DO_NOT_EXPORT_PROVIDER_CONTENT",
            ["server_error"],
            {"secret": "content"},
            None,
        ):
            with (
                self.subTest(code_type=type(code).__name__),
                self.assertRaises(AppError) as raised,
            ):
                server.provider_state_service().validate_openai_response(
                    "/responses",
                    {
                        "error": {
                            "code": code,
                            "message": "DO_NOT_EXPORT_PROVIDER_CONTENT",
                        }
                    },
                )
            self.assertEqual(raised.exception.reason, "response_error")
            metadata = server.observability.safe_diagnostic_error(raised.exception)
            self.assertNotIn("provider_error_code", metadata)
            status = server.provider_state_service().summary("openai")["status"]
            self.assertNotIn("provider_error_code", status)
            self.assertNotIn(
                "DO_NOT_EXPORT_PROVIDER_CONTENT", json.dumps([metadata, status])
            )
