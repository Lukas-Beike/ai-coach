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


if __name__ == "__main__":
    unittest.main()
