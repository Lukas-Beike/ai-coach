import unittest
from unittest.mock import Mock

from server_test_support import server

from backend.coach.context_selection import (
    CoachContextSelection,
    compact_coach_dialogue,
    select_coach_context,
)
from backend.coach.request_payload import CoachRequestPayloadService


class CoachContextSelectionTests(unittest.TestCase):
    def setUp(self):
        training_context = Mock()
        training_context.build.return_value = "Synthetic local context"
        settings = Mock()
        settings.selected_model.return_value = "synthetic-model"
        settings.selected_thinking_level.return_value = "medium"
        self.payload_service = CoachRequestPayloadService(
            training_context, settings, max_output_tokens=1024
        )

    def offered_tools(self, message):
        _, payload = self.payload_service.build(
            message=message,
            context={"local_date": "2026-10-07"},
            command_receipts=[],
            tools=server.COACH_DIALOGUE_TOOLS,
            allow_mutations=True,
            model="synthetic-model",
            thinking_level="medium",
            conversation_id="synthetic-conversation",
            attachments=[],
            retain_openai_attachment_context=False,
            has_prior_openai_attachments=False,
        )
        return {tool["name"] for tool in payload["tools"]}

    def test_explicit_dates_without_planning_keywords_use_full_context(self):
        for message in (
            "What should I train on 2026-12-01?",
            "Was trainiere ich am 01.12.?",
        ):
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertEqual(
                    selection.sections, CoachContextSelection("fallback").sections
                )
                self.assertIsNone(selection.horizon_days)

    def test_profiles(self):
        examples = {
            "Wie geht es meiner Erholung?": "general_coaching",
            "Was trainiere ich heute?": "today_training",
            "Analysiere meine letzte Einheit": "activity_analysis",
            "Plane nächste Woche": "weekly_planning",
            "Verschiebe den Lauf auf Freitag": "plan_editing",
            "Wie steht meine Wettkampfvorbereitung?": "competition_preparation",
            "Speichere meinen Check-in": "profile_or_checkin",
            "Synchronisiere den Plan": "provider_refresh_or_sync",
        }
        for message, expected in examples.items():
            with self.subTest(profile=expected):
                self.assertEqual(select_coach_context(message, {}).name, expected)

    def test_pending_requests_and_short_continuations_use_full_fallback(self):
        cases = [
            ("Ja", {}, {}),
            ("Mach das", {}, {}),
            ("Mach den Plan", {}, {}),
            (
                "Was ist das Training fuer heute?",
                {"pending_request": {"source_message_ids": [1]}},
                {},
            ),
            ("Auf Freitag", {"pending_request": {"source_message_ids": [1]}}, {}),
            ("Plan fortsetzen", {}, {"has_receipts": True}),
        ]
        for message, dialogue, kwargs in cases:
            with self.subTest(message=message):
                selection = select_coach_context(message, dialogue, **kwargs)
                self.assertEqual(selection.name, "fallback")
                self.assertIsNone(selection.horizon_days)

    def test_explicit_topics_with_pronouns_keep_compact_context_and_full_dialogue(self):
        examples = {
            "Was ist das Training fuer heute?": "today_training",
            "Kannst du diese letzte Einheit analysieren?": "activity_analysis",
            "Kannst du das Training fuer naechste Woche planen?": "weekly_planning",
            "Please analyse that latest activity": "activity_analysis",
        }
        for message, expected in examples.items():
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertEqual(selection.name, expected)
                self.assertIsNotNone(selection.horizon_days)
                self.assertTrue(selection.retain_dialogue)

    def test_receipts_preserve_profile_and_dialogue_without_expanding_training_data(
        self,
    ):
        for message in (
            "How is recovery?",
            "Was trainiere ich heute?",
            "Analysiere meine letzte Einheit",
            "Plan next week",
        ):
            with self.subTest(message=message):
                original = select_coach_context(message, {})
                selected = select_coach_context(message, {}, has_receipts=True)
                self.assertEqual(selected.name, original.name)
                self.assertEqual(selected.sections, original.sections)
                self.assertEqual(selected.horizon_days, original.horizon_days)
                self.assertTrue(selected.retain_dialogue)

    def test_attachments_preserve_full_tool_availability(self):
        selection = select_coach_context("Prüfe die Route", {}, attachments=True)
        self.assertEqual(selection.name, "attachment_analysis")
        self.assertEqual(
            self.offered_tools("Prüfe die Route"),
            {tool["name"] for tool in server.COACH_DIALOGUE_TOOLS},
        )

    def test_food_keyword_does_not_match_latest_or_weather(self):
        for message, expected in (
            ("Analyse the latest activity", "activity_analysis"),
            ("How is the weather today?", "today_training"),
            ("I ate lunch", "profile_or_checkin"),
        ):
            with self.subTest(message=message):
                self.assertEqual(select_coach_context(message, {}).name, expected)

    def test_long_range_planning_uses_complete_context(self):
        for message in (
            "Plane 8 Wochen",
            "Plane bis 2026-12-01",
            "Plan next month",
            "Kannst du das Training fuer drei Wochen planen?",
            "Please plan that for three weeks",
            "Plane das Training fuer die kommenden Tage",
        ):
            with self.subTest(message=message):
                self.assertIsNone(select_coach_context(message, {}).horizon_days)

    def test_pronoun_requests_with_multiple_topics_keep_conservative_context(self):
        for message in (
            "Kannst du das letzte Rennen analysieren?",
            "Kannst du das Training planen und meinen Check-in speichern?",
        ):
            with self.subTest(message=message):
                self.assertEqual(select_coach_context(message, {}).name, "fallback")

    def test_date_window_and_activity_limits_preserve_provenance(self):
        selection = select_coach_context("Was trainiere ich heute?", {})
        context = {
            "daily_planning_context": [
                {"date": "2026-09-30", "health": {"source": "Garmin"}},
                {"date": "2026-10-15"},
            ],
            "local_planned_workouts": [{"date": "2026-10-01"}, {"date": "2026-10-15"}],
            "intervals": {
                "synced_at": "2026-09-30T06:00:00Z",
                "recent_activities_by_sport": {"Run": [{"id": "new"}, {"id": "old"}]},
                "planned_workouts": [{"id": "duplicate"}],
            },
            "garmin": {"raw": "unused"},
        }
        projected = selection.project(context, "2026-09-30")
        self.assertEqual(len(projected["daily_planning_context"]), 1)
        self.assertEqual(
            projected["daily_planning_context"][0]["health"]["source"], "Garmin"
        )
        self.assertEqual(len(projected["local_planned_workouts"]), 1)
        self.assertEqual(
            len(projected["intervals"]["recent_activities_by_sport"]["Run"]), 1
        )
        self.assertNotIn("planned_workouts", projected["intervals"])
        self.assertNotIn("garmin", projected)
        self.assertIn("planned_workouts", context["intervals"])

    def test_dialogue_compaction_does_not_mutate_authorization_context(self):
        context = {
            "current_user_message_id": 24,
            "messages": [{"id": index, "role": "user"} for index in range(25)],
            "confirmed_results": list(range(12)),
        }
        compact = compact_coach_dialogue(
            context, select_coach_context("How is recovery?", {})
        )
        self.assertLessEqual(len(compact["messages"]), 8)
        self.assertNotIn(24, [message["id"] for message in compact["messages"]])
        self.assertEqual(len(compact["confirmed_results"]), 3)
        self.assertEqual(len(context["messages"]), 25)
        self.assertEqual(
            compact_coach_dialogue(context, CoachContextSelection("fallback")),
            {**context, "messages": context["messages"][:-1]},
        )

    def test_compact_training_selection_keeps_referenced_dialogue_and_receipts(self):
        pending = {"source_message_ids": [1], "question": "Which date?"}
        context = {
            "current_user_message_id": 24,
            "messages": [{"id": index, "role": "user"} for index in range(25)],
            "confirmed_results": list(range(12)),
            "pending_request": pending,
            "attachment_evidence": [{"source_message_id": 1}],
        }
        selection = select_coach_context("Was ist das Training fuer heute?", {})
        compact = compact_coach_dialogue(context, selection)
        self.assertEqual(compact["messages"], context["messages"][:-1])
        self.assertEqual(compact["confirmed_results"], context["confirmed_results"])
        self.assertEqual(compact["pending_request"], pending)
        self.assertEqual(compact["attachment_evidence"], context["attachment_evidence"])
        self.assertEqual(len(context["messages"]), 25)

    def test_missing_current_message_id_does_not_remove_unidentified_messages(self):
        context = {
            "messages": [{"role": "user", "content": "Synthetic earlier message"}]
        }
        compact = compact_coach_dialogue(
            context, select_coach_context("How is recovery?", {})
        )
        self.assertEqual(compact["messages"], context["messages"])

    def test_rephrased_requests_offer_required_registered_tools(self):
        cases = {
            "Ich bin krank und habe Fieber": {
                "save_checkin",
                "preview_adaptive_replan",
            },
            "Trag 2 Bananen ein": {"save_nutrition_entry"},
            "Mein Ruhepuls war heute 48, Schlaf 6 von 10": {"save_checkin"},
            "Ich will am 12. Oktober beim Stadtlauf starten": {"save_competition"},
            "Lösche die doppelte Aktivität von gestern": {
                "delete_duplicate_intervals_activity"
            },
            "Gleiche die Ernährung mit Intervals ab": {"sync_nutrition"},
            "Speichere einen Verpflegungsplan für den Halbmarathon": {
                "save_fueling_plan"
            },
        }
        registered = {tool["name"] for tool in server.COACH_DIALOGUE_TOOLS}
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertTrue(expected <= registered)
                self.assertTrue(expected <= self.offered_tools(message))
