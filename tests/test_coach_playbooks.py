"""Request-kind playbooks: allowlist, per-turn injection and context sections."""

from __future__ import annotations

import threading
import unittest
from typing import Any
from unittest.mock import Mock

from backend.coach.context_selection import (
    REQUEST_KIND_SELECTIONS,
    select_coach_context,
)
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.playbooks import REQUEST_KINDS, playbook_for
from backend.coach.request_payload import (
    CoachRequestPayloadService,
    compose_model_instructions,
)
from backend.errors import AppError

NEW_KINDS = ("session_analysis", "progress_review", "plan_week", "plan_block")


class RequestKindAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CoachJobSubmissionService(
            lambda: Mock(),
            Mock(),
            threading.Lock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            lambda: "synthetic-time",
            background_horizon_days=30,
        )

    def validate(self, kind):
        return self.service._validate_submission("Hallo", "turn-1", kind, [])

    def test_new_kinds_and_morning_checkin_are_accepted(self) -> None:
        self.assertEqual(set(NEW_KINDS), set(REQUEST_KINDS))
        for kind in (*NEW_KINDS, "morning_checkin", None, ""):
            with self.subTest(kind=kind):
                self.assertEqual(self.validate(kind)[2], kind or None)

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.validate("plan_year")
        self.assertEqual(raised.exception.reason, "invalid_request_kind")


class PlaybookInjectionTests(unittest.TestCase):
    def test_each_kind_has_a_bounded_playbook_with_the_common_rules(self) -> None:
        for kind in NEW_KINDS:
            with self.subTest(kind=kind):
                text = playbook_for(kind)
                self.assertLess(len(text.split()), 450)
                self.assertIn("Never use ACWR", text)
                self.assertIn("pyramidal when it is absent", text)
                self.assertIn("training_model", text)

    def test_kind_specific_content(self) -> None:
        self.assertIn("get_activity_details", playbook_for("session_analysis"))
        self.assertIn("get_training_report", playbook_for("progress_review"))
        self.assertNotIn("Planning science", playbook_for("progress_review"))
        for kind in ("plan_week", "plan_block"):
            self.assertIn("Planning science", playbook_for(kind))
        self.assertIn("week-by-week rationale", playbook_for("plan_block"))
        self.assertNotIn("week-by-week rationale", playbook_for("plan_week"))

    def test_other_turns_carry_no_playbook(self) -> None:
        for kind in (None, "morning_checkin", "unknown"):
            self.assertEqual(playbook_for(kind), "")
            self.assertNotIn(
                "REQUEST PLAYBOOK",
                compose_model_instructions(
                    "ctx", allow_mutations=True, request_kind=kind
                ),
            )

    def test_payload_instructions_include_only_the_turn_playbook(self) -> None:
        training_context = Mock()
        training_context.build.return_value = "training context"
        settings = Mock()
        settings.selected_model.return_value = "model"
        settings.selected_thinking_level.return_value = "low"
        service = CoachRequestPayloadService(training_context, settings, 1000)
        context = {
            "current_user_message_id": 1,
            "local_date": "2026-09-23",
            "timezone": "Europe/Berlin",
            "pending_request": None,
            "messages": [],
        }
        arguments: dict[str, Any] = {
            "message": "Plane meine nächste Woche.",
            "context": context,
            "command_receipts": [],
            "tools": [],
            "allow_mutations": True,
            "model": None,
            "thinking_level": None,
            "conversation_id": "c",
            "attachments": [],
            "retain_openai_attachment_context": False,
            "has_prior_openai_attachments": False,
        }
        planned, _ = service.build(**arguments, request_kind="plan_week")
        plain, _ = service.build(**arguments)
        self.assertIn("REQUEST PLAYBOOK", planned)
        self.assertNotIn("REQUEST PLAYBOOK", plain)
        selection = training_context.build.call_args_list[0].kwargs["selection"]
        self.assertEqual(selection.name, "plan_week")


class RequestKindSelectionTests(unittest.TestCase):
    def test_plan_kinds_load_plan_calendar_recovery_and_weather(self) -> None:
        for kind in ("plan_week", "plan_block"):
            sections = select_coach_context("ok", {}, request_kind=kind).sections
            with self.subTest(kind=kind):
                self.assertLessEqual(
                    {
                        "planning",
                        "training_plans",
                        "calendar",
                        "external_calendar",
                        "recovery",
                        "weather",
                        "durable_profile",
                    },
                    sections,
                )
                self.assertNotIn("nutrition_products", sections)

    def test_review_and_analysis_kinds_load_what_they_need(self) -> None:
        progress = select_coach_context("x", {}, request_kind="progress_review")
        self.assertLessEqual({"planning", "recovery", "activities"}, progress.sections)
        analysis = select_coach_context("x", {}, request_kind="session_analysis")
        self.assertEqual(analysis.name, "activity_analysis")
        self.assertIn("durable_profile", analysis.sections)

    def test_every_kind_has_a_selection_and_keeps_message_retention(self) -> None:
        self.assertEqual(set(REQUEST_KIND_SELECTIONS), set(REQUEST_KINDS))
        context = {
            "pending_request": {"status": "needs_clarification", "summary": "x"},
            "messages": [],
        }
        for kind in REQUEST_KINDS:
            for message in ("Plane meine nächste Woche.", "Wie war mein Schlaf?"):
                expected = select_coach_context(message, context)
                selection = select_coach_context(message, context, request_kind=kind)
                with self.subTest(kind=kind, message=message):
                    self.assertEqual(
                        selection.retain_pending_request,
                        expected.retain_pending_request,
                    )
                    self.assertEqual(
                        selection.retain_dialogue, expected.retain_dialogue
                    )

    def test_progress_review_keeps_performance_comparisons(self) -> None:
        context = {"current_performance": {"comparisons": [1], "other": 2}}
        selection = select_coach_context("x", {}, request_kind="progress_review")
        projected = selection.project(context, "2026-11-01")
        self.assertEqual(projected["current_performance"]["comparisons"], [1])

    def test_morning_checkin_and_unknown_kinds_use_message_selection(self) -> None:
        expected = select_coach_context("Wie geht es mir?", {}).name
        for kind in (None, "morning_checkin"):
            self.assertEqual(
                select_coach_context("Wie geht es mir?", {}, request_kind=kind).name,
                expected,
            )


if __name__ == "__main__":
    unittest.main()
