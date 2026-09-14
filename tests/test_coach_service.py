import unittest

from backend.coach.service import effects_from_receipts, mark_resolved_receipts, outcome_status


class CoachServiceTests(unittest.TestCase):
    def test_effects_exclude_internal_tools_and_resolution_preserves_identity(self):
        failed = {"tool": "save_checkin", "result": {"ok": False}}
        resolved = {"tool": "save_checkin", "result": {"ok": False}}
        effects = [{"tool": "save_checkin", "result": {"ok": True}}, {"tool": "read_profile", "result": {"ok": True}}]
        mark_resolved_receipts([failed, resolved], [failed])
        self.assertFalse(failed["resolved"])
        self.assertTrue(resolved["resolved"])
        self.assertEqual(effects_from_receipts(effects, {"read_profile"}), [effects[0]])

    def test_outcome_status_distinguishes_partial_failure_and_cancellation(self):
        self.assertEqual(outcome_status(question="How?", incomplete_answer=False, failures=[], missing_answer=False, effects=[], cancelled=False), "completed")
        self.assertEqual(outcome_status(question="", incomplete_answer=False, failures=[{"tool": "save"}], missing_answer=False, effects=[{"tool": "other"}], cancelled=False), "partial")
        self.assertEqual(outcome_status(question="", incomplete_answer=False, failures=[], missing_answer=False, effects=[], cancelled=True), "cancelled")


if __name__ == "__main__":
    unittest.main()
