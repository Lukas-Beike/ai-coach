import unittest
from datetime import date

from backend.performance.training_focus import training_focus


class TrainingFocusTests(unittest.TestCase):
    def test_garmin_primary_effect_uses_recorded_load_and_skips_unknown(self):
        rows = [
            {"activityId": 1, "trainingEffectLabel": "aerobic_base", "activityTrainingLoad": 40},
            {"activityId": 2, "trainingEffectLabel": "TEMPO", "activityTrainingLoad": 80},
            {"activityId": 3, "trainingEffectLabel": "ANAEROBIC_CAPACITY", "activityTrainingLoad": 30},
            {"activityId": 4, "trainingEffectLabel": "OTHER", "activityTrainingLoad": 999},
            {"activityId": 5, "trainingEffectLabel": "TEMPO"},
        ]
        rows = [{**row, "startTimeLocal": "2026-10-02T08:00:00"} for row in rows]
        rows.append(rows[0])
        rows.append({**rows[0], "activityId": 6, "startTimeLocal": "2026-10-03T08:00:00"})
        result = training_focus({}, {"activities": rows}, date(2026, 10, 2))
        self.assertEqual(3, result["classified_sessions"])
        self.assertEqual(2, result["unclassified_sessions"])
        self.assertEqual(40, result["categories"]["low_aerobic"]["load"])
        self.assertEqual(80, result["categories"]["high_aerobic"]["load"])
        self.assertEqual(30, result["categories"]["anaerobic"]["load"])

    def test_recorded_hr_and_power_zones_remain_separate_and_bounded(self):
        rows = [{"id": "ride", "type": "Ride", "start_date_local": "2026-10-02T08:00:00",
                 "moving_time": 3600, "icu_hr_zone_times": [600, 1800, 1200, -1],
                 "icu_zone_times": [{"id": "Z1", "secs": 1000}, {"id": "Z2", "secs": 2600}]}]
        rows.append({**rows[0], "id": "old", "start_date_local": "2026-01-01T08:00:00"})
        result = training_focus({"recent_activities": rows}, {}, date(2026, 10, 2))
        zones = {row["sensor"]: row for row in result["zones"]}
        self.assertEqual({"Z1": 600, "Z2": 1800, "Z3": 1200}, zones["heart_rate"]["seconds"])
        self.assertEqual({"Z1": 1000, "Z2": 2600}, zones["power"]["seconds"])
        self.assertEqual(0, result["classified_sessions"])
