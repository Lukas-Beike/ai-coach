"""Focused authorization and dispatch tests for local Coach record tools."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import Mock

from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.checkins import CheckinService
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.errors import AppError
from backend.planning.competition_service import CompetitionService


class CoachAthleteRecordToolServiceTests(unittest.TestCase):
    def setUp(self):
        self.checkins = Mock()
        self.feedback = Mock()
        self.competitions = Mock()
        self.nutrition = Mock()
        self.service = CoachAthleteRecordToolService(
            self.checkins, self.feedback, self.competitions, self.nutrition
        )

    def test_success_routes_all_five_tools_and_preserves_response_shapes(self):
        self.checkins.save_coach.return_value = {"status": "ok"}
        self.feedback.save_coach.return_value = {"status": "ok"}
        self.feedback.save.return_value = {"status": "ok"}
        self.competitions.save.return_value = {"status": "created"}
        self.competitions.delete.return_value = {"status": "deleted"}
        self.nutrition.log_meal.return_value = {"id": "nut-1", "meal_type": "lunch"}
        self.nutrition.delete_meal.return_value = {"status": "deleted", "id": "nut-1"}
        cases = (
            ("save_checkin", {"payload": {"notes": "Synthetic"}}, "local_checkin"),
            ("save_activity_feedback", {"payload": {"activity_id": "a1", "notes": "Synthetic"}}, "activity_feedback"),
            ("delete_activity_feedback", {"activity_id": " a1 "}, "activity_feedback"),
            ("save_competition", {"payload": {"name": "Synthetic"}}, "local_competitions"),
            ("delete_competition", {"competition_id": " a1 "}, "competition:a1"),
            ("save_nutrition_entry", {"payload": {"description": "Oatmeal", "kcal": 450}}, "local_nutrition"),
            ("delete_nutrition_entry", {"id": "nut-1"}, "local_nutrition"),
        )
        expected = {
            "save_checkin": {"ok": True, "status": "ok"},
            "save_activity_feedback": {"ok": True, "stored_locally": True, "status": "ok"},
            "delete_activity_feedback": {"ok": True, "stored_locally": True, "status": "ok"},
            "save_competition": {"ok": True, "status": "created"},
            "delete_competition": {"ok": True, "status": "deleted"},
            "save_nutrition_entry": {"ok": True, "entry": {"id": "nut-1", "meal_type": "lunch"}},
            "delete_nutrition_entry": {"ok": True, "status": "deleted", "id": "nut-1"},
        }
        for name, arguments, scope in cases:
            with self.subTest(name=name):
                result = self.service.execute(
                    name,
                    arguments,
                    {"operation": name, "authorization_scope": [scope]},
                )
                self.assertEqual(result, expected[name])

        self.assertEqual(self.service.execute("other", {}, {}), None)
        self.checkins.save_coach.assert_called_once_with({"notes": "Synthetic"})
        self.feedback.save_coach.assert_called_once_with(
            "a1", {"notes": "Synthetic", "activity_name": None, "activity_date": None}
        )
        self.feedback.save.assert_called_once_with("a1", {"notes": ""})
        self.competitions.save.assert_called_once_with({"name": "Synthetic"})
        self.competitions.delete.assert_called_once_with("a1")
        self.nutrition.log_meal.assert_called_once_with({"description": "Oatmeal", "kcal": 450})
        self.nutrition.delete_meal.assert_called_once_with("nut-1")

    def test_operation_and_scope_denials_block_each_tool(self):
        cases = (
            (
                "save_checkin", {"payload": {}}, "local_checkin",
                "Die strukturierte Coach-Autorisierung erlaubt diesen Check-in nicht.",
            ),
            (
                "save_activity_feedback", {"payload": {}}, "activity_feedback",
                "Die strukturierte Coach-Autorisierung erlaubt dieses Aktivitätsfeedback nicht.",
            ),
            (
                "delete_activity_feedback", {"activity_id": "a1"}, "activity_feedback",
                "Die strukturierte Coach-Autorisierung erlaubt diese Feedbackänderung nicht.",
            ),
            (
                "save_competition", {"payload": {}}, "local_competitions",
                "Die strukturierte Coach-Autorisierung erlaubt diese Aktion in diesem Turn nicht.",
            ),
            (
                "delete_competition", {"competition_id": "a1"}, "competition:a1",
                "Die strukturierte Coach-Autorisierung erlaubt diese Aktion in diesem Turn nicht.",
            ),
            (
                "save_nutrition_entry", {"payload": {}}, "local_nutrition",
                "Die strukturierte Coach-Autorisierung erlaubt diesen Ernährungseintrag nicht.",
            ),
            (
                "delete_nutrition_entry", {"id": "nut-1"}, "local_nutrition",
                "Die strukturierte Coach-Autorisierung erlaubt das Löschen dieses Eintrags nicht.",
            ),
        )
        for name, arguments, scope, operation_message in cases:
            with self.subTest(name=name, denied="operation"), self.assertRaises(AppError) as raised:
                self.service.execute(name, arguments, {"authorization_scope": [scope]})
            self.assertEqual(raised.exception.status, 403)
            self.assertEqual(raised.exception.reason, "intent_scope_denied")
            self.assertEqual(raised.exception.message, operation_message)
            with self.subTest(name=name, denied="scope"), self.assertRaises(AppError) as raised:
                self.service.execute(name, arguments, {"operation": name})
            self.assertEqual(raised.exception.status, 403)
            self.assertEqual(raised.exception.reason, "intent_scope_denied")
            self.assertEqual(
                raised.exception.message,
                "Die strukturierte Coach-Autorisierung umfasst dieses Objekt nicht.",
            )
        self.checkins.save_coach.assert_not_called()
        self.feedback.save_coach.assert_not_called()
        self.feedback.save.assert_not_called()
        self.competitions.save.assert_not_called()
        self.competitions.delete.assert_not_called()

    def test_invalid_payloads_keep_shared_and_domain_validation(self):
        invalid_saves = (
            ("save_checkin", "local_checkin"),
            ("save_activity_feedback", "activity_feedback"),
            ("save_competition", "local_competitions"),
            ("save_nutrition_entry", "local_nutrition"),
        )
        for name, scope in invalid_saves:
            with self.subTest(name=name), self.assertRaises(AppError) as raised:
                self.service.execute(
                    name,
                    {"payload": []},
                    {"operation": name, "authorization_scope": [scope]},
                )
            self.assertEqual((raised.exception.status, raised.exception.reason), (400, "invalid_action"))
            self.assertEqual(raised.exception.message, "Diese Aktion benoetigt payload.")

        manager = Mock()
        feedback = ActivityFeedbackService(manager, Mock(), Mock())
        checkins = CheckinService(manager, Mock(), date.today)
        competitions = CompetitionService(manager, Mock(), lambda: "2026-09-23T00:00:00Z")
        service = CoachAthleteRecordToolService(checkins, feedback, competitions)
        invalid_ids = (
            ("delete_activity_feedback", {"activity_id": ""}, "activity_feedback"),
            ("delete_competition", {"competition_id": ""}, "competition:"),
        )
        for name, arguments, scope in invalid_ids:
            with self.subTest(name=name), self.assertRaises(AppError) as raised:
                service.execute(name, arguments, {"operation": name, "authorization_scope": [scope]})
            self.assertEqual(raised.exception.status, 400)
            self.assertEqual(
                raised.exception.message,
                "Die Aktivität konnte nicht eindeutig zugeordnet werden."
                if name == "delete_activity_feedback"
                else "Eine lokale Wettkampf-ID ist erforderlich.",
            )


if __name__ == "__main__":
    unittest.main()
