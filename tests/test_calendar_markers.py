import unittest

from backend.calendar.markers import has_marker


class MarkerTests(unittest.TestCase):
    def test_variants_match(self):
        for text in (
            "[NO_TRAINING]",
            "[no training]",
            "[NO-TRAINING]",
            "[ NO_TRAINING ]",
            "(no_training)",
            "x [No_Training] y",
        ):
            self.assertTrue(has_marker(text, "[NO_TRAINING]"), text)

    def test_bare_or_other_marker_does_not_match(self):
        for text in ("NO_TRAINING", "", None, "[NO_INTENSITY]"):
            self.assertFalse(has_marker(text, "[NO_TRAINING]"), text)


if __name__ == "__main__":
    unittest.main()
