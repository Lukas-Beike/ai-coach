"""Analytic synthetic signals verify time weighting and conservative eligibility."""

import unittest

from backend.performance.session_analysis import (
    aerobic_analysis,
    heart_rate_histogram,
    interval_quality,
)
from backend.planning.target_snapshot import freeze_targets


def ride(times=None):
    times = list(range(3601)) if times is None else times
    return {
        "sport": "ride",
        "streams": {
            "time": times,
            "watts": [200] * len(times),
            "heartrate": [100 if time < 2100 else 110 for time in times],
        },
    }


def run(environment="outdoor", grade=True):
    """Flat first half at 3.0 m/s, then 2.8 m/s up a 2 % grade, HR constant."""
    times = list(range(3601))
    streams = {
        "time": times,
        "velocity_smooth": [3.0 if time < 2100 else 2.8 for time in times],
        "heartrate": [150] * len(times),
    }
    if grade:
        streams["grade_smooth"] = [0.0 if time < 2100 else 2.0 for time in times]
    return {"sport": "run", "environment": environment, "streams": streams}


class SessionAnalysisTests(unittest.TestCase):
    def test_heart_rate_histogram_counts_moving_seconds_per_bpm(self):
        # 100 s at 120 bpm, a 40 s pause (nothing counted), 50 s at 150 bpm of
        # which the first 10 s are stopped; 25 and 250 bpm are no readings.
        times = list(range(101)) + [140 + second for second in range(51)]
        heart = [120.4] * 101 + [150] * 51
        moving = [True] * 101 + [False] * 10 + [True] * 41
        heart[10] = 25
        heart[11] = 250
        result = heart_rate_histogram(
            {"streams": {"time": times, "heartrate": heart, "moving": moving}}
        )
        self.assertEqual({"120": 98.0, "150": 40.0}, result["seconds"])
        self.assertEqual(138.0, result["covered_s"])

    def test_heart_rate_histogram_needs_a_matching_stream(self):
        self.assertIsNone(heart_rate_histogram({"streams": {"time": [0, 1, 2]}}))
        self.assertIsNone(
            heart_rate_histogram({"streams": {"time": [0, 1], "heartrate": [100]}})
        )

    def test_outdoor_run_decoupling_uses_grade_adjusted_speed(self):
        # Card M8 v2 worked example: Minetti cost at 2 % is 3.6 * 3.1175 / 2.8 J/kg/m,
        # so 2.8 m/s uphill is 3.1175 m/s on level ground. Raw speed would give
        # (3.0 - 2.8) / 3.0 = +6.67 %; grade-adjusted (3.0 - 3.1175) / 3.0 = -3.92 %.
        result = aerobic_analysis(run())
        self.assertEqual("ok", result["status"])
        self.assertEqual("grade_adjusted_speed", result["sensor"])
        self.assertAlmostEqual(-3.92, result["drift_percent"], places=2)
        self.assertAlmostEqual(3.1175, result["halves"][1]["mean_output"], places=4)

    def test_altitude_and_distance_give_the_grade_without_a_grade_stream(self):
        activity = run(grade=False)
        times = activity["streams"]["time"]
        distance, altitude, here, height = [], [], 0.0, 100.0
        for time in times:
            speed, slope = (3.0, 0.0) if time < 2100 else (2.8, 0.02)
            distance.append(here)
            altitude.append(height)
            here += speed
            height += speed * slope
        activity["streams"].update(distance=distance, altitude=altitude)
        result = aerobic_analysis(activity)
        self.assertEqual("grade_adjusted_speed", result["sensor"])
        self.assertLess(result["drift_percent"], 0)

    def test_outdoor_run_without_grade_or_altitude_has_no_decoupling(self):
        result = aerobic_analysis(run(grade=False))
        self.assertEqual("insufficient_data", result["status"])
        self.assertIn("Steigung oder Höhe fehlt", result["reason"])

    def test_treadmill_run_keeps_raw_speed(self):
        result = aerobic_analysis(run("indoor", grade=False))
        self.assertEqual("ok", result["status"])
        self.assertEqual("velocity_smooth", result["sensor"])
        self.assertAlmostEqual(6.67, result["drift_percent"], places=2)

    def test_pulse_rise_at_constant_output_has_known_drift(self):
        result = aerobic_analysis(ride())
        self.assertEqual("ok", result["status"])
        self.assertAlmostEqual(9.09, result["drift_percent"], places=2)
        self.assertEqual("W/bpm", result["unit"])

    def test_irregular_time_spacing_preserves_time_weighted_result(self):
        result = aerobic_analysis(
            ride(list(range(0, 2101, 2)) + list(range(2103, 3601, 3)))
        )
        self.assertEqual("ok", result["status"])
        self.assertAlmostEqual(9.09, result["drift_percent"], places=2)

    def test_missing_pulse_stops_and_variable_intervals_stay_open(self):
        for variant in ("pulse", "stops", "variable", "gap"):
            activity = ride()
            if variant == "pulse":
                activity["streams"].pop("heartrate")
            elif variant == "stops":
                activity["streams"]["moving"] = [False] * 3601
            elif variant == "variable":
                activity["streams"]["watts"] = [
                    100 if i % 2 else 300 for i in range(3601)
                ]
            else:
                activity = ride(list(range(601)) + list(range(2100, 3601)))
            with self.subTest(variant=variant):
                self.assertEqual(
                    "insufficient_data", aerobic_analysis(activity)["status"]
                )

    def test_target_uses_frozen_ftp_and_partial_completion_is_partial(self):
        activity = ride(list(range(121)))
        activity["laps"] = [{"start_time": 0, "end_time": 120}]
        targets = {
            "steps": [{"kind": "power", "target": "100%", "duration": 120}] * 2,
            "basis": {"ftp": 200},
        }
        result = interval_quality(activity, targets)
        self.assertEqual("partial", result["status"])
        self.assertEqual(1, result["missing_steps"])
        self.assertEqual(120, result["steps"][0]["seconds_in_target"])
        self.assertEqual(0, result["steps"][0]["average_deviation_percent"])
        targets["basis"] = {}
        self.assertEqual(
            "insufficient_data",
            interval_quality(activity, targets)["steps"][0]["status"],
        )

    def test_measured_duration_does_not_imply_target_achievement(self):
        activity = ride(list(range(121)))
        activity["laps"] = [{"start_time": 0, "end_time": 120}]
        targets = {"steps": [{"kind": "power", "target": "300W", "duration": 120}]}
        result = interval_quality(activity, targets)["steps"][0]
        self.assertEqual(0, result["seconds_in_target"])
        self.assertAlmostEqual(-33.33, result["average_deviation_percent"])

    def test_ambiguous_laps_are_not_scored(self):
        activity = ride(list(range(121)))
        activity["laps"] = [{"start_time": 0, "end_time": 100}]
        self.assertEqual(
            "insufficient_data",
            interval_quality(
                activity,
                {"steps": [{"kind": "power", "target": "200W", "duration": 120}]},
            )["status"],
        )

    def test_only_unique_local_match_can_freeze_targets(self):
        local = [
            {
                "id": "local-1",
                "date": "2026-10-02",
                "sport": "ride",
                "description": "- 2m 200w",
                "target": "POWER",
            }
        ]
        # Activity summaries: the local session id plus the Intervals.icu record id,
        # which is the stored key the targets are frozen under.
        rows = [
            {
                "id": "act_1",
                "record_ids": {"intervals": "activity-1"},
                "started_at_local": "2026-10-02T08:00:00",
                "sport": "ride",
            }
        ]
        frozen = freeze_targets(
            local, rows, "activity-1", {"ftp": 250}, "2026-10-02T10:00:00Z"
        )
        self.assertIsNotNone(frozen)
        self.assertEqual(120, frozen["steps"][0]["duration"])
        self.assertIsNone(
            freeze_targets(
                local,
                rows
                + [
                    {
                        **rows[0],
                        "id": "act_2",
                        "record_ids": {"intervals": "activity-2"},
                    }
                ],
                "activity-1",
                {},
                "now",
            )
        )

    def test_source_label_names_the_stream_provider(self):
        result = aerobic_analysis(ride(), source_label="Garmin")
        self.assertEqual("derived from Garmin original streams", result["source"])
        self.assertNotIn("provider_decoupling", result)
        self.assertEqual(
            "derived from Garmin Connect, Wahoo original streams",
            aerobic_analysis(ride())["source"],
        )
        activity = ride(list(range(121)))
        activity["laps"] = [{"start_time": 0, "end_time": 120}]
        targets = {"steps": [{"kind": "power", "target": "200W", "duration": 120}]}
        result = interval_quality(activity, targets, source_label="Wahoo")
        self.assertEqual(
            "derived from Wahoo original streams and frozen local targets",
            result["source"],
        )


if __name__ == "__main__":
    unittest.main()
