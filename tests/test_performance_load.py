import unittest
from datetime import date
from inspect import signature

from backend.performance.load import activity_rollup


class PerformanceLoadTests(unittest.TestCase):
    def test_activity_rollup_has_required_end_date_and_includes_boundaries(self):
        self.assertIs(
            signature(activity_rollup).parameters["end_date"].default,
            signature(activity_rollup).empty,
        )
        anchor = date(2026, 9, 12)
        result = activity_rollup(
            [
                {
                    "started_at_local": "2026-09-11T07:00:00",
                    "moving_duration_s": 1800,
                    "training_load": 10,
                },
                {
                    "started_at_local": "2026-09-12",
                    "moving_duration_s": "3600",
                    "training_load": "42.5",
                },
                {
                    "started_at_local": "2026-09-10",
                    "moving_duration_s": 999,
                    "training_load": 99,
                },
            ],
            2,
            anchor,
        )
        self.assertEqual(
            result,
            {"days": 2, "sessions": 2, "duration_hours": 1.5, "training_load": 52.5},
        )

    def test_activity_rollup_ignores_invalid_rows_and_sums_multiple_loads_per_day(self):
        anchor = date(2026, 9, 12)
        activities = [
            {
                "started_at_local": "2026-09-12",
                "moving_duration_s": "invalid",
                "training_load": None,
            },
            {
                "started_at_local": "not-a-date",
                "moving_duration_s": 7200,
                "training_load": 90,
            },
            {
                "started_at_local": "2026-09-11",
                "moving_duration_s": 1800,
                "training_load": 10,
            },
            {
                "started_at_local": "2026-09-11",
                "moving_duration_s": 1800,
                "training_load": 15,
            },
            "not-an-activity",
        ]
        original = [row.copy() if isinstance(row, dict) else row for row in activities]
        self.assertEqual(
            activity_rollup(activities, 2, anchor),
            {
                "days": 2,
                "sessions": 3,
                "duration_hours": 1.0,
                "training_load": 25.0,
                "load_missing_sessions": 1,
            },
        )
        self.assertEqual(activities, original)

    def test_sessions_without_a_tss_scale_load_are_counted_with_their_rpe_load(
        self,
    ):
        # #1672: a Garmin-only session (EPOC load) is left out of the sum, counted,
        # and its session-RPE load is reported beside it in AU, never added.
        anchor = date(2026, 9, 12)
        activities = [
            {
                "id": "act_1",
                "started_at_local": "2026-09-12T07:00:00",
                "elapsed_duration_s": 3600,
                "training_load": 60,
            },
            {
                "id": "act_2",
                "started_at_local": "2026-09-12T18:00:00",
                "elapsed_duration_s": 1800,
                "load_model": "garmin_training_load",
            },
            {"id": "act_3", "started_at_local": "2026-09-11T18:00:00"},
        ]
        feedback = {"act_2": {"session_rpe": 6}}

        rollup = activity_rollup(activities, 7, anchor, session_feedback=feedback)

        self.assertEqual(rollup["training_load"], 60.0)
        self.assertEqual(rollup["load_missing_sessions"], 2)
        self.assertEqual(rollup["load_missing_session_rpe_au"], 180.0)
        self.assertEqual(rollup["load_missing_session_rpe_source"], "Athletenfeedback")
        provider_rated = {
            **activities[1],
            "rpe": 5,
            "sources": {"rpe": "Intervals.icu"},
        }
        fallback = activity_rollup([provider_rated], 7, anchor)
        self.assertEqual(fallback["load_missing_session_rpe_au"], 150.0)
        self.assertEqual(fallback["load_missing_session_rpe_source"], "Intervals.icu")
        self.assertNotIn(
            "load_missing_sessions",
            activity_rollup(activities[:1], 7, anchor, session_feedback=feedback),
        )


if __name__ == "__main__":
    unittest.main()
