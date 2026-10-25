import unittest

from backend.coach.tool_schemas import build_structured_tool_schemas

EXECUTOR_CHANGE_FIELDS = {
    "local_id",
    "action",
    "date",
    "start_date_local",
    "name",
    "description",
    "duration_minutes",
    "target",
    "sport",
    "expected_payload_hash",
    "plan_id",
    "rationale",
    "environment",
    "sport_detail",
}


def _tools():
    return {
        tool["name"]: tool
        for tool in build_structured_tool_schemas(
            default_profile={},
            checkin_text_limits={},
            checkin_score_fields=(),
            training_change_limit=366,
            library_bulk_max_entries=100,
            training_plan_statuses=(),
        )
    }


def _nested_objects(node, path=""):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node and path:
            yield path, node
        for key, value in node.items():
            yield from _nested_objects(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _nested_objects(value, f"{path}[{index}]")


class CoachToolSchemaTests(unittest.TestCase):
    def test_activity_detail_description_is_not_limited_to_one_provider(self):
        description = _tools()["get_activity_details"]["description"]
        self.assertNotIn("Intervals.icu", description)
        self.assertIn("any connected provider", description)
        self.assertIn("act_", description)

    def test_nested_object_schemas_reject_unknown_keys(self):
        open_objects = [
            f"{name}.{path}"
            for name, tool in _tools().items()
            for path, node in _nested_objects(tool["parameters"])
            if node.get("additionalProperties") is not False
        ]
        self.assertEqual(open_objects, [])

    def test_training_change_items_are_closed_over_executor_fields(self):
        items = _tools()["apply_training_changes"]["parameters"]["properties"][
            "changes"
        ]["items"]
        self.assertIs(items["additionalProperties"], False)
        self.assertLessEqual(EXECUTOR_CHANGE_FIELDS, set(items["properties"]))

    def test_read_limits_declare_server_clamp_bounds(self):
        tools = _tools()
        expected = {
            ("list_recent_activities", "days"): {"minimum": 1, "maximum": 3660},
            ("list_recent_activities", "limit"): {"minimum": 1, "maximum": 500},
            ("list_planned_workouts", "limit"): {"minimum": 1, "maximum": 366},
            ("list_change_history", "limit"): {"minimum": 1, "maximum": 500},
        }
        for (name, key), bounds in expected.items():
            prop = tools[name]["parameters"]["properties"][key]
            for bound, value in bounds.items():
                with self.subTest(tool=name, key=key, bound=bound):
                    self.assertEqual(prop.get(bound), value)

    def test_save_checkin_clear_fields_enumerates_coach_preserved_fields(self):
        from backend.athlete.checkins import (
            CHECKIN_SCORE_FIELDS,
            CHECKIN_TEXT_LIMITS,
            COACH_PRESERVED_FIELDS,
        )

        tool = {
            tool["name"]: tool
            for tool in build_structured_tool_schemas(
                default_profile={},
                checkin_text_limits=CHECKIN_TEXT_LIMITS,
                checkin_score_fields=CHECKIN_SCORE_FIELDS,
                training_change_limit=366,
                library_bulk_max_entries=100,
                training_plan_statuses=(),
            )
        }["save_checkin"]
        payload = tool["parameters"]["properties"]["payload"]
        clear_fields = payload["properties"]["clear_fields"]
        self.assertEqual(clear_fields["type"], "array")
        self.assertIs(clear_fields["uniqueItems"], True)
        self.assertEqual(clear_fields["items"]["enum"], list(COACH_PRESERVED_FIELDS))
        self.assertNotIn("clear_fields", payload.get("required", []))
        self.assertIn("clear_fields", tool["description"])
        self.assertIn("Omitted and empty fields preserve", tool["description"])

    def test_refresh_days_allow_all_days_or_bounded_window(self):
        days = _tools()["start_provider_refresh"]["parameters"]["properties"]["days"]
        self.assertEqual(
            days["anyOf"],
            [
                {"type": "integer", "enum": [-1]},
                {"type": "integer", "minimum": 1, "maximum": 365},
            ],
        )
        self.assertIn("Set to 30", days["description"])


if __name__ == "__main__":
    unittest.main()
