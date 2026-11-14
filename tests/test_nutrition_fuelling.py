import unittest

from backend.nutrition.fuelling import carbohydrate_per_hour, pre_race_carbohydrates


class FuellingRuleTests(unittest.TestCase):
    """Steps of Thomas, Erdman and Burke (2016); athlete ceiling 120 g/h (#2803)."""

    def test_carbohydrates_per_hour_by_duration(self):
        for minutes, step, rate in [
            (44, "none", (0, 0)),
            (45, "mouth_rinse", (None, None)),
            (75, "mouth_rinse", (None, None)),
            (76, "moderate", (30, 60)),
            (150, "moderate", (30, 60)),
            (151, "high", (60, 120)),
        ]:
            with self.subTest(minutes=minutes):
                result = carbohydrate_per_hour(minutes * 60)
                self.assertEqual(
                    (step, rate), (result["step"], (result["low_g"], result["high_g"]))
                )
        high = carbohydrate_per_hour(4 * 3600)
        self.assertEqual((90, True), (high["established_max_g"], high["glucose_fructose"]))
        for value in (None, 0, -60, True, "3600"):
            with self.subTest(value=value):
                self.assertIsNone(carbohydrate_per_hour(value))

    def test_days_before_and_the_pre_race_meal(self):
        for minutes, expected in [
            (
                100,
                [
                    ("loading", 2, [10, 12], [700, 840]),
                    ("meal", None, [1, 4], [70, 280]),
                ],
            ),
            (
                80,
                [
                    ("daily", 1, [7, 12], [490, 840]),
                    ("meal", None, [1, 4], [70, 280]),
                ],
            ),
            (50, [("daily", 1, [7, 12], [490, 840])]),
        ]:
            with self.subTest(minutes=minutes):
                result = pre_race_carbohydrates(minutes * 60, 70)
                self.assertEqual(
                    expected,
                    [
                        (e["kind"], e.get("days_before"), e["g_per_kg"], e["grams"])
                        for e in result
                    ],
                )
        unweighed = pre_race_carbohydrates(100 * 60, None)
        self.assertEqual([None, None], [entry["grams"] for entry in unweighed])
        self.assertEqual([4, 1], unweighed[1]["hours_before"])
        self.assertEqual([], pre_race_carbohydrates(None, 70))


if __name__ == "__main__":
    unittest.main()
