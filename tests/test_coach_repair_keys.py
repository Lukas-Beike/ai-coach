import unittest

from backend.coach.service import (
    coach_repair_key,
    dialogue_effect_key,
    dialogue_plan_effect_key,
    dialogue_request_binding_key,
    dialogue_scope_repair_key,
)


class CoachRepairKeyTests(unittest.TestCase):
    def test_scope_repair_matches_corrected_scope_but_not_another_object(self):
        original = {
            "changes": [{"id": "workout-a", "date": "2026-10-01", "expected_payload_hash": "old"}],
            "expected_revision": 3,
            "_request": {
                "target": "plan", "period": "october", "constraints": ["future"],
                "remote_write": False, "sync_scope": "local", "scope": ["workout-a"],
            },
        }
        corrected = {
            "changes": [{"id": "workout-a", "date": "2026-10-01", "expected_payload_hash": "new"}],
            "expected_revision": 4,
            "_request": {
                "target": "plan", "period": "october", "constraints": ["future"],
                "remote_write": False, "sync_scope": "local", "scope": ["workout-b"],
            },
        }
        another_object = {**corrected, "changes": [{"id": "workout-b", "date": "2026-10-01"}]}

        self.assertEqual(
            dialogue_scope_repair_key("update_workout", original),
            dialogue_scope_repair_key("update_workout", corrected),
        )
        self.assertNotEqual(
            dialogue_scope_repair_key("update_workout", corrected),
            dialogue_scope_repair_key("update_workout", another_object),
        )

    def test_request_binding_sorts_scope_and_constraints_and_binds_remote_write(self):
        request = {
            "target": "training_plan", "scope": ["b", "a"], "period": "next_week",
            "constraints": ["rest", "availability"], "remote_write": False,
            "sync_scope": "local",
        }
        reordered = {
            **request, "scope": ["a", "b"], "constraints": ["availability", "rest"],
        }
        remotely_authorized = {**reordered, "remote_write": True}

        self.assertEqual(
            dialogue_request_binding_key({"_request": request}),
            dialogue_request_binding_key({"_request": reordered}),
        )
        self.assertNotEqual(
            dialogue_request_binding_key({"_request": reordered}),
            dialogue_request_binding_key({"_request": remotely_authorized}),
        )

    def test_plan_effect_key_uses_the_exact_workout_signature(self):
        workout = {
            "date": "2026-10-01", "sport": "run", "name": "Easy", "description": "Easy run",
            "duration_minutes": 40, "target": {"pace": "easy"}, "rationale": "Recovery",
            "unrelated_metadata": "ignored",
        }
        patch_key = dialogue_plan_effect_key("apply_training_patch", {"workouts": [workout]})
        replacement_key = dialogue_plan_effect_key(
            "replace_training_plan", {"payload": {"workouts": [{**workout, "unrelated_metadata": "other"}]}}
        )

        self.assertEqual(patch_key, replacement_key)
        self.assertNotEqual(
            patch_key,
            dialogue_plan_effect_key("apply_training_patch", {"workouts": [{**workout, "date": "2026-10-02"}]}),
        )
        self.assertIsNone(dialogue_plan_effect_key("apply_training_patch", {"changes": [{"id": "x"}]}))

    def test_invalid_request_is_rejected_without_losing_value_error(self):
        self.assertIsNone(dialogue_request_binding_key({"_request": {"scope": [1], "constraints": []}}))
        with self.assertRaisesRegex(ValueError, "^request_object$"):
            dialogue_effect_key("update_profile", {"_request": ["invalid"]})

    def test_profile_repair_key_identifies_fields_not_changed_values(self):
        self.assertEqual(
            coach_repair_key("update_profile", {"changes": [{"field": "weight", "value": 70}]}),
            {"profile_fields": ["weight"]},
        )
        self.assertIsNone(coach_repair_key("save_checkin", {"changes": [{"field": "weight"}]}))


if __name__ == "__main__":
    unittest.main()
