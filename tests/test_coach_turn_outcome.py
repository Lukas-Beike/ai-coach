"""Structured Coach outcome, repair and pending-request persistence contracts."""

from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from test_coach_dialogue import DialogueHarness, server

from backend.coach.turn_outcome import CoachStructuredOutcomeService


class CoachStructuredOutcomeTests(DialogueHarness, unittest.TestCase):
    @staticmethod
    def response(text: str = "Done", *, status: str = "completed") -> dict:
        return {
            "status": status,
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ],
        }

    @staticmethod
    def success(tool: str = "save_checkin") -> dict:
        return {
            "call_id": "success",
            "tool": tool,
            "result": {"ok": True, "status": "saved"},
        }

    @staticmethod
    def failure(tool: str = "update_profile", *, request: dict | None = None) -> dict:
        return {
            "call_id": "failed",
            "tool": tool,
            "request": request,
            "result": {
                "ok": False,
                "reason": "profile_conflict",
                "error": "Synthetic conflict",
            },
        }

    def finalize(self, response: dict, receipts: list[dict], **options):
        return server.COACH_TURNS.outcome_service().finalize(
            response,
            receipts,
            question=options.get("question", ""),
            cancelled=options.get("cancelled", False),
            allow_mutations=options.get("allow_mutations", True),
            context=options.get("context", {"current_user_message_id": 17}),
            message=options.get("message", "Synthetic user request"),
            budget_exhausted=options.get("budget_exhausted", False),
        )

    def test_successful_effect_uses_provider_text_and_clears_pending_request(self):
        server.key_value_service().set("coach_pending_request", '{"summary":"old"}')
        receipts = [self.success()]
        status, text, failures = self.finalize(self.response("Saved"), receipts)
        self.assertEqual((status, text, failures), ("completed", "Saved", []))
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )
        self.assertEqual(receipts[0]["result"]["status"], "saved")

    def test_save_claim_without_a_write_step_is_flagged(self):
        read = {"tool": "read_nutrition", "result": {"ok": True}}
        for claim in (
            "Als Snack für heute erfasst: 113 g Apfel.",
            "Ich habe den Eintrag gespeichert.",
        ):
            with self.subTest(claim=claim):
                _, text, _ = self.finalize(self.response(claim), [dict(read)])
                self.assertTrue(text.startswith(claim))
                self.assertIn("nichts gespeichert", text)

    def test_save_claim_is_not_flagged_when_backed_or_not_a_claim(self):
        read = {"tool": "read_nutrition", "result": {"ok": True}}
        _, backed, _ = self.finalize(
            self.response("Ich habe den Eintrag gespeichert."), [self.success()]
        )
        _, quoted, _ = self.finalize(
            self.response("Heute erfasst: 113 g Apfel."), [read]
        )
        self.assertEqual(backed, "Ich habe den Eintrag gespeichert.")
        self.assertEqual(quoted, "Heute erfasst: 113 g Apfel.")

    def test_local_nutrition_approval_uses_local_only_wording(self):
        _, text, _ = self.finalize(
            self.response(""),
            [
                {
                    "tool": "save_nutrition_template",
                    "result": {
                        "ok": True,
                        "status": "approval_required",
                        "proposed_action": {"action_type": "local_coach_write"},
                    },
                }
            ],
        )
        self.assertIn("lokale Änderung", text)
        self.assertIn("gespeichert wird", text)
        self.assertNotIn("Remote-Änderung", text)

    def test_queued_remote_job_overrides_false_model_completion_claim(self):
        result = {
            "ok": True,
            "status": "queued",
            "sync_job_id": "synthetic-job-1",
        }
        status, text, failures = self.finalize(
            self.response("Synchronized successfully."),
            [
                {
                    "call_id": "sync",
                    "tool": "start_intervals_plan_sync",
                    "result": result,
                }
            ],
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertIn("synthetic-job-1: queued", text)
        self.assertIn("Remote-Abschluss ist noch nicht bestätigt", text)
        self.assertNotIn("Synchronized successfully", text)

    def test_remote_job_observation_supersedes_original_queued_receipt(self):
        receipts = [
            {
                "call_id": "sync",
                "tool": "start_intervals_plan_sync",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-job-1",
                },
            },
            {
                "call_id": "inspect",
                "tool": "inspect_sync_job",
                "result": {
                    "ok": True,
                    "job": {"id": "synthetic-job-1", "status": "completed"},
                },
            },
        ]
        status, text, failures = self.finalize(
            self.response("Synchronized successfully."), receipts
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertIn("synthetic-job-1: completed", text)
        self.assertIn("Remote-Abschluss ist bestätigt", text)
        self.assertNotIn("Synchronized successfully", text)

    def test_pending_receipt_observation_retains_unconfirmed_wording(self):
        receipts = [
            {
                "call_id": "sync",
                "tool": "start_intervals_plan_sync",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-job-2",
                },
            },
            {
                "call_id": "inspect",
                "tool": "inspect_sync_job",
                "result": {
                    "ok": True,
                    "job": {"id": "synthetic-job-2", "status": "running"},
                },
            },
        ]
        status, text, failures = self.finalize(
            self.response("Still syncing."), receipts
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertIn("synthetic-job-2: running", text)
        self.assertIn("Remote-Abschluss ist noch nicht bestätigt", text)

    def test_completed_job_observations_keep_model_analysis(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "completed",
                    "synchronous_refresh": True,
                },
            },
            *(
                {
                    "call_id": f"inspect-{job_id}",
                    "tool": "get_sync_job",
                    "result": {
                        "ok": True,
                        "job": {"id": job_id, "status": "completed"},
                    },
                }
                for job_id in ("synthetic-job-a", "synthetic-job-b")
            ),
        ]
        status, text, failures = self.finalize(
            self.response("Recovery is good; keep today's planned session."), receipts
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertEqual(text, "Recovery is good; keep today's planned session.")

    def test_completed_refresh_started_this_turn_keeps_model_analysis(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-refresh-1",
                },
            },
            {
                "call_id": "inspect",
                "tool": "get_sync_job",
                "result": {
                    "ok": True,
                    "job": {
                        "id": "synthetic-refresh-1",
                        "type": "refresh",
                        "status": "completed",
                    },
                },
            },
        ]
        status, text, failures = self.finalize(
            self.response("Readiness is high; the planned intervals fit."), receipts
        )
        self.assertEqual((status, failures), ("completed", []))
        self.assertEqual(text, "Readiness is high; the planned intervals fit.")

    def test_partial_synchronous_refresh_keeps_analysis_and_flags_missing_data(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "completed",
                    "provider": "garmin",
                    "partial": True,
                    "synchronous_refresh": True,
                },
            }
        ]
        _, text, _ = self.finalize(self.response("Recovery looks fine."), receipts)
        self.assertTrue(text.startswith("Recovery looks fine.\n"))
        self.assertIn("direkte Datenabruf vor dieser Antwort war unvollständig", text)

    def test_narrowed_whole_history_refresh_discloses_the_limited_window(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "completed",
                    "provider": "garmin",
                    "activity_days": 3,
                    "partial": False,
                    "history_limited": True,
                    "synchronous_refresh": True,
                },
            }
        ]
        _, text, _ = self.finalize(self.response("Recovery looks fine."), receipts)
        self.assertTrue(text.startswith("Recovery looks fine.\n"))
        self.assertIn("ältere Historie wurde nicht neu geladen", text)
        self.assertNotIn("direkte Datenabruf vor dieser Antwort", text)

    def test_complete_synchronous_refresh_adds_no_note(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "completed",
                    "provider": "garmin",
                    "partial": False,
                    "synchronous_refresh": True,
                },
            }
        ]
        _, text, _ = self.finalize(self.response("Recovery looks fine."), receipts)
        self.assertEqual(text, "Recovery looks fine.")

    def test_inspected_job_type_decides_whether_a_started_job_writes_remote(self):
        def receipts(job_type):
            return [
                {
                    "call_id": "refresh",
                    "tool": "start_provider_refresh",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "synthetic-typed-1",
                    },
                },
                {
                    "call_id": "inspect",
                    "tool": "get_sync_job",
                    "result": {
                        "ok": True,
                        "job": {
                            "id": "synthetic-typed-1",
                            "type": job_type,
                            "status": "running",
                        },
                    },
                },
            ]

        _, kept, _ = self.finalize(self.response("Analysis."), receipts("refresh"))
        self.assertTrue(kept.startswith("Analysis.\n"))
        _, replaced, _ = self.finalize(
            self.response("Analysis."), receipts("plan_push")
        )
        self.assertNotIn("Analysis.", replaced)
        self.assertIn("synthetic-typed-1: running", replaced)

    def test_pending_refresh_keeps_analysis_and_appends_unconfirmed_status(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-refresh-2",
                },
            }
        ]
        _, text, _ = self.finalize(self.response("Take it easy today."), receipts)
        self.assertTrue(text.startswith("Take it easy today.\n"))
        self.assertIn("synthetic-refresh-2: queued", text)
        self.assertIn("Der Datenabruf läuft noch", text)
        self.assertNotIn("Remote-Abschluss", text)

    def test_empty_answer_with_pending_refresh_falls_back_to_receipts(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-refresh-3",
                },
            }
        ]
        _, text, _ = self.finalize(self.response(""), receipts)
        self.assertIn("synthetic-refresh-3: queued", text)

    def test_completed_plan_push_inspected_only_keeps_model_analysis(self):
        receipts = [
            {
                "call_id": "inspect",
                "tool": "get_sync_job",
                "result": {
                    "ok": True,
                    "job": {
                        "id": "synthetic-push-1",
                        "type": "plan_push",
                        "status": "completed",
                    },
                },
            }
        ]
        _, text, _ = self.finalize(self.response("The plan is on Intervals."), receipts)
        self.assertEqual(text, "The plan is on Intervals.")

    def test_write_job_alongside_refresh_still_replaces_model_claim(self):
        receipts = [
            {
                "call_id": "refresh",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-refresh-4",
                },
            },
            {
                "call_id": "sync",
                "tool": "start_intervals_plan_sync",
                "result": {
                    "ok": True,
                    "status": "queued",
                    "sync_job_id": "synthetic-push-2",
                },
            },
        ]
        _, text, _ = self.finalize(self.response("All synchronized."), receipts)
        self.assertNotIn("All synchronized", text)
        self.assertIn("synthetic-push-2: queued", text)

    def test_unfinished_job_observation_still_replaces_model_claim(self):
        receipts = [
            {
                "call_id": "inspect",
                "tool": "get_sync_job",
                "result": {
                    "ok": True,
                    "job": {"id": "synthetic-job-3", "status": "running"},
                },
            }
        ]
        _, text, _ = self.finalize(self.response("Everything is synced."), receipts)
        self.assertIn("synthetic-job-3: running", text)
        self.assertIn("Remote-Abschluss ist noch nicht bestätigt", text)
        self.assertNotIn("Everything is synced", text)

    def test_repaired_failure_clears_failure_text_and_sets_completed(self):
        failed = self.failure()
        repaired = {
            "call_id": "repair",
            "tool": "update_profile",
            "result": {"ok": True, "status": "updated"},
        }
        receipts = [failed, repaired]
        status, text, failures = self.finalize(self.response("Repaired"), receipts)
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertEqual(text, "Repaired")
        self.assertTrue(failed["resolved"])

    def test_approval_required_result_keeps_pending_approval_wording(self):
        result = {
            "ok": True,
            "status": "approval_required",
            "proposed_action": {"action_type": "remote_coach_write"},
        }
        status, text, failures = self.finalize(
            self.response("Done"),
            [
                {
                    "call_id": "plan",
                    "tool": "create_workout_on_intervals",
                    "result": result,
                }
            ],
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertIn("wartet auf deine ausdrückliche Freigabe", text)

    def test_partial_failure_with_queued_job_includes_both_receipts(self):
        queued = {
            "call_id": "sync",
            "tool": "start_intervals_plan_sync",
            "result": {
                "ok": True,
                "status": "queued",
                "sync_job_id": "synthetic-job-partial",
            },
        }
        failed = self.failure()
        status, text, failures = self.finalize(
            self.response("Ignored"), [queued, failed]
        )
        self.assertEqual(status, "partial")
        self.assertEqual(failures, [failed])
        self.assertIn("synthetic-job-partial: queued", text)
        self.assertIn("Synthetic conflict", text)

    def test_incomplete_answer_with_queued_job_includes_continuation_notice(self):
        queued = {
            "call_id": "sync",
            "tool": "start_intervals_plan_sync",
            "result": {
                "ok": True,
                "status": "queued",
                "sync_job_id": "synthetic-job-inc",
            },
        }
        status, text, failures = self.finalize(
            self.response("Done", status="incomplete"), [queued]
        )
        self.assertEqual(status, "partial")
        self.assertEqual(failures, [])
        self.assertIn("synthetic-job-inc: queued", text)
        self.assertIn("Antwort wurde nicht abgeschlossen", text)

    def test_question_with_queued_job_preserves_question_and_job_receipt(self):
        queued = {
            "call_id": "sync",
            "tool": "start_intervals_plan_sync",
            "result": {
                "ok": True,
                "status": "queued",
                "sync_job_id": "question-partial-job",
            },
        }
        status, text, failures = self.finalize(
            self.response("The update completed.", status="incomplete"),
            [queued],
            question="Which training period should I refresh?",
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertIn("question-partial-job: queued", text)
        self.assertIn("Antwort wurde nicht abgeschlossen", text)
        self.assertIn("Which training period should I refresh?", text)
        self.assertNotIn("The update completed", text)

    def test_partial_failure_persists_request_provenance_and_confirmed_effect(self):
        request = {
            "summary": "Repair profile",
            "source_message_ids": [17],
            "scope": ["profile"],
        }
        failed = self.failure(request=request)
        status, text, failures = self.finalize(
            self.response("Ignored"), [self.success(), failed]
        )
        self.assertEqual(status, "partial")
        self.assertEqual(failures, [failed])
        self.assertIn("Synthetic conflict", text)
        self.assertIn("Gespeichert beziehungsweise beauftragt", text)
        self.assertEqual(
            json.loads(server.key_value_service().get("coach_pending_request")),
            {
                # The athlete's own words, not the model-written request summary.
                "summary": "Synthetic user request",
                "source_message_ids": [17],
                "status": "failed",
                "domain": "nutrition_or_profile",
                "question": None,
                "completed_steps": [{"tool": "save_checkin", "status": "saved"}],
            },
        )

    def test_failed_request_stores_stored_athlete_text_not_model_summary(self):
        request = {
            "summary": "Delete every planned workout this season",
            "source_message_ids": [15, 17],
            "scope": ["plan"],
        }
        context = {
            "current_user_message_id": 17,
            "messages": [
                {"id": 15, "role": "user", "content": "Schiebe den Donnerstag"},
                {"id": 16, "role": "assistant", "content": "Welcher Donnerstag?"},
                {"id": 17, "role": "user", "content": "Der nächste"},
            ],
        }
        self.finalize(
            self.response("Ignored"),
            [self.failure(request=request)],
            context=context,
            message="Der nächste",
        )
        pending = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(pending["summary"], "Schiebe den Donnerstag\nDer nächste")
        self.assertEqual(pending["source_message_ids"], [15, 17])
        self.assertNotIn("Delete", json.dumps(pending))

    def test_retry_of_failed_request_keeps_original_athlete_request(self):
        server.key_value_service().set(
            "coach_pending_request",
            json.dumps(
                {
                    "summary": "Model wording",
                    "source_message_ids": [15],
                    "status": "failed",
                    "domain": "training",
                }
            ),
        )
        context = {
            "current_user_message_id": 17,
            "messages": [
                {"id": 15, "role": "user", "content": "Plane Dienstag locker"},
                {"id": 17, "role": "user", "content": "nochmal"},
            ],
            "pending_request": json.loads(
                server.key_value_service().get("coach_pending_request")
            ),
        }
        self.finalize(
            self.response("Ignored"),
            [self.failure()],
            context=context,
            message="nochmal",
        )
        pending = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(pending["summary"], "Plane Dienstag locker")
        self.assertEqual(pending["source_message_ids"], [15])

    def test_retry_that_fails_again_keeps_original_athlete_request(self):
        pending = {
            "summary": "Plane Dienstag locker",
            "source_message_ids": [15],
            "status": "failed",
            "domain": "training",
        }
        server.key_value_service().set("coach_pending_request", json.dumps(pending))
        context = {
            "current_user_message_id": 17,
            "messages": [
                {"id": 15, "role": "user", "content": "Plane Dienstag locker"},
                {"id": 17, "role": "user", "content": "nochmal"},
            ],
            "pending_request": pending,
        }
        # The model only cites the bare retry message as its request source.
        request = {
            "summary": "Retry",
            "source_message_ids": [17],
            "scope": ["plan"],
        }
        self.finalize(
            self.response("Ignored"),
            [self.failure(request=request)],
            context=context,
            message="nochmal",
        )
        stored = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(stored["summary"], "Plane Dienstag locker")
        self.assertEqual(stored["source_message_ids"], [15])

    def test_failed_clarification_answer_keeps_the_answer(self):
        pending = {
            "summary": "Schiebe den Donnerstag",
            "source_message_ids": [15],
            "status": "needs_clarification",
            "domain": "training",
        }
        context = {
            "current_user_message_id": 17,
            "messages": [
                {"id": 15, "role": "user", "content": "Schiebe den Donnerstag"},
                {"id": 17, "role": "user", "content": "Der erste"},
            ],
            "pending_request": pending,
        }
        request = {"summary": "Move", "source_message_ids": [15, 17]}
        self.finalize(
            self.response("Ignored"),
            [self.failure(request=request)],
            context=context,
            message="Der erste",
        )
        stored = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(stored["summary"], "Schiebe den Donnerstag\nDer erste")
        self.assertEqual(stored["source_message_ids"], [15, 17])

    def test_exhausted_budget_after_clarification_keeps_original_and_answer(self):
        pending = {
            "summary": "Abendessen: 100g Risottoreis",
            "source_message_ids": [15],
            "status": "needs_clarification",
            "domain": "nutrition_or_profile",
        }
        answer = "Trocken. Ergänze auch noch 130g Champignons roh"
        context = {
            "current_user_message_id": 17,
            "messages": [
                {"id": 15, "role": "user", "content": "Abendessen: 100g Risottoreis"},
                {"id": 17, "role": "user", "content": answer},
            ],
            "pending_request": pending,
        }
        lookup = {
            "call_id": "lookup",
            "tool": "lookup_food",
            "result": {"ok": True, "results": []},
        }
        status, text, failures = self.finalize(
            self.response("Ich habe die Zutaten gesucht."),
            [lookup],
            context=context,
            message=answer,
            budget_exhausted=True,
        )
        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertTrue(text.startswith("Ich habe die Zutaten gesucht.\n"))
        self.assertIn("„weiter“", text)
        stored = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(stored["status"], "failed")
        self.assertEqual(stored["domain"], "nutrition_or_profile")
        self.assertEqual(stored["source_message_ids"], [15, 17])
        self.assertEqual(stored["summary"], f"Abendessen: 100g Risottoreis\n{answer}")

    def test_failed_new_request_does_not_fall_back_to_the_retained_request(self):
        pending = {
            "summary": "Schiebe den Donnerstag",
            "source_message_ids": [15],
            "status": "needs_clarification",
            "domain": "training",
        }
        context = {
            "current_user_message_id": 17,
            "messages": [
                {"id": 15, "role": "user", "content": "Schiebe den Donnerstag"},
                {"id": 17, "role": "user", "content": "Plane Samstag 3 Stunden Rad"},
            ],
            "pending_request": pending,
        }
        request = {"summary": "Plan", "source_message_ids": [17]}
        self.finalize(
            self.response("Ignored"),
            [self.failure(request=request)],
            context=context,
            message="Plane Samstag 3 Stunden Rad",
        )
        stored = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(stored["summary"], "Plane Samstag 3 Stunden Rad")
        self.assertEqual(stored["source_message_ids"], [17])

    def test_question_keeps_existing_pending_request_and_text(self):
        server.key_value_service().set(
            "coach_pending_request", '{"summary":"previous"}'
        )
        status, text, failures = self.finalize(
            self.response("Ignored"), [self.failure()], question="Which date?"
        )
        self.assertEqual(status, "completed")
        self.assertEqual(text, "Which date?")
        self.assertEqual(len(failures), 1)
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"),
            '{"summary":"previous"}',
        )

    def test_incomplete_answer_uses_local_fallback_provenance(self):
        status, text, failures = self.finalize(
            self.response("Partial", status="incomplete"), []
        )
        self.assertEqual(status, "partial")
        self.assertIn("Fortsetzung", text)
        self.assertEqual(failures, [])
        pending = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(pending["summary"], "Synthetic user request")
        self.assertEqual(pending["source_message_ids"], [17])
        self.assertEqual(pending["completed_steps"], [])

    def test_read_only_turn_never_mutates_pending_request(self):
        server.key_value_service().set(
            "coach_pending_request", '{"summary":"previous"}'
        )
        status, _, failures = self.finalize(
            self.response("Partial", status="incomplete"),
            [self.failure()],
            allow_mutations=False,
        )
        self.assertEqual(status, "partial")
        self.assertEqual(len(failures), 1)
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"),
            '{"summary":"previous"}',
        )

    def test_repaired_failure_is_marked_resolved_before_final_projection(self):
        failed = self.failure()
        repaired = {
            "call_id": "repair",
            "tool": "update_profile",
            "result": {"ok": True},
        }
        receipts = [failed, repaired]
        status, _, failures = self.finalize(self.response("Repaired"), receipts)
        self.assertEqual((status, failures), ("completed", []))
        self.assertTrue(failed["resolved"])
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )

    def test_missing_answer_without_effect_fails_without_pending_mutation(self):
        server.key_value_service().set(
            "coach_pending_request", '{"summary":"previous"}'
        )
        status, text, failures = self.finalize(self.response(""), [])
        self.assertEqual((status, failures), ("failed", []))
        self.assertIn("nicht abgeschlossen", text)
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"),
            '{"summary":"previous"}',
        )

    def test_clean_advisory_turn_clears_stale_failed_pending_request(self):
        server.key_value_service().set(
            "coach_pending_request",
            json.dumps({"summary": "Previous failed", "status": "failed"}),
        )
        status, text, failures = self.finalize(
            self.response("Lauf locker mit den Vomeros."), []
        )
        self.assertEqual((status, failures), ("completed", []))
        self.assertEqual(text, "Lauf locker mit den Vomeros.")
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )

    def test_clean_advisory_turn_clears_active_clarification_pending_request(
        self,
    ):
        server.key_value_service().set(
            "coach_pending_request",
            json.dumps(
                {"summary": "Needs clarification", "status": "needs_clarification"}
            ),
        )
        status, _, failures = self.finalize(
            self.response("Hier ist deine Antwort."), []
        )
        self.assertEqual((status, failures), ("completed", []))
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )

    def test_empty_text_turn_with_effects_clears_failed_pending_request(self):
        server.key_value_service().set(
            "coach_pending_request",
            json.dumps({"summary": "Previous failed", "status": "failed"}),
        )
        receipts = [self.success()]
        status, text, failures = self.finalize(self.response(""), receipts)
        self.assertEqual((status, failures), ("partial", []))
        self.assertIn("Tages-Check-in gespeichert", text)
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )

    def test_unrelated_read_only_tool_turn_clears_abandoned_clarification(self):
        server.key_value_service().set(
            "coach_pending_request",
            json.dumps(
                {
                    "summary": "Snack erfassen",
                    "status": "needs_clarification",
                    "domain": "nutrition_or_profile",
                }
            ),
        )
        status, _, failures = self.finalize(
            self.response("Read-only advice"),
            [{"tool": "get_profile", "result": {"ok": True}}],
            message="Welche Schuhe für morgen?",
        )
        self.assertEqual((status, failures), ("completed", []))
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )

    def test_incomplete_new_topic_does_not_reuse_abandoned_summary(self):
        pending = {
            "summary": "Snack erfassen",
            "status": "needs_clarification",
            "domain": "nutrition_or_profile",
        }
        self.finalize(
            self.response("Partial", status="incomplete"),
            [],
            context={"pending_request": pending, "current_user_message_id": 17},
            message="Plane Intervalle morgen",
        )
        stored = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(stored["summary"], "Plane Intervalle morgen")
        self.assertEqual(stored["domain"], "training")

    def test_related_read_preserves_clarification_for_later_answer(self):
        pending = {
            "summary": "Einheit verschieben",
            "status": "needs_clarification",
            "domain": "training",
            "question": "Welche Einheit?",
        }
        server.key_value_service().set("coach_pending_request", json.dumps(pending))
        self.finalize(
            self.response("Synthetic weekly overview"),
            [{"tool": "list_planned_workouts", "result": {"ok": True}}],
            message="Zeig mir die Woche nochmal.",
        )
        self.assertEqual(
            json.loads(server.key_value_service().get("coach_pending_request")), pending
        )

    def test_clean_advice_clears_clarification_within_same_broad_domain(self):
        server.key_value_service().set(
            "coach_pending_request",
            json.dumps(
                {
                    "summary": "Einheit verschieben",
                    "status": "needs_clarification",
                    "domain": "training",
                    "question": "Welche Einheit?",
                }
            ),
        )
        self.finalize(
            self.response("Synthetic training advice"),
            [],
            message="Wie soll ich morgen trainieren?",
        )
        self.assertEqual(
            server.key_value_service().get("coach_pending_request"), "null"
        )

    def test_pending_cleanup_reads_and_writes_in_one_transaction(self):
        database = object()
        active = False
        manager, key_values = Mock(), Mock()

        @contextmanager
        def transaction():
            nonlocal active
            active = True
            try:
                yield database
            finally:
                active = False

        def read(db, key):
            self.assertTrue(active)
            self.assertIs(db, database)
            self.assertEqual(key, "coach_pending_request")
            return '{"status":"needs_clarification"}'

        def write(db, key, value):
            self.assertTrue(active)
            self.assertIs(db, database)
            self.assertEqual((key, value), ("coach_pending_request", "null"))

        manager.unit_of_work.side_effect = transaction
        key_values.get.side_effect = read
        key_values.set.side_effect = write
        service = CoachStructuredOutcomeService(
            manager, transaction(), key_values, frozenset()
        )
        service.finalize(
            self.response(),
            [],
            question="",
            cancelled=False,
            allow_mutations=True,
            context={},
            message="Unrelated question",
        )
        manager.reader.assert_not_called()
        manager.unit_of_work.assert_called_once()
        key_values.set.assert_called_once()

    def test_mixed_local_and_queued_effects_replace_model_completion_claim(self):
        status, text, failures = self.finalize(
            self.response("The check-in and remote sync are both complete."),
            [
                self.success(),
                {
                    "tool": "start_intervals_plan_sync",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "mixed-job",
                    },
                },
            ],
        )

        self.assertEqual(status, "completed")
        self.assertEqual(failures, [])
        self.assertIn("Tages-Check-in gespeichert", text)
        self.assertIn("mixed-job: queued", text)
        self.assertIn("Remote-Abschluss ist noch nicht bestätigt", text)
        self.assertNotIn("both complete", text)

    def test_mixed_local_and_queued_refresh_keeps_model_analysis(self):
        status, text, failures = self.finalize(
            self.response("Check-in saved; readiness looks good."),
            [
                self.success(),
                {
                    "tool": "refresh_current_performance",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "mixed-refresh",
                    },
                },
            ],
        )

        self.assertEqual((status, failures), ("completed", []))
        self.assertTrue(text.startswith("Check-in saved; readiness looks good.\n"))
        self.assertIn("mixed-refresh: queued", text)
        self.assertIn("Der Datenabruf läuft noch", text)
        self.assertNotIn("Remote-Abschluss", text)

    def test_finished_read_only_refresh_reports_failure_or_partial_data(self):
        def receipts(job_status):
            return [
                {
                    "call_id": "refresh",
                    "tool": "start_provider_refresh",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "synthetic-read-1",
                    },
                },
                {
                    "call_id": "inspect",
                    "tool": "get_sync_job",
                    "result": {
                        "ok": True,
                        "job": {
                            "id": "synthetic-read-1",
                            "type": "refresh",
                            "status": job_status,
                        },
                    },
                },
            ]

        _, failed, _ = self.finalize(self.response("Analysis."), receipts("failed"))
        self.assertTrue(failed.startswith("Analysis.\n"))
        self.assertIn("synthetic-read-1: failed", failed)
        self.assertIn("Der Datenabruf ist fehlgeschlagen", failed)
        self.assertNotIn("Remote-Abschluss", failed)
        _, partial, _ = self.finalize(self.response("Analysis."), receipts("partial"))
        self.assertIn("synthetic-read-1: partial", partial)
        self.assertIn("nur teilweise erfolgreich", partial)
        self.assertNotIn("Remote-Abschluss", partial)

    def test_partial_job_line_and_partial_direct_refresh_are_each_named(self):
        receipts = [
            {
                "call_id": "waited",
                "tool": "start_provider_refresh",
                "result": {
                    "ok": True,
                    "status": "completed",
                    "partial": True,
                    "synchronous_refresh": True,
                },
            },
            {
                "call_id": "inspect",
                "tool": "get_sync_job",
                "result": {
                    "ok": True,
                    "job": {
                        "id": "synthetic-read-2",
                        "type": "refresh",
                        "status": "partial",
                    },
                },
            },
        ]

        _, text, _ = self.finalize(self.response("Analysis."), receipts)

        self.assertIn("synthetic-read-2: partial", text)
        self.assertEqual(1, text.count("nur teilweise erfolgreich"))
        self.assertEqual(1, text.count("direkte Datenabruf vor dieser Antwort"))

    def test_question_keeps_failure_and_read_only_refresh_status(self):
        _, text, _ = self.finalize(
            self.response("Readiness looks fine."),
            [
                self.failure(),
                {
                    "tool": "refresh_current_performance",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "question-refresh",
                    },
                },
            ],
            question="Which race date should I use?",
        )

        self.assertIn("Which race date should I use?", text)
        self.assertIn("question-refresh: queued", text)
        self.assertIn("Synthetic conflict", text)

    def test_queued_receipt_does_not_suppress_clarifying_question(self):
        _, text, _ = self.finalize(
            self.response("The sync completed."),
            [
                {
                    "tool": "refresh_current_performance",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "question-job",
                    },
                }
            ],
            question="Which training period should I refresh?",
        )

        self.assertIn("question-job: queued", text)
        self.assertIn("Which training period should I refresh?", text)
        self.assertNotIn("The sync completed", text)

    def test_incomplete_queued_outcome_keeps_warning_and_authoritative_receipts(self):
        status, text, _ = self.finalize(
            self.response("The update completed.", status="incomplete"),
            [
                self.success(),
                {
                    "tool": "start_intervals_plan_sync",
                    "result": {
                        "ok": True,
                        "status": "queued",
                        "sync_job_id": "partial-job",
                    },
                },
            ],
        )

        self.assertEqual(status, "partial")
        self.assertIn("Tages-Check-in gespeichert", text)
        self.assertIn("partial-job: queued", text)
        self.assertIn("Antwort wurde nicht abgeschlossen", text)
        self.assertNotIn("The update completed", text)
