import unittest

from backend.activities.workout_profile import planned_profile, recorded_profile


class WorkoutProfileTests(unittest.TestCase):
    def test_explicit_steps_have_time_widths_zones_and_ramps(self):
        profile = planned_profile({"description": "- 15m 50%\n- 5m 100%\n- 5m ramp 50-80%"})
        self.assertEqual([900, 300, 300], [row["duration"] for row in profile["segments"]])
        self.assertEqual([1, 4, 2], [row["zone"] for row in profile["segments"]])
        self.assertEqual((50, 80), (profile["segments"][-1]["value"], profile["segments"][-1]["end_value"]))
        self.assertEqual("planned", profile["source"])

    def test_unknown_structure_and_distance_do_not_invent_a_time_profile(self):
        for description in ("Run easily", "- 5km Z2 Pace", "- 10m 50%\n- 10m Z2 HR"):
            self.assertIsNone(planned_profile({"description": description}))
        profile = planned_profile({"description": "- 30m 200w"})
        self.assertIsNone(profile["segments"][0]["zone"])

    def test_recorded_profile_keeps_gaps_and_uses_only_historical_ftp(self):
        samples = [100] * 61
        samples[20:40] = [None] * 20
        activity = {"streams": {"time": list(range(61)), "watts": samples}, "icu_ftp": 200}
        profile = recorded_profile(activity)
        self.assertEqual("recorded", profile["source"])
        self.assertEqual(60, len(profile["segments"]))
        self.assertEqual(100, profile["segments"][0]["value"])
        self.assertEqual(1, profile["segments"][0]["zone"])
        self.assertIsNone(profile["segments"][25]["value"])
        activity.pop("icu_ftp")
        self.assertIsNone(recorded_profile(activity)["segments"][0]["zone"])

    def test_sparse_or_invalid_recordings_are_not_filled(self):
        self.assertIsNone(recorded_profile({"streams": {"time": [0, 100], "watts": [200, 200]}}))
        self.assertIsNone(recorded_profile({"streams": {"time": [0, 1], "watts": [float("nan"), 200]}}))
