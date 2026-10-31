import unittest
from datetime import date

from performance_day_support import garmin_activity_summaries, garmin_sync_status

from backend.performance.training_focus import training_focus


class TrainingFocusTests(unittest.TestCase):
    def test_garmin_primary_effect_uses_recorded_load_and_skips_unknown(self):
        rows = [
            {
                "activityId": 1,
                "trainingEffectLabel": "aerobic_base",
                "activityTrainingLoad": 40,
            },
            {
                "activityId": 2,
                "trainingEffectLabel": "TEMPO",
                "activityTrainingLoad": 80,
            },
            {
                "activityId": 3,
                "trainingEffectLabel": "ANAEROBIC_CAPACITY",
                "activityTrainingLoad": 30,
            },
            {
                "activityId": 4,
                "trainingEffectLabel": "OTHER",
                "activityTrainingLoad": 999,
            },
            {"activityId": 5, "trainingEffectLabel": "TEMPO"},
        ]
        rows = [{**row, "startTimeLocal": "2026-10-02T08:00:00"} for row in rows]
        rows.append(rows[0])
        rows.append(
            {**rows[0], "activityId": 6, "startTimeLocal": "2026-10-03T08:00:00"}
        )
        result = training_focus(
            garmin_sync_status({"activities": rows}),
            date(2026, 10, 2),
            activities=garmin_activity_summaries({"activities": rows}),
        )
        self.assertEqual(3, result["classified_sessions"])
        self.assertEqual(2, result["unclassified_sessions"])
        self.assertEqual(
            {
                "known_sessions": 5,
                "observed_start": "2026-10-02",
                "observed_end": "2026-10-02",
            },
            result["coverage"],
        )
        self.assertEqual(40, result["categories"]["low_aerobic"]["load"])
        self.assertEqual(80, result["categories"]["high_aerobic"]["load"])
        self.assertEqual(30, result["categories"]["anaerobic"]["load"])

    def test_recorded_hr_and_power_zones_remain_separate_and_bounded(self):
        rows = [
            {
                "id": "ride",
                "sport": "ride",
                "started_at_local": "2026-10-02T08:00:00",
                "moving_duration_s": 3600,
                "sources": {
                    "heart_rate_zone_times": "Intervals.icu",
                    "power_zone_times": "Intervals.icu",
                },
                "heart_rate_zone_times": [
                    {"id": "Z1", "secs": 600},
                    {"id": "Z2", "secs": 1800},
                    {"id": "Z3", "secs": 1200},
                    {"id": "Z4", "secs": -1},
                ],
                "power_zone_times": [
                    {"id": "Z1", "secs": 1000},
                    {"id": "Z2", "secs": 2600},
                ],
            }
        ]
        rows.append({**rows[0], "id": "old", "started_at_local": "2026-01-01T08:00:00"})
        result = training_focus(
            garmin_sync_status({}), date(2026, 10, 2), activities=rows
        )
        zones = {row["sensor"]: row for row in result["zones"]}
        self.assertEqual(
            {"Z1": 600, "Z2": 1800, "Z3": 1200}, zones["heart_rate"]["seconds"]
        )
        self.assertEqual({"Z1": 1000, "Z2": 2600}, zones["power"]["seconds"])
        self.assertEqual("ride", zones["power"]["sport"])
        self.assertEqual("Intervals.icu", zones["power"]["source"])
        self.assertEqual(0, result["classified_sessions"])

    def test_focus_uses_exactly_four_weeks_including_today(self):
        rows = [
            {
                "activityId": index,
                "startTimeLocal": day + "T08:00:00",
                "trainingEffectLabel": "TEMPO",
                "activityTrainingLoad": 40,
            }
            for index, day in enumerate(
                ("2026-09-04", "2026-09-05", "2026-10-02", "2026-10-03"), 1
            )
        ]
        result = training_focus(
            garmin_sync_status({"activities": rows}),
            date(2026, 10, 2),
            activities=garmin_activity_summaries({"activities": rows}),
        )
        self.assertEqual(result["start"], "2026-09-05")
        self.assertEqual(result["end"], "2026-10-02")
        self.assertEqual(result["classified_sessions"], 2)
        self.assertEqual(result["categories"]["high_aerobic"]["load"], 80)

    def test_dedicated_activity_loads_join_base_activities_and_keep_unknowns(self):
        base = [
            {
                "activityId": "matched",
                "startTimeLocal": "2026-10-02T08:00:00",
                "trainingEffectLabel": "TEMPO",
                "activityTrainingLoad": 40,
            },
            {"activityId": "unmatched", "startTimeLocal": "2026-10-02T09:00:00"},
        ]
        result = training_focus(
            garmin_sync_status(
                {
                    "activities": base,
                    "training_load_activities": [
                        {
                            "activityId": "matched",
                            "trainingEffectLabel": "VO2_MAX",
                            "activityTrainingLoad": 80,
                        },
                        {
                            "activityId": "without-base",
                            "trainingEffectLabel": "TEMPO",
                            "activityTrainingLoad": 900,
                        },
                    ],
                    "source_freshness": {
                        "activities": {"freshness": "current"},
                        "training_load_activities": {"freshness": "partial"},
                    },
                }
            ),
            date(2026, 10, 2),
            activities=garmin_activity_summaries(
                {
                    "activities": base,
                    "training_load_activities": [
                        {
                            "activityId": "matched",
                            "trainingEffectLabel": "VO2_MAX",
                            "activityTrainingLoad": 80,
                        },
                        {
                            "activityId": "without-base",
                            "trainingEffectLabel": "TEMPO",
                            "activityTrainingLoad": 900,
                        },
                    ],
                    "source_freshness": {
                        "activities": {"freshness": "current"},
                        "training_load_activities": {"freshness": "partial"},
                    },
                }
            ),
        )
        self.assertEqual(result["coverage"]["known_sessions"], 2)
        self.assertEqual(result["classified_sessions"], 1)
        self.assertEqual(result["unclassified_sessions"], 1)
        self.assertEqual(result["categories"]["high_aerobic"]["load"], 80)
        self.assertEqual(
            result["category_freshness"]["training_load_activities"]["freshness"],
            "partial",
        )

    def test_activity_without_identity_is_not_a_session(self):
        # Canonical reads (#1416): the mapper drops a row without an activity id,
        # so it is neither a known nor an unclassified session.
        result = training_focus(
            garmin_sync_status(
                {
                    "activities": [
                        {
                            "startTimeLocal": "2026-10-02T09:00:00",
                            "trainingEffectLabel": "TEMPO",
                            "activityTrainingLoad": 40,
                        }
                    ]
                }
            ),
            date(2026, 10, 2),
            activities=garmin_activity_summaries(
                {
                    "activities": [
                        {
                            "startTimeLocal": "2026-10-02T09:00:00",
                            "trainingEffectLabel": "TEMPO",
                            "activityTrainingLoad": 40,
                        }
                    ]
                }
            ),
        )
        self.assertEqual(result["coverage"]["known_sessions"], 0)
        self.assertEqual(result["classified_sessions"], 0)
        self.assertEqual(result["unclassified_sessions"], 0)
        self.assertEqual(result["categories"]["high_aerobic"]["sessions"], 0)
