import copy
import unittest
from datetime import date, timedelta

from backend.performance.context import current_performance_context


class PerformanceContextTests(unittest.TestCase):
    def test_none_and_empty_snapshots_are_unavailable(self):
        expected = {
            "available": False,
            "source": "Intervals.icu",
            "as_of": None,
            "metrics": {},
        }
        self.assertEqual(
            current_performance_context(None, {}, {}, date(2026, 9, 20)), expected
        )
        self.assertEqual(
            current_performance_context({}, {}, {}, date(2026, 9, 20)), expected
        )

    def test_composes_intervals_garmin_load_health_and_validation(self):
        today = date(2026, 9, 20)
        snapshot = {
            "synced_at": "2026-09-20T08:00:00Z",
            "athlete": {
                "icu_ftp": 300,
                "lthr": 171,
                "max_hr": 190,
                "icu_w_prime": 20,
            },
            "recent_wellness": [
                {
                    "id": today.isoformat(),
                    "ctl": 70,
                    "atl": 76,
                    "tsb": -6,
                    "sleepSecs": 27000,
                    "readiness": 8,
                }
            ],
            "recent_activities": [
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": f"{today.isoformat()}T07:00:00",
                    "moving_time": 3600,
                    "icu_training_load": 110,
                    "average_watts": 200,
                    "average_heartrate": 150,
                }
            ],
        }
        garmin = {
            "sleep": [
                {
                    "calendarDate": today.isoformat(),
                    "sleepTimeSeconds": 28800,
                    "sleepScore": 90,
                }
            ],
            "daily_stats": [
                {
                    "calendarDate": (today - timedelta(days=1)).isoformat(),
                    "totalSteps": 1000,
                    "floorsAscended": 5,
                    "totalKilocalories": 2000,
                },
                {
                    "calendarDate": today.isoformat(),
                    "totalSteps": 9999,
                    "floorsAscended": 99,
                    "totalKilocalories": 9999,
                },
            ],
            "source_freshness": {
                "sleep": {
                    "freshness": "fresh",
                    "observed_at": today.isoformat(),
                },
                "daily_stats": {
                    "freshness": "fresh",
                    "observed_at": (today - timedelta(days=1)).isoformat(),
                },
            },
        }

        result = current_performance_context(snapshot, garmin, {}, today)

        self.assertTrue(result["available"])
        self.assertEqual(
            result["source"], "Letzter gespeicherter Intervals.icu-Snapshot"
        )
        self.assertEqual(result["as_of"], snapshot["synced_at"])
        self.assertEqual(result["thresholds"]["icu_ftp"], 300)
        self.assertEqual(result["current_load"]["tsb"], -6)
        self.assertEqual(
            result["rolling_training"]["last_7_days"]["training_load"], 110.0
        )
        self.assertEqual(result["metrics"]["steps_7d"]["value"], 1000)
        self.assertEqual(result["metrics"]["floors_7d"]["value"], 5)
        self.assertEqual(result["metrics"]["calories_7d"]["value"], 2000)
        self.assertEqual(result["metrics"]["steps_7d"]["measurement_status"], "earlier")
        self.assertTrue(result["activity_validation"]["available"])

    def test_garmin_source_freshness_and_daily_health_window_are_explicit(self):
        today = date(2026, 9, 20)
        snapshot = {"recent_wellness": [], "recent_activities": []}
        garmin = {
            "sleep": [
                {
                    "calendarDate": today.isoformat(),
                    "sleepTimeSeconds": 28800,
                    "sleepScore": 90,
                }
            ],
            "daily_stats": [
                {"date": (today - timedelta(days=8)).isoformat(), "steps": 7},
                {"date": (today - timedelta(days=6)).isoformat(), "steps": 100},
                {"date": today.isoformat(), "steps": 999},
            ],
            "source_freshness": {
                "sleep": {
                    "freshness": "fresh",
                    "observed_at": today.isoformat(),
                },
                "daily_stats": {
                    "freshness": "partial",
                    "fetched_at": "2026-09-20T09:00:00Z",
                    "observed_at": (today - timedelta(days=1)).isoformat(),
                },
            },
        }

        result = current_performance_context(snapshot, garmin, {}, today)

        self.assertEqual(result["metrics"]["steps_7d"]["value"], 100)
        self.assertEqual(result["metrics"]["steps_7d"]["freshness"], "partial")
        self.assertEqual(result["recovery"]["sleep_hours"], 8.0)
        self.assertEqual(
            result["recovery"]["source_freshness"]["sleep_hours"]["freshness"], "fresh"
        )

    def test_actual_atl_rolling_training_and_input_nonmutation(self):
        today = date(2026, 9, 20)
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_wellness": [
                {"id": (today - timedelta(days=1)).isoformat(), "atl": 10, "ctl": 20},
                {"id": today.isoformat(), "atl": 12, "ctl": 20},
            ],
            "recent_activities": [
                {
                    "id": "load",
                    "type": "Ride",
                    "start_date_local": f"{today.isoformat()}T08:00:00",
                    "icu_training_load": 70,
                },
                "malformed",
            ],
        }
        garmin = {"source_freshness": {"max_metrics": {"freshness": "stale"}}}
        profile = {"weight_kg": "72"}
        before = (
            copy.deepcopy(snapshot),
            copy.deepcopy(garmin),
            copy.deepcopy(profile),
        )

        result = current_performance_context(snapshot, garmin, profile, today)

        self.assertEqual(result["actual_load"]["as_of"], today.isoformat())
        self.assertEqual(
            result["actual_load"]["source"], "Abgeschlossene Aktivitäten (berechnet)"
        )
        self.assertIn("last_28_days", result["rolling_training"])
        self.assertEqual((snapshot, garmin, profile), before)

    def test_missing_and_malformed_lists_do_not_break_projection(self):
        result = current_performance_context(
            {
                "synced_at": "now",
                "athlete": "invalid",
                "recent_wellness": [None, {"id": "2026-09-20", "readiness": "bad"}],
                "recent_activities": [None, "bad", {"type": "Unknown"}],
            },
            {},
            {},
            date(2026, 9, 20),
        )

        self.assertTrue(result["available"])
        self.assertIn("metrics", result)
        self.assertIn("activity_validation", result)


if __name__ == "__main__":
    unittest.main()
