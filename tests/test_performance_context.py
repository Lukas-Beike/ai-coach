import copy
import unittest
from datetime import date, timedelta

from canonical_recovery_support import (
    recovery_inputs,
    recovery_observation,
    recovery_only_inputs,
)

from backend.canonical.vocabulary import MetricKind
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.context import current_performance_context


class PerformanceContextTests(unittest.TestCase):
    def test_none_and_empty_snapshots_are_unavailable(self):
        expected = {
            "available": False,
            "source": "Intervals.icu",
            "as_of": None,
            "metrics": {},
        }
        for snapshot in (None, {}):
            result = current_performance_context(snapshot, {}, {}, date(2026, 9, 20))
            recovery = result.pop("personal_recovery")
            focus = result.pop("training_focus")
            self.assertEqual(focus["zones"], [])
            self.assertEqual(focus["classified_sessions"], 0)
            self.assertEqual(result, expected)
            self.assertEqual(recovery["baselines"], [])
            self.assertEqual(recovery["sleep_deficits"], [])

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
        # Form and ramp rate come from canonical observations only (#1412): the
        # row's tsb is a carrier field and is not read without canonical inputs.
        self.assertIsNone(result["current_load"]["tsb"])
        self.assertIsNone(result["current_load"]["rampRate"])
        self.assertIsNone(result["current_load"]["rampRate_source"])
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

        result = current_performance_context(
            snapshot, garmin, {}, today, canonical=recovery_only_inputs(garmin)
        )

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

    def test_missing_snapshot_keeps_garmin_baselines_from_observations(self):
        today = date(2026, 9, 20)
        nights = [
            recovery_observation(
                MetricKind.RESTING_HR,
                48 + day % 3,
                (today - timedelta(days=day)).isoformat(),
                record_id=f"rhr-{day}",
            )
            for day in range(20)
        ]
        canonical = CanonicalPerformanceInputs(
            wellness_day=None, ctl=None, atl=None, recovery=recovery_inputs(nights)
        )

        result = current_performance_context(None, {}, {}, today, canonical=canonical)
        raw_only = current_performance_context(
            None,
            {"resting_hr": [{"calendarDate": "2026-09-20", "restingHR": 50}]},
            {},
            today,
        )

        self.assertFalse(result["available"])
        baseline = result["personal_recovery"]["baselines"][0]
        self.assertEqual(baseline["source"], "Garmin Connect")
        self.assertEqual(baseline["metric"], "resting_hr")
        self.assertEqual(baseline["status"], "provisional")
        # The raw Garmin view alone no longer produces a baseline.
        self.assertEqual(raw_only["personal_recovery"]["baselines"], [])

    def test_weekly_hrv_fallback_keeps_its_garmin_freshness(self):
        today = date(2026, 9, 7)
        garmin = {
            "hrv": [{"calendarDate": "2026-09-07", "weeklyAvg": 58}],
            "source_freshness": {
                "hrv": {"freshness": "stale", "observed_at": "2026-09-07"}
            },
        }
        snapshot = {"recent_wellness": [{"id": "2026-09-07"}], "recent_activities": []}

        recovery = current_performance_context(
            snapshot, garmin, {}, today, canonical=recovery_only_inputs(garmin)
        )["recovery"]

        self.assertEqual(recovery["hrv_source"], "Garmin Connect (Wochenmittel)")
        self.assertEqual(recovery["source_freshness"]["hrv"]["freshness"], "stale")


if __name__ == "__main__":
    unittest.main()
