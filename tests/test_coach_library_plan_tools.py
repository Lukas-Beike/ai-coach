from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.library_plan_tools import (
    CoachLibraryPlanToolService,
    require_complete_template,
)
from backend.errors import AppError


class CoachLibraryPlanToolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library_plan_service = Mock()
        self.service = CoachLibraryPlanToolService(self.library_plan_service)

    def test_authorized_entry_is_delegated_and_wrapped_as_local_result(self) -> None:
        entry = {"library_workout_id": "workout-1", "date": "2026-09-24"}
        self.library_plan_service.apply.return_value = {
            "status": "local",
            "planned": [entry],
        }

        result = self.service.execute(
            {"entries": [entry]},
            {
                "operation": "apply_workout_library_plan",
                "authorization_scope": ["library_workout:workout-1"],
            },
        )

        self.library_plan_service.apply.assert_called_once_with(
            [entry], check_template=require_complete_template
        )
        self.assertEqual(
            result,
            {"ok": True, "stored_locally": True, "status": "local", "planned": [entry]},
        )

    def test_unauthorized_operation_does_not_call_domain_service(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute({"entries": []}, {"operation": "other"})

        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.reason, "intent_scope_denied")
        self.library_plan_service.apply.assert_not_called()

    def test_non_list_entries_do_not_call_domain_service(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                {"entries": "workout-1"},
                {"operation": "apply_workout_library_plan"},
            )

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            raised.exception.message,
            "Bibliothekseinheiten müssen als Liste gesendet werden.",
        )
        self.assertEqual(raised.exception.reason, "invalid_library_plan")
        self.library_plan_service.apply.assert_not_called()

    def test_non_object_entry_does_not_call_domain_service(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                {"entries": ["workout-1"]},
                {"operation": "apply_workout_library_plan"},
            )

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            raised.exception.message, "Jede Bibliothekseinheit muss ein Objekt sein."
        )
        self.assertEqual(raised.exception.reason, "invalid_library_plan")
        self.library_plan_service.apply.assert_not_called()

    def test_missing_entry_scope_does_not_call_domain_service(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                {"entries": [{"library_workout_id": "workout-1"}]},
                {"operation": "apply_workout_library_plan", "authorization_scope": []},
            )

        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.reason, "intent_scope_denied")
        self.library_plan_service.apply.assert_not_called()


class RequireCompleteTemplateTests(unittest.TestCase):
    def test_legacy_templates_name_the_template_and_the_repair_tool(self) -> None:
        cases = {
            "strength": (
                {"name": "Kraft alt", "sport": "strength", "description": "Squats"},
                "strength_structure",
            ),
            "run without cap": (
                {"name": "Lauf alt", "sport": "run", "session_focus": "easy"},
                "hr_cap",
            ),
            "run without focus": (
                {"name": "Lauf ohne Typ", "sport": "run"},
                "session_focus",
            ),
        }
        for label, (template, field) in cases.items():
            with self.subTest(label), self.assertRaises(AppError) as raised:
                require_complete_template("tpl-1", template)
            message = str(raised.exception)
            self.assertIn(template["name"], message)
            self.assertIn("tpl-1", message)
            self.assertIn(field, message)
            self.assertIn("manage_training_templates", message)

    def test_complete_and_unfocused_sport_templates_pass(self) -> None:
        require_complete_template("s", {"name": "Schwimmen", "sport": "swim"})
        require_complete_template(
            "r",
            {
                "name": "Intervalle",
                "sport": "run",
                "session_focus": "vo2max",
            },
        )


if __name__ == "__main__":
    unittest.main()
