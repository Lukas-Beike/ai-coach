"""Request-kind playbooks: allowlist, per-turn injection and context sections."""

from __future__ import annotations

import re
import threading
import unittest
from datetime import date
from typing import Any
from unittest.mock import Mock

from backend.coach import playbooks
from backend.coach.context_selection import (
    REQUEST_KIND_SELECTIONS,
    free_text_review_kind,
    select_coach_context,
)
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.playbooks import REQUEST_KINDS, nutrition_playbook, playbook_for
from backend.coach.prompt import COACH_PROMPT
from backend.coach.request_payload import (
    CoachRequestPayloadService,
    compose_model_instructions,
)
from backend.errors import AppError

NEW_KINDS = (
    "session_analysis",
    "progress_review",
    "block_review",
    "plan_week",
    "plan_block",
    "adjust_week",
)


KIND_WORD_BUDGET = 600
# Per-block word budgets: a block that grows must justify it here.
BLOCK_WORD_BUDGETS = {
    "_EVIDENCE": 60,
    "_INTENSITY_MODEL": 40,
    "_PLAN_STRUCTURE": 130,
    "_STRENGTH_LEGS": 75,
    "_SEASON_PHASE": 75,
    "_PRECEDENCE": 30,
    "_CALENDAR": 45,
    "_PLAN_CHECK": 80,
    "_ADAPTIVE": 140,
    "_SESSION_CHECKS": 110,
    "_ANSWER": 55,
    "_NUTRITION": 520,
}
TASK_WORD_BUDGET = 190


class PlaybookBudgetTests(unittest.TestCase):
    def test_each_block_stays_within_its_budget(self) -> None:
        for name, budget in BLOCK_WORD_BUDGETS.items():
            with self.subTest(block=name):
                self.assertLessEqual(len(getattr(playbooks, name).split()), budget)

    def test_each_task_stays_within_its_budget(self) -> None:
        for kind, task in playbooks._TASKS.items():
            with self.subTest(kind=kind):
                self.assertLessEqual(len(task.split()), TASK_WORD_BUDGET)

    def test_every_block_is_budgeted_and_every_kind_composed(self) -> None:
        blocks = {
            name
            for name, value in vars(playbooks).items()
            if isinstance(value, str)
            and re.fullmatch(r"_[A-Z_]+", name)
            and name != "_HEADER"
        }
        self.assertEqual(blocks, set(BLOCK_WORD_BUDGETS))
        self.assertEqual(set(playbooks._BLOCKS), set(REQUEST_KINDS))

    def test_kinds_carry_only_the_blocks_they_need(self) -> None:
        for kind in ("session_analysis", "progress_review", "block_review"):
            text = playbook_for(kind)
            with self.subTest(kind=kind):
                for block in (
                    playbooks._SEASON_PHASE,
                    playbooks._PLAN_CHECK,
                    playbooks._ADAPTIVE,
                    playbooks._STRENGTH_LEGS,
                ):
                    self.assertNotIn(block, text)
        self.assertIn(playbooks._ADAPTIVE, playbook_for("adjust_week"))
        self.assertNotIn(playbooks._ADAPTIVE, playbook_for("plan_week"))
        for block in playbooks._BLOCKS["plan_block"]:
            self.assertIn(block, playbook_for("plan_week"))

    def test_nutrition_playbook_is_empty_without_nutrition(self) -> None:
        self.assertEqual(nutrition_playbook(False), "")
        self.assertIn("6i.", nutrition_playbook(True))


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
                self.assertLessEqual(len(text.split()), KIND_WORD_BUDGET)
                self.assertIn("Never use ACWR", text)
                self.assertIn("pyramidal when it is absent", text)
                self.assertIn("training_model", text)

    def test_session_analysis_carries_the_session_checks_only(self) -> None:
        text = playbook_for("session_analysis")
        for needle in ("session_focus", "pace_at_heart_rate", "never a proven cause"):
            self.assertIn(needle, text)
        self.assertIn("not_covered", text)
        self.assertNotIn(playbooks._SESSION_CHECKS, playbook_for("block_review"))

    def test_kind_specific_content(self) -> None:
        self.assertIn("get_activity_details", playbook_for("session_analysis"))
        self.assertIn("get_training_report", playbook_for("progress_review"))
        self.assertNotIn("Planning science", playbook_for("progress_review"))
        for kind in ("plan_week", "plan_block"):
            self.assertIn("Planning science", playbook_for(kind))
        for kind in ("plan_week", "plan_block"):
            self.assertIn("season_phase", playbook_for(kind))
        self.assertIn("season_phase", playbook_for("adjust_week"))
        self.assertIn("week-by-week rationale", playbook_for("plan_block"))
        self.assertNotIn("week-by-week rationale", playbook_for("plan_week"))

    def test_review_kinds_share_the_answer_format_and_plain_language(self) -> None:
        self.assertIn("explain a term like CTL, TSB or eFTP", COACH_PROMPT)
        for kind in ("session_analysis", "progress_review", "block_review"):
            with self.subTest(kind=kind):
                self.assertIn(playbooks._ANSWER, playbook_for(kind))
        for kind in ("plan_week", "plan_block", "adjust_week"):
            self.assertNotIn(playbooks._ANSWER, playbook_for(kind))

    def test_session_analysis_names_what_to_look_at_per_session_type(self) -> None:
        text = playbook_for("session_analysis")
        for marker in (
            "by default the last one",
            "warm-up and cool-down",
            "decoupling at the same pace",
            "strides or a progression are intended",
            "reps holding or fading",
            "heart-rate drop",
            "Under about 2 minutes",
            "load and intensity",
            "sensor errors",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_reviews_lead_with_fitness_and_block_review_reads_pace_at_hr(self) -> None:
        self.assertIn("getting fitter", playbook_for("progress_review"))
        self.assertIn("possible cause", playbook_for("progress_review"))
        block = playbook_for("block_review")
        self.assertNotIn("Pace at heart rate is not covered", block)
        self.assertIn("pace at heart rate is not_covered", block)

    def test_adjust_week_playbook_guards_hard_days_and_writes(self) -> None:
        text = playbook_for("adjust_week")
        for marker in (
            "get_training_report",
            "session_focus",
            "never next to another hard day",
            "24 h",
            "preview_adaptive_replan",
            "No Intervals.icu write without a named sync",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("Planning science", text)

    def test_adjust_week_context_is_its_own(self) -> None:
        sections = select_coach_context("ok", {}, request_kind="adjust_week").sections
        self.assertLessEqual(
            {
                "planning_brief",
                "planning",
                "training_plans",
                "recovery",
                "external_calendar",
                "daily_planning_context",
            },
            sections,
        )
        # Calendar events come once, as external_calendar.
        self.assertNotIn("calendar", sections)
        self.assertNotIn("nutrition_products", sections)
        selection = select_coach_context("ok", {}, request_kind="adjust_week")
        items = [{"date": f"2026-11-{day:02d}"} for day in (1, 2, 8, 10)]
        kept = selection.dated_items(items, date(2026, 11, 5))
        self.assertEqual(
            ["2026-11-01", "2026-11-02", "2026-11-08", "2026-11-10"],
            [i["date"] for i in kept],
        )
        self.assertEqual("", playbook_for("morning_checkin"))

    def test_nutrition_rules_only_on_nutrition_turns(self) -> None:
        marker = (
            "first match every ingredient against the athlete's saved local products"
        )
        plain = compose_model_instructions("ctx", allow_mutations=True)
        food = compose_model_instructions("ctx", allow_mutations=True, nutrition=True)
        self.assertNotIn(marker, plain)
        self.assertNotIn(marker, COACH_PROMPT)
        self.assertIn(marker, food)
        self.assertIn("save_nutrition_template", food)
        self.assertNotIn("save_nutrition_template", plain)
        for kind in ("plan_week", "session_analysis"):
            self.assertNotIn(
                marker,
                compose_model_instructions(
                    "ctx", allow_mutations=True, request_kind=kind
                ),
            )

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
        with self.assertLogs("intervals_coach", "INFO") as logs:
            planned, _ = service.build(**arguments, request_kind="plan_week")
            plain, _ = service.build(**{**arguments, "message": "Wie war mein Schlaf?"})
            typed, _ = service.build(**arguments)
        sizes = [r.context for r in logs.records if hasattr(r, "context")]
        self.assertEqual(
            len(playbook_for("plan_week")), sizes[0]["playbook_characters"]
        )
        self.assertEqual(0, sizes[1]["playbook_characters"])
        self.assertIn("REQUEST PLAYBOOK", planned)
        self.assertNotIn("REQUEST PLAYBOOK", plain)
        # A typed planning request carries the same playbook as the quick action.
        self.assertEqual(
            len(playbook_for("plan_week")), sizes[2]["playbook_characters"]
        )
        self.assertIn("Task: plan the requested next week", typed)
        selection = training_context.build.call_args_list[0].kwargs["selection"]
        self.assertEqual(selection.name, "plan_week")


class FreeTextReviewKindTests(unittest.TestCase):
    def test_typed_reviews_get_their_kind_and_playbook(self) -> None:
        cases = {
            "Analysiere meine letzte Einheit": "session_analysis",
            "Wie lief mein Intervalltraining gestern?": "session_analysis",
            "Wie war mein Tempolauf?": "session_analysis",
            "Analysiere meinen Lauf vom 2.11.": "session_analysis",
            "How was my ride?": "session_analysis",
            "Analysiere die letzte Einheit des Blocks": "session_analysis",
            "Analysiere meinen Lauf von letzter Woche Dienstag": "session_analysis",
            "Zeig mir meinen Fortschritt": "progress_review",
            "Wie ist mein Fortschritt?": "progress_review",
            "Werde ich fitter?": "progress_review",
            "Bewerte meinen letzten Block": "block_review",
        }
        for message, kind in cases.items():
            with self.subTest(message=message):
                self.assertEqual(free_text_review_kind(message), kind)
                self.assertEqual(select_coach_context(message, {}).kind, kind)

    def test_other_messages_keep_their_selection(self) -> None:
        for message in (
            "Analysiere den Verlauf meiner HRV",
            "Analysiere meine Läufe der letzten Woche",
            "Wie war meine Woche?",
            "Wie ist die Entwicklung meines Gewichts?",
            "Analysiere meine letzte Einheit und plane darauf basierend morgen",
            "Soll ich einen Progressionslauf machen?",
            "Was ist ein Progressionslauf?",
            "Wie werde ich fitter?",
            "Wie ist die Entwicklung meiner HRV?",
            "Wie war mein Schlaf nach der Einheit?",
            "Wie war meine Erholung nach dem Intervalltraining?",
            "Wie geht es meiner Erholung?",
            "Ich habe 60g Whey getrunken",
        ):
            with self.subTest(message=message):
                self.assertNotIn(
                    select_coach_context(message, {}).kind,
                    {"session_analysis", "progress_review", "block_review"},
                )
        self.assertEqual(
            select_coach_context("Plane die nächste Woche", {}).kind, "plan_week"
        )

    def test_typed_review_keeps_what_the_message_asked_for(self) -> None:
        weather = select_coach_context(
            "How did my interval session go and what is the weather tomorrow?", {}
        )
        self.assertEqual(weather.kind, "session_analysis")
        self.assertIn("weather", weather.sections)
        dated = select_coach_context("Analysiere meinen Lauf vom 2.11.", {})
        self.assertEqual(dated.kind, "session_analysis")
        self.assertNotIn("planning_brief", dated.sections)


class RequestKindSelectionTests(unittest.TestCase):
    def test_plan_kinds_load_plan_calendar_recovery_and_weather(self) -> None:
        for kind in ("plan_week", "plan_block"):
            sections = select_coach_context("ok", {}, request_kind=kind).sections
            with self.subTest(kind=kind):
                self.assertLessEqual(
                    {
                        "planning",
                        "training_plans",
                        "external_calendar",
                        "daily_planning_context",
                        "recovery",
                        "weather",
                        "durable_profile",
                    },
                    sections,
                )
                self.assertNotIn("calendar", sections)
                self.assertNotIn("nutrition_products", sections)

    def test_review_and_analysis_kinds_load_what_they_need(self) -> None:
        progress = select_coach_context("x", {}, request_kind="progress_review")
        self.assertLessEqual({"planning", "recovery", "activities"}, progress.sections)
        for dropped in ("training_plans", "daily_planning_context"):
            self.assertNotIn(dropped, progress.sections)
        self.assertEqual(progress.horizon_days, 0)
        analysis = select_coach_context("x", {}, request_kind="session_analysis")
        self.assertEqual(analysis.name, "session_analysis")
        self.assertIn("durable_profile", analysis.sections)
        self.assertLessEqual(
            {"local_planned_workouts", "activities", "recovery", "current_performance"},
            analysis.sections,
        )
        for heavy in (
            "weather",
            "calendar",
            "external_calendar",
            "training_plans",
            "daily_planning_context",
        ):
            self.assertNotIn(heavy, analysis.sections)
        self.assertEqual(analysis.horizon_days, 2)
        # The latest session keeps the today-based planned-unit window; an older
        # session brings its own plan with get_activity_details.
        self.assertEqual(analysis.past_planned_days, 0)

    def test_confirmation_after_food_exchange_keeps_products(self) -> None:
        history = {
            "messages": [
                {"id": 1, "role": "user", "content": "Speichere Mahlzeit Porridge"},
                {"id": 2, "role": "assistant", "content": "Soll ich speichern?"},
            ]
        }
        self.assertIn(
            "nutrition_products", select_coach_context("ja", history).sections
        )
        self.assertNotIn(
            "nutrition_products",
            select_coach_context("ja", {"messages": []}).sections,
        )

    def test_message_food_survives_a_fixed_kind(self) -> None:
        sections = select_coach_context(
            "80g Haferflocken gegessen", {}, request_kind="plan_week"
        ).sections
        self.assertIn("nutrition_products", sections)

    def test_upload_alone_adds_no_products_to_a_fixed_kind(self) -> None:
        for kind in ("session_analysis", "plan_week"):
            sections = select_coach_context(
                "Analysiere meine letzte Einheit.",
                {},
                attachments=True,
                request_kind=kind,
            ).sections
            with self.subTest(kind=kind):
                self.assertNotIn("nutrition_products", sections)

    def test_nutrition_topics_without_intake_wording_select_products(self) -> None:
        for message in (
            "Welche meiner gespeicherten Produkte passen dazu?",
            "Ändere die Vorlage auf zwei Portionen.",
            "Whey-Shake nach dem Training",
        ):
            with self.subTest(message=message):
                self.assertIn(
                    "nutrition_products", select_coach_context(message, {}).sections
                )

    def test_base_prompt_keeps_core_nutrition_write_rules(self) -> None:
        for marker in (
            "log a consumed meal once with save_nutrition_entry",
            "matching saved local products by exact product_id first",
            "log_nutrition_template by exact ID",
            "never save hypothetical or negated consumption",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, COACH_PROMPT)

    def test_every_kind_has_a_selection_and_keeps_message_retention(self) -> None:
        kinds = set(REQUEST_KINDS) | {"morning_checkin"}
        self.assertEqual(set(REQUEST_KIND_SELECTIONS), kinds)
        context = {
            "pending_request": {"status": "needs_clarification", "summary": "x"},
            "messages": [],
        }
        for kind in kinds:
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

    def test_unknown_kinds_use_message_selection(self) -> None:
        expected = select_coach_context("Wie geht es mir?", {}).name
        for kind in (None, "unknown_kind"):
            self.assertEqual(
                select_coach_context("Wie geht es mir?", {}, request_kind=kind).name,
                expected,
            )
        self.assertEqual("", playbook_for("morning_checkin"))


if __name__ == "__main__":
    unittest.main()
