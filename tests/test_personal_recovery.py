import unittest
from datetime import date, timedelta

from backend.athlete.profile import normalize_profile
from backend.errors import AppError
from backend.performance.personal_recovery import personal_recovery


class PersonalRecoveryTests(unittest.TestCase):
    today = date(2026, 10, 2)

    def rows(self, nights):
        return [
            {
                "id": (self.today - timedelta(days=i)).isoformat(),
                "sleepSecs": 7 * 3600,
                "restingHR": 50,
                "hrv": 40,
            }
            for i in range(nights + 1)
        ]

    def test_coverage_and_excluding_current_value_from_baseline(self):
        for nights, status in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (28, "ok"),
        ):
            rows = self.rows(nights)
            rows[0]["restingHR"] = 100
            result = personal_recovery(rows, {}, {}, self.today)
            pulse = next(
                row for row in result["baselines"] if row["metric"] == "resting_hr"
            )
            self.assertEqual(status, pulse["status"])
            if nights >= 14:
                self.assertEqual(50, pulse["median"])
                self.assertEqual("above", pulse["position"])
            self.assertFalse(any(row["metric"] == "hrv" for row in result["baselines"]))

    def test_future_stale_and_incompatible_methods_are_not_classified(self):
        rows = self.rows(30)
        for row in rows:
            row["hrv_method"] = "RMSSD" if row["id"] < "2026-09-20" else "SDNN"
        rows.append({"id": "2026-10-03", "restingHR": 200, "sleepSecs": 100})
        result = personal_recovery(rows, {}, {}, self.today)
        self.assertEqual(
            2, len([row for row in result["baselines"] if row["metric"] == "hrv"])
        )
        self.assertFalse(
            any(
                point["date"] > "2026-10-02"
                for row in result["baselines"]
                for point in row["history"]
            )
        )
        stale = personal_recovery(self.rows(30)[3:], {}, {}, self.today)
        self.assertTrue(
            all(row["status"] == "insufficient_data" for row in stale["baselines"])
        )

    def test_deficit_uses_known_nights_and_never_offsets_with_long_sleep(self):
        rows = self.rows(5)
        rows[0]["sleepSecs"] = 10 * 3600
        result = personal_recovery(rows, {}, {"sleep_target_hours": "8"}, self.today)
        deficit = result["sleep_deficits"][0]
        self.assertEqual(
            (5, 6, "partial"),
            (deficit["deficit_hours"], deficit["known_nights"], deficit["status"]),
        )
        self.assertEqual(
            [], personal_recovery(rows, {}, {}, self.today)["sleep_deficits"]
        )

    def test_profile_target_requires_valid_explicit_value(self):
        self.assertEqual(
            "8", normalize_profile({"sleep_target_hours": 8})["sleep_target_hours"]
        )
        for value in (3, 13, "nan", "no"):
            with self.subTest(value=value), self.assertRaises(AppError):
                normalize_profile({"sleep_target_hours": value})

    def test_eight_calendar_weeks_keep_a_42_day_comparison_range(self):
        rows = self.rows(60)
        for row in rows:
            if row["id"] < "2026-08-21":
                row["restingHR"] = 100
        result = personal_recovery(rows, {}, {}, self.today)
        pulse = next(row for row in result["baselines"] if row["metric"] == "resting_hr")
        self.assertEqual("2026-08-03", pulse["history"][0]["date"])
        self.assertEqual(61, len(pulse["history"]))
        self.assertEqual(42, pulse["nights"])
        self.assertEqual(50, pulse["median"])


if __name__ == "__main__":
    unittest.main()
