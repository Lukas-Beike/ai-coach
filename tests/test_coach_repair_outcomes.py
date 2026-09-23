import unittest

from backend.coach.outcomes import unresolved_coach_steps


class UnresolvedCoachStepsTests(unittest.TestCase):
    def test_same_tool_success_only_repairs_same_target_scope_and_period(self):
        failed = {
            "tool": "apply_training_patch", "step_key": "first",
            "request": {"target": "local_plan", "scope": ["workout:one"], "period": {"start": "2026-09-20"}},
            "result": {"ok": False, "reason": "tool_arguments_invalid"},
        }
        for changed in (
            {"target": "other", "scope": ["workout:one"], "period": {"start": "2026-09-20"}},
            {"target": "local_plan", "scope": ["workout:two"], "period": {"start": "2026-09-20"}},
            {"target": "local_plan", "scope": ["workout:one"], "period": {"start": "2026-09-21"}},
        ):
            with self.subTest(changed=changed):
                success = {"tool": failed["tool"], "step_key": "second", "request": changed, "result": {"ok": True}}
                self.assertEqual(unresolved_coach_steps([failed, success]), [failed])

        equivalent = {
            "tool": failed["tool"], "step_key": "second",
            "request": {"target": "local_plan", "scope": ["workout:one"], "period": {"start": "2026-09-20"}},
            "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([failed, equivalent]), [])

        legacy_json_scope = {
            "tool": failed["tool"], "step_key": "numeric-scope",
            "request": {"target": "local_plan", "scope": [7], "period": None},
            "result": {"ok": True},
        }
        same_legacy_scope = {
            "tool": failed["tool"], "step_key": "numeric-scope-retry",
            "request": {"target": "local_plan", "scope": [7], "period": None},
            "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([legacy_json_scope, same_legacy_scope]), [])

    def test_profile_conflict_requires_exact_profile_fields(self):
        failed = {
            "tool": "update_profile", "step_key": "profile-a",
            "request": {"target": "profile", "scope": ["profile"], "period": None},
            "repair_key": {"profile_fields": ["ftp", "weight"]},
            "result": {"ok": False, "reason": "profile_conflict"},
        }
        different = {
            "tool": "update_profile", "step_key": "profile-b",
            "request": {"target": "profile", "scope": ["profile"], "period": None},
            "repair_key": {"profile_fields": ["ftp"]}, "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([failed, different]), [failed])
        same = {
            "tool": "update_profile", "step_key": "profile-b",
            "request": {"target": "profile", "scope": ["profile"], "period": None},
            "repair_key": {"profile_fields": ["ftp", "weight"]}, "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([failed, same]), [])

        legacy_fields = {**failed, "repair_key": {"profile_fields": "ftp,weight"}}
        same_legacy_fields = {
            **same, "repair_key": {"profile_fields": "ftp,weight"},
        }
        self.assertEqual(unresolved_coach_steps([legacy_fields, same_legacy_fields]), [])

    def test_all_pending_plan_sync_can_repair_selected_sync(self):
        failed = {
            "tool": "start_intervals_plan_sync", "step_key": "sync-selected",
            "request": {"target": "intervals", "scope": ["planned_unit:one"], "sync_scope": "selected"},
            "result": {"ok": False, "reason": "tool_arguments_invalid"},
        }
        success = {
            "tool": "start_intervals_plan_sync", "step_key": "sync-all",
            "request": {"target": "intervals", "scope": ["local_plan", "intervals_sync"], "sync_scope": "all_pending"},
            "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([failed, success]), [])

    def test_alternative_plan_tools_require_same_binding_and_plan_effect(self):
        failed = {
            "tool": "apply_training_patch", "step_key": "patch",
            "request_binding_key": "binding-a", "plan_effect_key": "effect-a",
            "result": {"ok": False, "reason": "request_invalid"},
        }
        for change in ({"request_binding_key": "binding-b"}, {"plan_effect_key": "effect-b"}):
            success = {
                "tool": "replace_training_plan", "step_key": "replacement",
                "request_binding_key": "binding-a", "plan_effect_key": "effect-a", "result": {"ok": True},
                **change,
            }
            self.assertEqual(unresolved_coach_steps([failed, success]), [failed])
        success = {
            "tool": "replace_training_plan", "step_key": "replacement",
            "request_binding_key": "binding-a", "plan_effect_key": "effect-a", "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([failed, success]), [])

    def test_step_key_tracking_and_result_order_are_preserved(self):
        first = {"tool": "apply_training_patch", "step_key": "first", "result": {"ok": False}}
        second = {"tool": "update_profile", "step_key": "second", "result": {"ok": False}}
        replacement = {"tool": "apply_training_patch", "step_key": "first", "result": {"ok": False, "reason": "new"}}
        self.assertEqual(unresolved_coach_steps([first, second, replacement]), [replacement, second])

    def test_malformed_receipts_cannot_clear_failures_or_crash_projection(self):
        failed = {
            "tool": "apply_training_patch", "step_key": "first",
            "request": {"target": "local_plan", "scope": ["workout:one"], "period": None},
            "result": {"ok": False, "reason": "request_invalid"},
        }
        malformed_success = {
            "tool": "apply_training_patch", "step_key": {"not": "hashable"},
            "request": {"target": "local_plan", "scope": [["invalid"]], "period": None},
            "result": {"ok": True},
        }
        self.assertEqual(unresolved_coach_steps([failed, None, {"tool": []}, malformed_success]), [failed])

    def test_legacy_missing_request_exception_is_preserved(self):
        failed = {"tool": "apply_training_patch", "step_key": "first", "result": {"ok": False, "reason": "request_invalid"}}
        success = {"tool": "apply_training_patch", "step_key": "second", "result": {"ok": True}}
        self.assertEqual(unresolved_coach_steps([failed, success]), [])

    def test_json_truthy_success_value_one_is_preserved(self):
        failed = {
            "tool": "apply_training_patch", "step_key": "first",
            "request": {"target": "local_plan", "scope": ["workout:one"], "period": None},
            "result": {"ok": False, "reason": "tool_arguments_invalid"},
        }
        success = {
            "tool": "apply_training_patch", "step_key": "second",
            "request": {"target": "local_plan", "scope": ["workout:one"], "period": None},
            "result": {"ok": 1},
        }
        self.assertEqual(unresolved_coach_steps([failed, success]), [])


if __name__ == "__main__":
    unittest.main()
