import json
import unittest
from unittest.mock import Mock

from server_test_support import server

from backend.coach.context import CoachStructuredContextService
from backend.coach.context_selection import (
    BASE_SECTIONS,
    CONTEXT_SECTIONS,
    FULL_SECTIONS,
    CoachContextSelection,
    compact_coach_dialogue,
    infer_coach_domain,
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

    def test_food_intake_adds_saved_products_section_only_for_food(self):
        for message in (
            "Frühstück: 77g Banane, 60g Whey, 100g Mandeldrink",
            "I ate lunch",
            "Ich habe einen Shake getrunken",
        ):
            with self.subTest(message=message):
                sections = select_coach_context(message, {}).sections
                self.assertEqual(sections, BASE_SECTIONS | {"nutrition_products"})
        for message in (
            "Speichere meinen Check-in",
            "Wie ist mein Befinden?",
            "Was soll ich heute Nachmittag trainieren?",
        ):
            with self.subTest(message=message):
                sections = select_coach_context(message, {}).sections
                self.assertNotIn("nutrition_products", sections)

    def test_structured_context_lists_compact_saved_products(self):
        library = Mock()
        library.list_products.return_value = [
            {
                "id": "p1",
                "name": "Bio Whey Protein",
                "brand": "Rheinnatur",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 400,
                "provenance": {"kind": "manual"},
            }
        ]
        service = CoachStructuredContextService(
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            lambda: library.list_products(),
        )
        section = service._selected_sections(
            frozenset({"nutrition_products"}), {}, {}, [], {}, []
        )["nutrition_products"]
        self.assertEqual(
            section,
            [
                {
                    "id": "p1",
                    "name": "Bio Whey Protein",
                    "brand": "Rheinnatur",
                    "basis_amount": 100,
                    "basis_unit": "g",
                }
            ],
        )

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
            "activities": {
                "synced_at": "2026-09-30T06:00:00Z",
                "recent_activities_by_sport": {"Run": [{"id": "new"}, {"id": "old"}]},
                "planned_workouts": [{"id": "duplicate"}],
            },
            "recovery": {"raw": "unused"},
        }
        projected = selection.project(context, "2026-09-30")
        self.assertEqual(len(projected["daily_planning_context"]), 1)
        self.assertEqual(
            projected["daily_planning_context"][0]["health"]["source"], "Garmin"
        )
        self.assertEqual(len(projected["local_planned_workouts"]), 1)
        self.assertEqual(
            len(projected["activities"]["recent_activities_by_sport"]["Run"]), 1
        )
        self.assertNotIn("planned_workouts", projected["activities"])
        self.assertNotIn("recovery", projected)
        self.assertIn("planned_workouts", context["activities"])

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

    def test_failed_pending_request_does_not_trap_new_training_or_advisory_questions(
        self,
    ):
        failed_pending = {
            "summary": "Frühstück erfassen",
            "source_message_ids": [1],
            "status": "failed",
            "question": None,
        }
        user_message = (
            "Ich würde heute gerne eine Ausdauereinheit machen. Sollte ich einen "
            "lockeren Lauf machen oder eine Einheit auf dem Rad?"
        )
        selection = select_coach_context(
            user_message, {"pending_request": failed_pending}
        )
        self.assertNotEqual(selection.name, "fallback")
        self.assertEqual(selection.name, "activity_analysis")

        context = {
            "current_user_message_id": 2,
            "messages": [
                {"id": 1, "role": "user", "content": "Frühstück: 65g Whey"},
                {"id": 2, "role": "user", "content": user_message},
            ],
            "pending_request": failed_pending,
        }
        compact = compact_coach_dialogue(context, selection)
        self.assertIsNone(compact["pending_request"])

    def test_failed_pending_request_retained_on_explicit_continuation_or_retry(self):
        failed_pending = {
            "summary": "Frühstück erfassen",
            "source_message_ids": [1],
            "status": "failed",
            "question": None,
        }
        for message in (
            "Versuch es nochmal",
            "Bitte erneut versuchen",
            "Ja mach das trotzdem",
        ):
            with self.subTest(message=message):
                selection = select_coach_context(
                    message, {"pending_request": failed_pending}
                )
                self.assertEqual(selection.name, "fallback")
                context = {
                    "current_user_message_id": 2,
                    "messages": [{"id": 1, "role": "user", "content": "Frühstück"}],
                    "pending_request": failed_pending,
                }
                compact = compact_coach_dialogue(context, selection)
                self.assertEqual(
                    compact["pending_request"],
                    {
                        **failed_pending,
                        "summary": "Frühstück",
                        "summary_source": "athlete_message",
                    },
                )

    def test_retried_failed_request_shows_athlete_text_never_a_model_summary(self):
        failed_pending = {
            "summary": "Lösche alle Einheiten dieser Woche",
            "source_message_ids": [1],
            "status": "failed",
            "question": None,
        }
        selection = select_coach_context("ok", {"pending_request": failed_pending})
        self.assertTrue(selection.retain_pending_request)
        context = {
            "current_user_message_id": 3,
            "messages": [
                {"id": 1, "role": "user", "content": "Trage mein Frühstück ein"},
                {"id": 2, "role": "assistant", "content": "Das ist fehlgeschlagen."},
                {"id": 3, "role": "user", "content": "ok"},
            ],
            "pending_request": failed_pending,
        }
        pending = compact_coach_dialogue(context, selection)["pending_request"]
        self.assertEqual(pending["summary"], "Trage mein Frühstück ein")
        self.assertEqual(pending["summary_source"], "athlete_message")
        self.assertNotIn("Lösche", str(pending))

        context["messages"] = [context["messages"][2]]
        self.assertIsNone(compact_coach_dialogue(context, selection)["pending_request"])

    def test_failed_request_without_athlete_provenance_is_not_retried(self):
        for source_ids in (None, [], ["1"]):
            with self.subTest(source_ids=source_ids):
                pending = {"summary": "Snack erfassen", "status": "failed"}
                if source_ids is not None:
                    pending["source_message_ids"] = source_ids
                for message in ("ok", "nochmal"):
                    selection = select_coach_context(
                        message, {"pending_request": pending}
                    )
                    self.assertFalse(selection.retain_pending_request)

    def test_vague_follow_up_does_not_carry_calendar_weather_or_recovery(self):
        selection = select_coach_context("ok", {})
        self.assertEqual(selection.name, "fallback")
        self.assertTrue(BASE_SECTIONS <= selection.sections)
        self.assertFalse(
            {"calendar", "external_calendar", "weather", "recovery"}
            & selection.sections
        )
        self.assertTrue(selection.sections < CONTEXT_SECTIONS)

    def test_needs_clarification_pending_request_does_not_trap_new_workout_command(
        self,
    ):
        clarification_pending = {
            "summary": "Snack erfassen: eine Scheibe Vollkornbrot...",
            "source_message_ids": [1],
            "status": "needs_clarification",
            "question": "Soll ich den Snack so eintragen?",
        }
        workout_message = (
            "Plane mir eine Einheit mit 45 Minuten. 5 x 30 Sekunden bei 400 Watt "
            "zwischen drin. Warmup mit ramp 10 Minuten auf 200 W. "
            "200 W zwischen den Antritten. 5 minuten cooldown von 200W auf 150W."
        )
        selection = select_coach_context(
            workout_message, {"pending_request": clarification_pending}
        )
        self.assertNotEqual(selection.name, "fallback")
        self.assertEqual(selection.name, "weekly_planning")

        context = {
            "current_user_message_id": 2,
            "messages": [
                {"id": 1, "role": "user", "content": "Snack: Brot und Kaese"},
                {"id": 2, "role": "user", "content": workout_message},
            ],
            "pending_request": clarification_pending,
        }
        compact = compact_coach_dialogue(context, selection)
        self.assertIsNone(compact["pending_request"])

    def test_needs_clarification_pending_request_retained_on_continuation_or_short_answer(
        self,
    ):
        clarification_pending = {
            "summary": "Snack erfassen: eine Scheibe Vollkornbrot...",
            "source_message_ids": [1],
            "status": "needs_clarification",
            "question": "Soll ich den Snack so eintragen?",
        }
        for message in ("Ja bitte", "Mach das", "Die zweite", "Auf Freitag", "Samstag"):
            with self.subTest(message=message):
                selection = select_coach_context(
                    message, {"pending_request": clarification_pending}
                )
                self.assertEqual(selection.name, "fallback")
                context = {
                    "current_user_message_id": 2,
                    "messages": [
                        {"id": 1, "role": "user", "content": "Snack: Brot und Kaese"}
                    ],
                    "pending_request": clarification_pending,
                }
                compact = compact_coach_dialogue(context, selection)
                self.assertEqual(compact["pending_request"], clarification_pending)

    def test_concise_freeform_answer_retains_an_active_clarification(self):
        pending = {
            "summary": "Tagesform für heute festhalten",
            "source_message_ids": [1],
            "status": "needs_clarification",
            "question": "Wie fühlen sich deine Beine an?",
        }
        selection = select_coach_context(
            "Ziemlich schwer.", {"pending_request": pending}
        )
        self.assertEqual(selection.name, "fallback")
        self.assertEqual(
            compact_coach_dialogue({"pending_request": pending}, selection)[
                "pending_request"
            ],
            pending,
        )

        unrelated_question = select_coach_context(
            "Faszienrollen sinnvoll?", {"pending_request": pending}
        )
        self.assertNotEqual(unrelated_question.name, "fallback")
        self.assertIsNone(
            compact_coach_dialogue({"pending_request": pending}, unrelated_question)[
                "pending_request"
            ]
        )

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
        }
        registered = {tool["name"] for tool in server.COACH_DIALOGUE_TOOLS}
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertTrue(expected <= registered)
                self.assertTrue(expected <= self.offered_tools(message))

    def test_profile_or_checkin_restored_terms(self):
        cases = {
            "meine Ernährung heute war schlecht": "profile_or_checkin",
            "Mein Check in ist fertig": "profile_or_checkin",
            "Ich habe eine Mahlzeit eingetragen": "profile_or_checkin",
            "Wie ist mein Befinden?": "profile_or_checkin",
            "Zum Fruehstueck gab es Haferflocken": "profile_or_checkin",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(select_coach_context(message, {}).name, expected)

    def test_needs_clarification_domain_conflict_or_unmatched_does_not_trap(self):
        clarification_pending = {
            "summary": "Snack erfassen: eine Scheibe Vollkornbrot...",
            "source_message_ids": [1],
            "status": "needs_clarification",
            "domain": "nutrition_or_profile",
            "question": "Soll ich den Snack so eintragen?",
        }
        # 3-word message in training domain:
        training_short = "Plane Intervalle morgen"
        selection = select_coach_context(
            training_short, {"pending_request": clarification_pending}
        )
        self.assertNotEqual(selection.name, "fallback")
        self.assertEqual(selection.name, "weekly_planning")

        # Unmatched long advisory question:
        advisory_msg = "Was haeltst du von Faszienrollen nach einem langen Lauf?"
        selection = select_coach_context(
            advisory_msg, {"pending_request": clarification_pending}
        )
        self.assertNotEqual(selection.name, "fallback")
        self.assertEqual(selection.name, "general_coaching")

    def test_failed_pending_request_not_reactivated_by_pronouns_or_cross_domain_wording(
        self,
    ):
        failed_pending = {
            "summary": "Frühstück erfassen",
            "source_message_ids": [1],
            "status": "failed",
            "domain": "nutrition_or_profile",
            "question": None,
        }
        # Contains 'das':
        msg1 = "Das Training heute war hart, was empfiehlst du morgen?"
        selection1 = select_coach_context(msg1, {"pending_request": failed_pending})
        self.assertNotEqual(selection1.name, "fallback")
        self.assertEqual(selection1.name, "today_training")

        # Contains 'wiederhol' in training context:
        msg2 = "Wiederhole die Einheit von gestern"
        selection2 = select_coach_context(msg2, {"pending_request": failed_pending})
        self.assertNotEqual(selection2.name, "fallback")
        self.assertEqual(selection2.name, "activity_analysis")

    def test_unrelated_short_messages_and_embedded_retry_words_abandon_pending(self):
        for status in ("failed", "needs_clarification"):
            pending = {
                "summary": "Snack erfassen",
                "status": status,
                "domain": "nutrition_or_profile",
            }
            for message in (
                "Faszienrollen sinnvoll?",
                "Okay, welche Schuhe empfiehlst du?",
                "Ja, welche Schuhe empfiehlst du?",
                "It was hard yesterday",
                "Das Training war trotzdem gut",
                "Ich bin erneut müde",
                "Wiederholen wir die Einheit morgen?",
                "Mach das Training im Kalender morgen leichter",
            ):
                with self.subTest(status=status, message=message):
                    selection = select_coach_context(
                        message, {"pending_request": pending}
                    )
                    self.assertIsNone(
                        compact_coach_dialogue({"pending_request": pending}, selection)[
                            "pending_request"
                        ]
                    )

    def test_recorded_domain_ignores_incidental_today_and_keeps_same_domain_reply(self):
        self.assertEqual(
            infer_coach_domain("Frühstück heute erfassen"), "nutrition_or_profile"
        )
        self.assertEqual(infer_coach_domain("Synchronisiere heute"), "sync")
        self.assertIsNone(infer_coach_domain("Unmatched synthetic request"))
        pending = {
            "summary": "Synthetic request",
            "status": "needs_clarification",
            "domain": "nutrition_or_profile",
        }
        selection = select_coach_context(
            "Zum Frühstück 500 kcal", {"pending_request": pending}
        )
        self.assertEqual(selection.name, "fallback")
        self.assertEqual(
            compact_coach_dialogue({"pending_request": pending}, selection)[
                "pending_request"
            ],
            pending,
        )

    def test_failed_pending_supports_explicit_english_retry(self):
        pending = {
            "summary": "Snack erfassen",
            "status": "failed",
            "source_message_ids": [1],
        }
        selection = select_coach_context(
            "Please try again", {"pending_request": pending}
        )
        self.assertTrue(selection.retain_pending_request)

    def test_attachment_continuity_does_not_restore_abandoned_pending_request(self):
        _, payload = self.payload_service.build(
            message="Plane Intervalle morgen",
            context={
                "current_user_message_id": 2,
                "local_date": "2026-10-07",
                "timezone": "Europe/Berlin",
                "pending_request": {
                    "summary": "Snack erfassen",
                    "status": "needs_clarification",
                    "domain": "nutrition_or_profile",
                },
            },
            command_receipts=[],
            tools=[],
            allow_mutations=True,
            model="synthetic-model",
            thinking_level="medium",
            conversation_id="synthetic-conversation",
            attachments=[],
            retain_openai_attachment_context=True,
            has_prior_openai_attachments=True,
        )
        self.assertIsNone(json.loads(payload["input"])["pending_request"])


class CoachContextRuleTests(unittest.TestCase):
    def test_weekday_weather_question_adds_weather_and_extends_horizon(self):
        selection = select_coach_context(
            "Wie wird das Wetter am Samstag für die lange Ausfahrt?", {}
        )
        self.assertIn("weather", selection.sections)
        self.assertEqual(7, selection.horizon_days)

    def test_plain_weather_question_adds_weather_section(self):
        selection = select_coach_context("Regnet es Donnerstag?", {})
        self.assertIn("weather", selection.sections)
        self.assertEqual(7, selection.horizon_days)

    def test_weekday_without_weather_keeps_short_horizon(self):
        selection = select_coach_context("Was trainiere ich am Samstag?", {})
        self.assertNotIn("weather", selection.sections)
        self.assertEqual(3, selection.horizon_days)

    def test_history_comparison_selects_complete_context_and_keeps_comparisons(self):
        selection = select_coach_context(
            "Was hältst du von meinem Lauf heute Morgen im Vergleich zu letzter Woche?",
            {},
        )
        self.assertIsNone(selection.horizon_days)
        self.assertEqual(FULL_SECTIONS, selection.sections)
        projected = selection.project(
            {"current_performance": {"ctl": 40, "comparisons": [{"week": "last"}]}},
            "2026-10-18",
        )
        self.assertEqual(
            [{"week": "last"}], projected["current_performance"]["comparisons"]
        )

    def test_long_period_history_selects_complete_context(self):
        selection = select_coach_context(
            "Wie sieht meine Belastung über die letzten zwei Monate aus?", {}
        )
        self.assertIsNone(selection.horizon_days)
        self.assertGreaterEqual(selection.activity_limit, 5)

    def test_past_week_without_planning_verb_is_activity_review(self):
        message = "Wie war mein Lauf letzte Woche?"
        selection = select_coach_context(message, {})
        self.assertEqual("activity_analysis", selection.name)
        self.assertIsNone(selection.horizon_days)
        self.assertEqual(5, selection.activity_limit)
        self.assertEqual("training", infer_coach_domain(message))

    def test_retrospective_past_week_phrasings_select_activity_analysis(self):
        for message in (
            "Was habe ich letzte Woche trainiert?",
            "Wie war mein Training in den letzten Wochen?",
            "Wie lief die vorletzte Woche?",
            "How was last week?",
        ):
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertEqual("activity_analysis", selection.name)
                self.assertIsNone(selection.horizon_days)
                self.assertEqual(5, selection.activity_limit)

    def test_past_week_keeps_other_topic_domains(self):
        self.assertEqual(
            "nutrition_or_profile",
            infer_coach_domain("Was habe ich letzte Woche gegessen?"),
        )

    def test_past_week_with_planning_verb_stays_weekly_planning(self):
        selection = select_coach_context("Plane meine letzte Woche neu", {})
        self.assertEqual("weekly_planning", selection.name)
        self.assertEqual(14, selection.horizon_days)

    def test_planning_request_with_past_week_reference_stays_weekly_planning(self):
        selection = select_coach_context(
            "Plane die nächste Woche basierend auf letzter Woche", {}
        )
        self.assertEqual("weekly_planning", selection.name)
        self.assertEqual(14, selection.horizon_days)

    def test_past_week_pattern_stays_narrow(self):
        selection = select_coach_context("Wie war die letzte Nacht?", {})
        self.assertEqual("general_coaching", selection.name)
        self.assertEqual(3, selection.horizon_days)
        numbered = select_coach_context("Wie war mein Training letzten 2 Wochen?", {})
        self.assertNotEqual("activity_analysis", numbered.name)
        self.assertIsNone(numbered.horizon_days)

    def test_full_calendar_cues_add_external_calendar(self):
        for message in (
            "Habe ich nächste Woche Termine, die mit dem Training kollidieren?",
            "Was steht in meinem Kalender?",
        ):
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertIn("external_calendar", selection.sections)

    def test_ordinary_message_shapes_are_unchanged(self):
        planning = BASE_SECTIONS | {"planning", "training_plans"}
        cases = (
            (
                "Wie geht es meiner Erholung?",
                "general_coaching",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Was trainiere ich heute?",
                "today_training",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Analysiere meine letzte Einheit",
                "activity_analysis",
                BASE_SECTIONS,
                3,
                5,
                False,
                False,
            ),
            ("Plane nächste Woche", "weekly_planning", planning, 14, 5, True, False),
            (
                "Verschiebe den Lauf auf Freitag",
                "plan_editing",
                planning,
                14,
                5,
                True,
                False,
            ),
            (
                "Speichere meinen Check-in",
                "profile_or_checkin",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Synchronisiere den Plan",
                "provider_refresh_or_sync",
                FULL_SECTIONS,
                None,
                5,
                True,
                False,
            ),
            (
                "Wie steht meine Wettkampfvorbereitung?",
                "competition_preparation",
                planning,
                14,
                5,
                True,
                False,
            ),
            (
                "Wie ist mein Befinden?",
                "profile_or_checkin",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Was trainiere ich am Samstag?",
                "general_coaching",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Kannst du das Training fuer naechste Woche planen?",
                "weekly_planning",
                planning,
                14,
                5,
                True,
                True,
            ),
            (
                "Plane 8 Wochen",
                "weekly_planning",
                FULL_SECTIONS,
                None,
                5,
                True,
                False,
            ),
            (
                "How did I sleep last night?",
                "general_coaching",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Was steht heute im Plan?",
                "weekly_planning",
                planning,
                14,
                5,
                True,
                False,
            ),
            (
                "Wie ist meine aktuelle CTL und Form?",
                "general_coaching",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
            (
                "Analyse the latest activity",
                "activity_analysis",
                BASE_SECTIONS,
                3,
                5,
                False,
                False,
            ),
            (
                "Wann ist mein nächster Wettkampf?",
                "competition_preparation",
                planning,
                14,
                5,
                True,
                False,
            ),
            (
                "Kann ich Mittwochabend lang laufen oder hab ich da was vor?",
                "general_coaching",
                BASE_SECTIONS,
                3,
                1,
                False,
                False,
            ),
        )
        for message, name, sections, horizon, limit, library, dialogue in cases:
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertEqual(name, selection.name)
                self.assertEqual(sections, selection.sections)
                self.assertEqual(horizon, selection.horizon_days)
                self.assertEqual(limit, selection.activity_limit)
                self.assertEqual(library, selection.include_library)
                self.assertEqual(dialogue, selection.retain_dialogue)

    def test_dative_long_period_history_selects_complete_context(self):
        for message in (
            "Wie war mein Training in den letzten zwei Monaten?",
            "Wie habe ich in den letzten 10 Tagen geschlafen?",
            "Wie war mein Training in den vergangenen drei Wochen?",
        ):
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertIsNone(selection.horizon_days)

    def test_vergangene_night_is_not_period_history(self):
        selection = select_coach_context(
            "Wie habe ich vergangene Nacht geschlafen?", {}
        )
        self.assertEqual(3, selection.horizon_days)
        self.assertEqual(BASE_SECTIONS, selection.sections)
