"""The report sport filter takes canonical sports and previous provider tokens."""

import unittest

from backend.performance.report_service import report_sport


class ReportSportFilterTests(unittest.TestCase):
    def test_canonical_sports_and_all_pass(self) -> None:
        for value, expected in (("all", "all"), (None, "all"), ("ride", "ride")):
            with self.subTest(value=value):
                self.assertEqual(expected, report_sport(value))

    def test_previous_provider_tokens_resolve_to_the_canonical_sport(self) -> None:
        self.assertEqual("run", report_sport("Run"))
        self.assertEqual("ride", report_sport("VirtualRide"))

    def test_unknown_or_overlong_text_is_rejected(self) -> None:
        self.assertIsNone(report_sport("not-a-sport"))
        self.assertIsNone(report_sport("r" * 41))


if __name__ == "__main__":
    unittest.main()
