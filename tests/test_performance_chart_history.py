import math
import unittest
from datetime import date

from backend.performance.chart_history import analysis_history


class AnalysisHistoryTests(unittest.TestCase):
    def test_load_is_bounded_retrospective_and_missing_days_remain_missing(self):
        snapshot = {
            "recent_wellness": [
                {"id": "2026-10-01", "ctl": 42, "atl": 50, "tsb": 999},
                {"id": "2026-10-02", "ctl": 100, "atl": 200},
                {"id": "2026-10-03", "ctl": 200, "atl": 300},
                {"id": "2020-01-01", "ctl": 100},
                {"id": "bad", "ctl": 100},
            ]
        }
        result = analysis_history(snapshot, {}, date(2026, 10, 2))
        points = result["load"]["points"]
        self.assertEqual(len(points), 90)
        self.assertEqual(
            points[-2], {"date": "2026-10-01", "ctl": 42, "atl": 50, "tsb": -8}
        )
        self.assertIsNone(points[-1]["ctl"])
        self.assertIsNone(points[-3]["atl"])
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
                ]
            },
            "recent_wellness": [{"id": "2026-10-01", "ctl": 40, "atl": 50}],
        }
        result = analysis_history(snapshot, {}, date(2026, 10, 2))
        self.assertEqual(result["load"]["points"][5]["ctl"], 30)
        self.assertEqual(result["load"]["points"][-2]["ctl"], 40)
        self.assertNotIn("untrusted content", str(result))

    def test_sources_remain_separate_with_no_backdating_of_current_settings(self):
        snapshot = {
            "athlete": {"icu_ftp": 999},
            "recent_wellness": [
                {
                    "id": "2026-10-01",
                    "sport_info": [
                        {"types": ["Ride"], "ftp": 250, "vo2max": 52},
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
        self.assertEqual(
            [item["source"] for item in ftp], ["Intervals.icu", "Garmin Connect"]
        )
        self.assertEqual([item["points"][-2]["value"] for item in ftp], [250, 260])
        self.assertTrue(all(item["points"][-1]["value"] is None for item in ftp))
        self.assertEqual(
            series["run_threshold_pace_seconds_per_km"][0]["points"][-2]["value"], 250
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
        self.assertIsNone(result["load"]["points"][-2]["tsb"])
        self.assertIsNone(
            result["metrics"]["cycling_ftp_watts"][1]["points"][-2]["value"]
        )
        self.assertEqual(
            len(analysis_history(None, {}, date(2026, 10, 2))["load"]["points"]), 90
        )


if __name__ == "__main__":
    unittest.main()
