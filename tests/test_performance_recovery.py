import unittest

from backend.performance.recovery import rounded_average


class RecoveryAverageTests(unittest.TestCase):
    def test_rounded_average_uses_two_decimals_and_none_for_no_values(self):
        self.assertEqual(rounded_average([7.0, 7.1, 7.15]), 7.08)
        self.assertIsNone(rounded_average([]))


if __name__ == "__main__":
    unittest.main()
