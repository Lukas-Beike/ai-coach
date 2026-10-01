import unittest

from backend.coach.context_selection import (
    CoachContextSelection,
    compact_coach_dialogue,
    select_coach_context,
    select_coach_tools,
)


class CoachContextSelectionTests(unittest.TestCase):
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
        tools = [{"name": "read_coach_context"}, {"name": "save_nutrition_entry"}]
        self.assertEqual(select_coach_tools(tools, selection), tools)

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

    def test_tool_filter_keeps_detail_read_but_no_remote_write(self):
        tools = [
            {"name": name}
            for name in (
                "read_coach_context",
                "read_profile",
                "get_activity_details",
                "apply_training_patch",
                "start_intervals_plan_sync",
                "save_checkin",
            )
        ]
        general = select_coach_tools(
            tools, select_coach_context("How is recovery?", {})
        )
        self.assertEqual(
            {tool["name"] for tool in general},
            {
                "read_coach_context",
                "read_profile",
                "get_activity_details",
            },
        )
        planning = select_coach_tools(
            tools, select_coach_context("Plane nächste Woche", {})
        )
        self.assertIn("apply_training_patch", {tool["name"] for tool in planning})
        self.assertNotIn(
            "start_intervals_plan_sync", {tool["name"] for tool in planning}
        )
