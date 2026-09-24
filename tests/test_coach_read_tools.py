import unittest
from unittest.mock import Mock

from backend.coach.read_tools import CoachReadToolService
from backend.errors import AppError


class CoachReadToolServiceTests(unittest.TestCase):
    def setUp(self):
        self.profile = Mock()
        self.profile.get.return_value = {"name": "Athlete"}
        self.training_state = Mock()
        self.training_state.read.return_value = {
            "planned_units": [], "planned_units_page": {"has_more": False}
        }
        self.activity_tools = Mock()
        self.activity_tools.execute.side_effect = lambda name, _arguments: {
            "ok": True, "tool": name
        }
        self.library = Mock()
        self.library.list.return_value = [{"id": "workout-1"}]
        self.planned_units = Mock()
        self.planned_units.list_for_coach.return_value = {"local": []}
        self.history = Mock()
        self.history.list.return_value = [{"id": "change-1"}]
        self.competitions = Mock()
        self.competitions.list.return_value = [{"id": "race-1"}]
        self.training_plans = Mock()
        self.training_plans.list.return_value = [{"id": "plan-1"}]
        self.factories = [
            Mock(return_value=service)
            for service in (
                self.profile,
                self.training_state,
                self.activity_tools,
                self.library,
                self.planned_units,
                self.history,
                self.competitions,
                self.training_plans,
            )
        ]
        self.service = CoachReadToolService(*self.factories, training_change_limit=366)

    def test_dispatches_every_read_tool_and_projects_existing_shapes(self):
        self.assertEqual(
            self.service.execute("read_profile", {}),
            {"ok": True, "profile": {"name": "Athlete"}},
        )
        self.assertEqual(
            self.service.execute(
                "read_training_state",
                {"include_inactive": 1, "cursor": "next", "limit": 12},
            ),
            {"ok": True, "planned_units": [], "planned_units_page": {"has_more": False}},
        )
        self.training_state.read.assert_called_once_with(
            include_inactive=True, cursor="next", limit=12
        )
        for name in ("list_recent_activities", "get_activity_details"):
            self.assertEqual(self.service.execute(name, {"activity_id": "activity-1"}), {
                "ok": True, "tool": name
            })
        self.activity_tools.execute.assert_any_call(
            "list_recent_activities", {"activity_id": "activity-1"}
        )
        self.activity_tools.execute.assert_any_call(
            "get_activity_details", {"activity_id": "activity-1"}
        )
        self.assertEqual(
            self.service.execute("list_workout_library", {"include_archived": True}),
            {"ok": True, "templates": [{"id": "workout-1"}]},
        )
        self.library.list.assert_called_once_with(100, include_archived=True)
        self.assertEqual(
            self.service.execute("list_planned_workouts", {}),
            {"ok": True, "local": []},
        )
        self.planned_units.list_for_coach.assert_called_once_with(100)
        self.assertEqual(
            self.service.execute("list_change_history", {}),
            {"ok": True, "changes": [{"id": "change-1"}]},
        )
        self.assertEqual(
            self.service.execute("list_competitions", {}),
            {"ok": True, "competitions": [{"id": "race-1"}]},
        )
        self.assertEqual(
            self.service.execute("list_training_plans", {}),
            {"ok": True, "training_plans": [{"id": "plan-1"}]},
        )

    def test_limit_bounds_saturate_and_optional_filters_are_forwarded(self):
        self.service.execute("list_workout_library", {"limit": 900, "include_archived": False})
        self.library.list.assert_called_once_with(500, include_archived=False)
        self.service.execute("list_planned_workouts", {"limit": 900})
        self.planned_units.list_for_coach.assert_called_once_with(366)
        self.service.execute("list_change_history", {"limit": 0})
        self.history.list.assert_called_once_with(1)

    def test_invalid_limits_keep_bad_request_reason(self):
        for tool_name in (
            "list_workout_library", "list_planned_workouts", "list_change_history"
        ):
            with self.subTest(tool=tool_name), self.assertRaises(AppError) as caught:
                self.service.execute(tool_name, {"limit": "not-an-integer"})
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(caught.exception.reason, "invalid_list_request")

    def test_unknown_name_returns_none_without_constructing_services(self):
        self.assertIsNone(self.service.execute("unknown_read_tool", {}))
        for factory in self.factories:
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
