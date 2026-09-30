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
                self.assertEqual(selection.sections, CoachContextSelection("fallback").sections)
                self.assertIsNone(selection.planned_horizon_days)

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

    def test_pending_receipts_and_continuations_use_full_fallback(self):
        cases = [
            ("Ja", {}, {}),
            ("Mach das", {}, {}),
            ("Auf Freitag", {"pending_request": {"source_message_ids": [1]}}, {}),
            ("Plan fortsetzen", {}, {"has_receipts": True}),
        ]
        for message, dialogue, kwargs in cases:
            with self.subTest(message=message):
                selection = select_coach_context(message, dialogue, **kwargs)
                self.assertEqual(selection.name, "fallback")
                self.assertIsNone(selection.horizon_days)

    def test_attachments_preserve_full_tool_availability(self):
        selection = select_coach_context("Prüfe die Route", {}, attachments=True)
        self.assertEqual(selection.name, "attachment_analysis")
        tools = [{"name": "read_coach_context"}, {"name": "save_nutrition_entry"}]
        self.assertEqual(select_coach_tools(tools, selection), tools)

    def test_long_range_planning_uses_complete_context(self):
        for message in ("Plane 8 Wochen", "Plane bis 2026-12-01", "Plan next month"):
            with self.subTest(message=message):
                self.assertIsNone(select_coach_context(message, {}).horizon_days)

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
            compact_coach_dialogue(context, CoachContextSelection("fallback")), context
        )

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
