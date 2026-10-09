"""Analytic synthetic signals verify time weighting and conservative eligibility."""

import unittest

from backend.performance.session_analysis import aerobic_analysis, interval_quality
from backend.planning.target_snapshot import freeze_targets


def ride(times=None):
    times = list(range(3601)) if times is None else times
    return {
        "type": "Ride",
        "streams": {
            "time": times,
            "watts": [200] * len(times),
            "heartrate": [100 if time < 2100 else 110 for time in times],
        },
    }


class SessionAnalysisTests(unittest.TestCase):
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
                activity = ride([0, 600, 2100, 3600])
            with self.subTest(variant=variant):
                self.assertEqual(
                    "insufficient_data", aerobic_analysis(activity)["status"]
                )

    def test_target_uses_frozen_ftp_and_partial_completion_is_partial(self):
        activity = ride(list(range(121)))
        activity["laps"] = [{"start_time": 0, "end_time": 120}]
        targets = {
            "steps": [{"kind": "power", "target": "100%", "duration": 120}] * 2,
            "basis": {"icu_ftp": 200},
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
                "type": "Ride",
                "description": "- 2m 200w",
                "target": "POWER",
            }
        ]
        rows = [
            {
                "id": "activity-1",
                "start_date_local": "2026-10-02T08:00:00",
                "type": "Ride",
            }
        ]
        frozen = freeze_targets(
            local, rows, "activity-1", {"icu_ftp": 250}, "2026-10-02T10:00:00Z"
        )
        self.assertIsNotNone(frozen)
        self.assertEqual(120, frozen["steps"][0]["duration"])
        self.assertIsNone(
            freeze_targets(
                local, rows + [{**rows[0], "id": "activity-2"}], "activity-1", {}, "now"
            )
        )


if __name__ == "__main__":
    unittest.main()
