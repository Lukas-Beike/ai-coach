import unittest

from backend.performance.power_profile import power_profile, running_profile


class PowerProfileTests(unittest.TestCase):
    def test_sprint_is_not_lost_to_display_downsampling(self):
        watts = [200] * 2001
        watts[777:782] = [900] * 5
        result = power_profile(
            {"sport": "ride", "streams": {"time": list(range(2001)), "watts": watts}}
        )
        self.assertEqual(900, result["points"][0]["watts"])
        self.assertAlmostEqual(
            (5 * 900 + 55 * 200) / 60, result["points"][1]["watts"], places=2
        )

    def test_irregular_sample_intervals_are_weighted_and_zero_is_measured(self):
        result = power_profile(
            {"sport": "ride", "streams": {"time": [0, 1, 5], "watts": [100, 200, 200]}}
        )
        self.assertEqual(180, result["points"][0]["watts"])
        zero = power_profile(
            {"sport": "ride", "streams": {"time": [0, 5], "watts": [0, 0]}}
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
                power_profile({"sport": "ride", "streams": streams})["status"],
            )

    def test_duration_curve_and_running_efforts_keep_unknown_gaps(self):
        result = power_profile(
            {
                "sport": "ride",
                "streams": {"time": list(range(3601)), "watts": [250] * 3601},
            }
        )
        self.assertEqual(
            [5, 15, 30, 60, 120, 180, 300, 420, 600, 720, 1200, 1800, 3600],
            [point["duration_seconds"] for point in result["duration_curve"]],
        )
        times = list(range(1201))
        streams = {
            "time": times,
            "distance": [i * 3 for i in times],
            "moving": [1] * len(times),
        }
        streams["distance"][400] = None
        running = running_profile({"sport": "run", "streams": streams})
        self.assertEqual("unknown", running["distance"][1]["status"])

    def test_protocol_windows_reproduce_known_maxima_around_gaps_and_pauses(self):
        times = list(range(2401))
        watts = [100.0] * len(times)
        moving = [True] * len(times)
        for start, end, value in (
            (100, 280, 450),
            (1000, 1420, 330),
            (1600, 2320, 300),
        ):
            watts[start:end] = [value] * (end - start)
        # A 900 W effort split by a gap and a pause never fills a 3-min window.
        watts[500:850] = [900] * 350
        watts[499] = watts[620] = watts[850] = None
        moving[740] = False
        result = power_profile(
            {
                "sport": "ride",
                "streams": {"time": times, "watts": watts, "moving": moving},
            }
        )
        best = {p["duration_seconds"]: p for p in result["duration_curve"]}
        self.assertEqual(
            {180: 450, 420: 330, 720: 300},
            {duration: best[duration]["watts"] for duration in (180, 420, 720)},
        )
        self.assertEqual(
            {180: 100, 420: 1000, 720: 1600},
            {duration: best[duration]["start_seconds"] for duration in (180, 420, 720)},
        )
        self.assertEqual(
            ("mean-max-curve", 1), (result["method"], result["method_version"])
        )

        speed = [3.0] * len(times)
        for start, end, value in (
            (100, 280, 5.0),
            (1000, 1420, 4.5),
            (1600, 2320, 4.2),
        ):
            speed[start:end] = [value] * (end - start)
        distance = [0.0]
        for value in speed[:-1]:
            distance.append(distance[-1] + value)
        running = running_profile(
            {
                "sport": "run",
                "streams": {
                    "time": times,
                    "velocity_smooth": speed,
                    "distance": distance,
                },
            }
        )
        fastest = {p["duration_seconds"]: p["speed_mps"] for p in running["speed"]}
        self.assertEqual(
            {180: 5.0, 420: 4.5, 720: 4.2}, {d: fastest[d] for d in (180, 420, 720)}
        )
        self.assertEqual(
            ("mean-max-curve", 1), (running["method"], running["method_version"])
        )

    def test_source_label_names_the_stream_provider(self):
        ride = {"sport": "ride", "streams": {"time": [0, 5], "watts": [200, 200]}}
        self.assertEqual(
            "Wahoo original watts stream",
            power_profile(ride, source_label="Wahoo")["source"],
        )
        run = {
            "sport": "run",
            "streams": {"time": [0, 1], "velocity_smooth": [3, 3], "distance": [0, 3]},
        }
        self.assertEqual(
            "Garmin original speed/distance streams",
            running_profile(run, source_label="Garmin")["source"],
        )


if __name__ == "__main__":
    unittest.main()
