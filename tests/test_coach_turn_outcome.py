"""Structured Coach outcome, repair and pending-request persistence contracts."""

from __future__ import annotations

import json
import unittest

from test_coach_dialogue import DialogueHarness, server


class CoachStructuredOutcomeTests(DialogueHarness, unittest.TestCase):
    @staticmethod
    def response(text: str = "Done", *, status: str = "completed") -> dict:
        return {
            "status": status,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        }

    @staticmethod
    def success(tool: str = "save_checkin") -> dict:
        return {"call_id": "success", "tool": tool, "result": {"ok": True, "status": "saved"}}

    @staticmethod
    def failure(tool: str = "update_profile", *, request: dict | None = None) -> dict:
        return {
            "call_id": "failed", "tool": tool,
            "request": request,
            "result": {"ok": False, "reason": "profile_conflict", "error": "Synthetic conflict"},
        }

    def finalize(self, response: dict, receipts: list[dict], **options):
        return server.coach_structured_outcome_service().finalize(
            response, receipts,
            question=options.get("question", ""),
            cancelled=options.get("cancelled", False),
            allow_mutations=options.get("allow_mutations", True),
            context=options.get("context", {"current_user_message_id": 17}),
            message="Synthetic user request",
        )

    def test_successful_effect_uses_provider_text_and_clears_pending_request(self):
        server.key_value_service().set("coach_pending_request", '{"summary":"old"}')
        receipts = [self.success()]
        status, text, failures = self.finalize(self.response("Saved"), receipts)
        self.assertEqual((status, text, failures), ("completed", "Saved", []))
        self.assertEqual(server.key_value_service().get("coach_pending_request"), "null")
        self.assertEqual(receipts[0]["result"]["status"], "saved")

    def test_partial_failure_persists_request_provenance_and_confirmed_effect(self):
        request = {"summary": "Repair profile", "source_message_ids": [17], "scope": ["profile"]}
        failed = self.failure(request=request)
        status, text, failures = self.finalize(self.response("Ignored"), [self.success(), failed])
        self.assertEqual(status, "partial")
        self.assertEqual(failures, [failed])
        self.assertIn("Synthetic conflict", text)
        self.assertIn("Gespeichert beziehungsweise beauftragt", text)
        self.assertEqual(json.loads(server.key_value_service().get("coach_pending_request")), {
            "summary": "Repair profile", "source_message_ids": [17],
            "status": "failed", "question": None,
            "completed_steps": [{"tool": "save_checkin", "status": "saved"}],
        })

    def test_question_keeps_existing_pending_request_and_text(self):
        server.key_value_service().set("coach_pending_request", '{"summary":"previous"}')
        status, text, failures = self.finalize(
            self.response("Ignored"), [self.failure()], question="Which date?"
        )
        self.assertEqual(status, "completed")
        self.assertEqual(text, "Which date?")
        self.assertEqual(len(failures), 1)
        self.assertEqual(server.key_value_service().get("coach_pending_request"), '{"summary":"previous"}')

    def test_incomplete_answer_uses_local_fallback_provenance(self):
        status, text, failures = self.finalize(self.response("Partial", status="incomplete"), [])
        self.assertEqual(status, "partial")
        self.assertIn("Fortsetzung", text)
        self.assertEqual(failures, [])
        pending = json.loads(server.key_value_service().get("coach_pending_request"))
        self.assertEqual(pending["summary"], "Synthetic user request")
        self.assertEqual(pending["source_message_ids"], [17])
        self.assertEqual(pending["completed_steps"], [])

    def test_read_only_turn_never_mutates_pending_request(self):
        server.key_value_service().set("coach_pending_request", '{"summary":"previous"}')
        status, _, failures = self.finalize(
            self.response("Partial", status="incomplete"), [self.failure()], allow_mutations=False
        )
        self.assertEqual(status, "partial")
        self.assertEqual(len(failures), 1)
        self.assertEqual(server.key_value_service().get("coach_pending_request"), '{"summary":"previous"}')

    def test_repaired_failure_is_marked_resolved_before_final_projection(self):
        failed = self.failure()
        repaired = {"call_id": "repair", "tool": "update_profile", "result": {"ok": True}}
        receipts = [failed, repaired]
        status, _, failures = self.finalize(self.response("Repaired"), receipts)
        self.assertEqual((status, failures), ("completed", []))
        self.assertTrue(failed["resolved"])
        self.assertEqual(server.key_value_service().get("coach_pending_request"), "null")

    def test_missing_answer_without_effect_fails_without_pending_mutation(self):
        server.key_value_service().set("coach_pending_request", '{"summary":"previous"}')
        status, text, failures = self.finalize(self.response(""), [])
        self.assertEqual((status, failures), ("failed", []))
        self.assertIn("nicht abgeschlossen", text)
        self.assertEqual(server.key_value_service().get("coach_pending_request"), '{"summary":"previous"}')
