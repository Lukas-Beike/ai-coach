import unittest

from backend.performance.planning_recovery import planning_recovery_by_date


class PlanningRecoveryTests(unittest.TestCase):
    def test_intervals_values_keep_sources_and_garmin_priority(self):
        wellness_rows = [
            {
                "id": "2026-09-07",
                "sleepSecs": 25_200,
                "sleepScore": 70,
                "hrv": 42,
                "restingHR": 55,
                "readiness": {"score": 80},
                "ctl": 90,
                "atl": 60,
                "tsb": 30,
            }
        ]
        garmin = {
            "sleep": [
                {
                    "calendarDate": "2026-09-07",
                    "sleepTimeSeconds": 28_800,
                    "sleepScore": 90,
                }
            ],
            "hrv": [{"calendarDate": "2026-09-07", "hrvLastNight": 60}],
            "resting_hr": [{"calendarDate": "2026-09-07", "restingHeartRate": 50}],
            "readiness": [{"calendarDate": "2026-09-07", "score": 65}],
        }

        result = planning_recovery_by_date(wellness_rows, garmin, {}, None)

        self.assertEqual(
            result["2026-09-07"],
            {
                "sleep_hours": 8.0,
                "sleep_score": 90,
                "hrv": 60,
                "readiness": 80,
                "resting_hr": 50,
                "ctl": 90,
                "atl": 60,
                "tsb": 30,
                "sources": {
                    "sleep_hours": "Garmin Connect",
                    "sleep_score": "Garmin Connect",
                    "hrv": "Garmin Connect",
                    "readiness": "Intervals.icu Wellness",
                    "resting_hr": "Garmin Connect",
                    "ctl": "Intervals.icu Wellness",
                    "atl": "Intervals.icu Wellness",
                    "tsb": "Intervals.icu Wellness",
                },
            },
        )

    def test_missing_invalid_dates_and_values_are_ignored(self):
        result = planning_recovery_by_date(
            [
                None,
                {"id": "not-a-date", "sleepSecs": 3_600},
                {"id": "2026-09-07", "sleepSecs": "not-a-number", "hrv": ""},
            ],
            {"sleep": [{"calendarDate": "bad", "sleepTimeSeconds": 3_600}]},
            {"not-a-date": 80, "2026-09-07": "not-a-number"},
            {"status": "ready", "sleep_date": "bad", "morning": {"value": 70}},
        )

        self.assertEqual(result, {"2026-09-07": {}})

    def test_saved_and_current_morning_body_battery(self):
        result = planning_recovery_by_date(
            [],
            {},
            {"2026-09-05": 74, "2026-09-06T00:00:00Z": "75", "bad": 99},
            {
                "status": "ready",
                "sleep_date": "2026-09-06",
                "morning": {"value": 78},
            },
        )

        self.assertEqual(result["2026-09-05"]["body_battery"], 74)
        self.assertEqual(result["2026-09-06"]["body_battery"], 78)
        self.assertEqual(
            result["2026-09-06"]["sources"]["body_battery"], "Garmin Connect"
        )


if __name__ == "__main__":
    unittest.main()
