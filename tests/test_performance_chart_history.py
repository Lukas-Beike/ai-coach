import math
import unittest
from datetime import date

from backend.performance.chart_history import analysis_history


class AnalysisHistoryTests(unittest.TestCase):
    def test_garmin_acute_load_is_dated_and_never_derived_from_daily_or_chronic_load(
        self,
    ):
        garmin = {
            "training_status": [
                {
                    "calendarDate": "2026-10-01",
                    "mostRecentTrainingStatus": {
                        "latestTrainingStatusData": {
                            "device": {
                                "acuteTrainingLoadDTO": {
                                    "acuteTrainingLoad": 475,
                                    "dailyTrainingLoad": 90,
                                }
                            }
                        }
                    },
                },
                {
                    "calendarDate": "2026-10-02",
                    "dailyTrainingLoad": 100,
                    "chronicTrainingLoad": 400,
                },
                {"calendarDate": "2026-10-03", "acuteTrainingLoad": 800},
            ]
        }
        result = analysis_history(None, garmin, date(2026, 10, 2))
        self.assertEqual(result["load"]["source"], "Garmin Connect")
        self.assertEqual(
            result["load"]["points"][-2], {"date": "2026-10-01", "value": 475}
        )
        self.assertIsNone(result["load"]["points"][-1]["value"])

    def test_acute_load_rejects_invalid_and_conflicting_device_values(self):
        from backend.performance.garmin_load import acute_load_value

        for value in (True, math.nan, math.inf, -1, 100_001, "bad"):
            self.assertIsNone(acute_load_value({"acuteTrainingLoad": value}))
        self.assertIsNone(
            acute_load_value(
                {"devices": [{"acuteTrainingLoad": 200}, {"acuteTrainingLoad": 300}]}
            )
        )

    def test_load_is_bounded_retrospective_and_missing_days_remain_missing(self):
        snapshot = {
            "recent_wellness": [
                {"id": "2026-10-01", "ctl": 42, "atl": 50, "tsb": 999},
                {"id": "2020-01-01", "ctl": 100},
                {"id": "bad", "ctl": 100},
            ]
        }
        result = analysis_history(snapshot, {}, date(2026, 10, 2))
        points = result["load"]["points"]
        self.assertEqual(len(points), 90)
        self.assertEqual(points[-1], {"date": "2026-10-02", "value": None})
        self.assertEqual(result["load"]["start"], "2026-07-05")
        self.assertEqual(result["load"]["end"], "2026-10-02")
        self.assertIsNone(points[-2]["value"])
        self.assertEqual(result["start"], "2026-07-05")

    def test_raw_history_retains_older_dates_and_compact_rows_take_precedence(self):
        snapshot = {
            "raw_provider_data": {
                "wellness": [
                    {
                        "id": "2026-07-10",
                        "ctl": 30,
                        "atl": 20,
                        "notes": "untrusted content",
                    },
                    {"id": "2026-10-01", "ctl": 10, "atl": 20},
                ],
                "garmin": [
                    {"calendarDate": "2026-07-10", "acuteTrainingLoad": 30},
                    {"calendarDate": "2026-10-01", "acuteTrainingLoad": 40},
                ],
            },
            "recent_wellness": [{"id": "2026-10-01", "ctl": 40, "atl": 50}],
        }
        result = analysis_history(
            snapshot,
            {"training_status": snapshot["raw_provider_data"]["garmin"]},
            date(2026, 10, 2),
        )
        self.assertEqual(result["load"]["points"][5]["value"], 30)
        self.assertEqual(result["load"]["points"][-2]["value"], 40)
        self.assertNotIn("untrusted content", str(result))

    def test_sources_remain_separate_with_no_backdating_of_current_settings(self):
        snapshot = {
            "athlete": {"icu_ftp": 999},
            "recent_wellness": [
                {
                    "id": "2026-10-01",
                    "sport_info": [
                        {"types": ["Ride"], "ftp": 250, "eftp": 255, "vo2max": 52},
                        {"types": ["Run"], "threshold_pace": 4, "vo2max": 54},
                    ],
                }
            ],
        }
        garmin = {
            "performance_history": [
                {"date": "2026-10-01", "metrics": {"cycling_ftp_watts": 260}},
                {"date": "2026-10-03", "metrics": {"cycling_ftp_watts": 400}},
            ]
        }
        series = analysis_history(snapshot, garmin, date(2026, 10, 2))["metrics"]
        ftp = series["cycling_ftp_watts"]
        self.assertEqual([item["source"] for item in ftp], ["Garmin Connect"])
        self.assertEqual([item["points"][-2]["value"] for item in ftp], [260])
        self.assertTrue(all(item["points"][-1]["value"] is None for item in ftp))
        self.assertEqual(
            series["run_threshold_pace_seconds_per_km"][0]["points"][-2]["value"], None
        )

    def test_eftp_uses_only_intervals_estimates_and_never_plain_ftp(self):
        snapshot = {
            "recent_wellness": [
                {"id": "2026-09-30", "sport_info": [{"types": ["Ride"], "ftp": 900}]},
                {
                    "id": "2026-10-01",
                    "sport_info": [{"types": ["Ride"], "mmp_model": {"ftp": 270}}],
                },
            ],
            "recent_activities": [
                {
                    "start_date_local": "2026-10-01T10:00:00",
                    "type": "Ride",
                    "icu_eftp": 250,
                },
                {
                    "start_date_local": "2026-10-02T10:00:00",
                    "type": "Ride",
                    "icu_eftp": 260,
                },
                {
                    "start_date_local": "2026-10-02T12:00:00",
                    "type": "VirtualRide",
                    "icu_eftp": 265,
                },
                {
                    "start_date_local": "2026-10-02T13:00:00",
                    "type": "Run",
                    "icu_eftp": 999,
                },
            ],
        }
        garmin = {
            "performance_history": [
                {"date": "2026-10-01", "metrics": {"cycling_eftp_watts": 999}}
            ]
        }
        result = analysis_history(snapshot, garmin, date(2026, 10, 2))["metrics"]
        points = result["cycling_eftp_watts"][0]["points"]
        self.assertEqual(result["cycling_eftp_watts"][0]["source"], "Intervals.icu")
        self.assertIsNone(points[-3]["value"])
        self.assertEqual(points[-2]["value"], 270)
        self.assertEqual(points[-1]["value"], 265)
        self.assertTrue(
            all(p["value"] is None for p in result["cycling_ftp_watts"][0]["points"])
        )

    def test_invalid_values_are_missing_and_empty_history_is_safe(self):
        snapshot = {
            "recent_wellness": [
                {"id": "2026-10-01", "ctl": math.nan, "atl": -1},
                None,
            ]
        }
        garmin = {
            "performance_history": [
                {"date": "2026-10-01", "metrics": {"cycling_ftp_watts": math.inf}},
                {"date": "2026-10-01", "metrics": None},
            ]
        }
        result = analysis_history(snapshot, garmin, date(2026, 10, 2))
        self.assertIsNone(result["load"]["points"][-2]["value"])
        self.assertIsNone(
            result["metrics"]["cycling_ftp_watts"][0]["points"][-2]["value"]
        )
        self.assertEqual(
            len(analysis_history(None, {}, date(2026, 10, 2))["load"]["points"]), 90
        )


if __name__ == "__main__":
    unittest.main()
