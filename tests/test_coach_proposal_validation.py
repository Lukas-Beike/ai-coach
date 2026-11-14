import copy
import unittest

from backend.coach.proposal_validation import validated_coach_action_preview_input
from backend.errors import AppError


class CoachProposalValidationTests(unittest.TestCase):
    def setUp(self):
        self.undo = {
            "action_type": "undo_change",
            "target_system": "local",
            "object_ids": {"history_id": "change-1"},
            "diff": {"fields": {"name": {"changed": True}}},
            "payload": {"history_id": "change-1"},
        }

    def assert_invalid(self, values, expected_message):
        unchanged = copy.deepcopy(values)
        with self.assertRaises(AppError) as raised:
            validated_coach_action_preview_input(values)
        self.assertEqual(type(raised.exception), AppError)
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, expected_message)
        self.assertEqual(values, unchanged)

    def test_a_valid_preview_returns_its_normalized_parts(self):
        self.assertEqual(
            validated_coach_action_preview_input(self.undo),
            (
                "undo_change",
                "local",
                self.undo["object_ids"],
                self.undo["diff"],
                self.undo["payload"],
            ),
        )

    def test_rejects_invalid_top_level_action_and_target_types(self):
        object_error = "Die Aktionsvorschau muss ein Objekt sein."
        self.assert_invalid(None, object_error)
        self.assert_invalid([], object_error)
        self.assert_invalid(
            {**self.undo, "action_type": "unknown"}, "Unbekannter Coach-Aktionstyp."
        )
        self.assert_invalid(
            {**self.undo, "action_type": []}, "Unbekannter Coach-Aktionstyp."
        )
        target_error = "Die Aktionsvorschau benötigt ein gültiges Zielsystem."
        for target in (None, "remote", [], {}):
            with self.subTest(target=target):
                self.assert_invalid(
                    {**self.undo, "target_system": target}, target_error
                )

    def test_rejects_invalid_object_diff_and_payload_types(self):
        shape_error = "Die Aktionsvorschau benötigt Objekt-IDs, Diff und Payload."
        for field, invalid in (
            ("object_ids", None),
            ("object_ids", "activity-1"),
            ("diff", None),
            ("diff", "visible"),
            ("payload", None),
            ("payload", []),
        ):
            with self.subTest(field=field, invalid=invalid):
                self.assert_invalid({**self.undo, field: invalid}, shape_error)

    def test_rejects_empty_diffs_and_wrong_action_targets(self):
        action_error = "Die geschützte Aktion benötigt das passende Ziel und einen sichtbaren Diff."
        for diff in ({}, []):
            with self.subTest(diff=diff):
                self.assert_invalid({**self.undo, "diff": diff}, action_error)
        self.assert_invalid({**self.undo, "target_system": "intervals"}, action_error)
        self.assert_invalid(
            {**self.undo, "target_system": "local+intervals"}, action_error
        )


class LocalNutritionWriteScopeTests(unittest.TestCase):
    @staticmethod
    def preview(tool, scope, values):
        return {
            "action_type": "local_coach_write",
            "target_system": "local",
            "object_ids": {},
            "diff": [{"name": values["name"]}],
            "payload": {
                "tool": tool,
                "arguments": {"payload": values},
                "intent": {
                    "operation": tool,
                    "target_system": "local",
                    "authorization_scope": scope,
                    "request": {"source_message_ids": [7]},
                },
            },
        }

    def accepted(self, tool, scope, values):
        try:
            validated_coach_action_preview_input(self.preview(tool, scope, values))
        except AppError:
            return False
        return True

    def test_a_product_update_needs_only_its_object_token(self):
        product = {"name": "Whey", "basis_unit": "g"}
        edit = {**product, "id": "abc"}
        tool = "save_nutrition_product"
        self.assertTrue(self.accepted(tool, ["nutrition_product:abc"], edit))
        self.assertTrue(
            self.accepted(
                tool, ["local_nutrition_product", "nutrition_product:abc"], edit
            )
        )
        self.assertFalse(self.accepted(tool, ["local_nutrition_product"], edit))
        self.assertFalse(self.accepted(tool, ["nutrition_product:other"], edit))
        self.assertFalse(self.accepted(tool, ["nutrition_product:abc"], product))
        self.assertTrue(self.accepted(tool, ["local_nutrition_product"], product))
        self.assertTrue(self.accepted(tool, ["local_nutrition"], product))

    def test_a_template_update_needs_only_its_object_token(self):
        template = {"name": "Bowl", "description": "Oats"}
        edit = {**template, "id": "t1"}
        tool = "save_nutrition_template"
        self.assertTrue(self.accepted(tool, ["nutrition_template:t1"], edit))
        self.assertFalse(self.accepted(tool, ["local_nutrition"], edit))
        self.assertFalse(self.accepted(tool, ["nutrition_template:t1"], template))
        self.assertTrue(self.accepted(tool, ["local_nutrition"], template))


if __name__ == "__main__":
    unittest.main()
