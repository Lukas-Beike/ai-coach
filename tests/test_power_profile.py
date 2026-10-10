import unittest

from backend.performance.power_profile import power_profile, running_profile


class PowerProfileTests(unittest.TestCase):
    def test_sprint_is_not_lost_to_display_downsampling(self):
        watts = [200] * 2001
        watts[777:782] = [900] * 5
        result = power_profile(
            {"type": "Ride", "streams": {"time": list(range(2001)), "watts": watts}}
        )
        self.assertEqual(900, result["points"][0]["watts"])
        self.assertAlmostEqual(
            (5 * 900 + 55 * 200) / 60, result["points"][1]["watts"], places=2
        )

    def test_irregular_sample_intervals_are_weighted_and_zero_is_measured(self):
        result = power_profile(
            {"type": "Ride", "streams": {"time": [0, 1, 5], "watts": [100, 200, 200]}}
        )
        self.assertEqual(180, result["points"][0]["watts"])
        zero = power_profile(
            {"type": "Ride", "streams": {"time": [0, 5], "watts": [0, 0]}}
        )
        self.assertEqual(0, zero["points"][0]["watts"])

    def test_missing_or_stopped_recording_never_yields_peak(self):
        for streams in (
            {"time": [0, 5], "watts": [None, 200]},
            {"time": [0, 6], "watts": [200, 200]},
            {"time": [0, 5], "watts": [200, 200], "moving": [False, False]},
        ):
            self.assertEqual(
                "insufficient_data",
                power_profile({"type": "Ride", "streams": streams})["status"],
            )

    def test_duration_curve_and_running_efforts_keep_unknown_gaps(self):
        result = power_profile(
            {
                "type": "Ride",
                "streams": {"time": list(range(3601)), "watts": [250] * 3601},
            }
        )
        self.assertEqual(
            [5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600],
            [point["duration_seconds"] for point in result["duration_curve"]],
        )
        times = list(range(1201))
        streams = {
            "time": times,
            "distance": [i * 3 for i in times],
            "moving": [1] * len(times),
        }
        streams["distance"][400] = None
        running = running_profile({"type": "Run", "streams": streams})
        self.assertEqual("unknown", running["distance"][1]["status"])


if __name__ == "__main__":
    unittest.main()
