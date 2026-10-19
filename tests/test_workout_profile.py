import unittest

from backend.activities.workout_profile import planned_profile, recorded_profile
from backend.activities.zone_settings import ZoneSettings


class WorkoutProfileTests(unittest.TestCase):
    def test_explicit_steps_have_time_widths_zones_and_ramps(self):
        profile = planned_profile(
            {"description": "- 15m 50%\n- 5m 100%\n- 5m ramp 50-80%"}
        )
        self.assertEqual(
            [900, 300, 300], [row["duration"] for row in profile["segments"]]
        )
        self.assertEqual([1, 4, 2], [row["zone"] for row in profile["segments"]])
        self.assertEqual(
            (50, 80),
            (profile["segments"][-1]["value"], profile["segments"][-1]["end_value"]),
        )
        self.assertEqual("planned", profile["source"])

    def test_unknown_structure_and_mixed_axes_do_not_invent_a_profile(self):
        for description in (
            "Run easily",
            "- 10m 50%\n- 10m Z2 HR",
            "- 10m Z2 Pace\n- 5km Z3 Pace",
        ):
            self.assertIsNone(planned_profile({"description": description}))
        profile = planned_profile({"description": "- 30m 200w"})
        self.assertIsNone(profile["segments"][0]["zone"])
        self.assertEqual("duration", profile["axis"])

    def test_distance_steps_use_a_distance_axis_with_zones(self):
        profile = planned_profile(
            {"description": "- 2km Z1 Pace\n- 5km Z2 Pace\n- 1km 100% Pace"}
        )
        self.assertEqual("distance", profile["axis"])
        self.assertEqual(
            [2000, 5000, 1000], [row["distance"] for row in profile["segments"]]
        )
        self.assertTrue(all("duration" not in row for row in profile["segments"]))
        self.assertEqual("zone", profile["unit"])
        self.assertEqual([1, 2, 4], [row["zone"] for row in profile["segments"]])

    def test_run_steps_mixing_zone_and_heart_rate_percent_share_the_zone_axis(self):
        profile = planned_profile(
            {
                "description": (
                    "- 10m Z1-Z2 HR\n- 8m 86-89% HR\n- 3m Z1 HR\n"
                    "- 8m 86-89% HR\n- 10m Z1 HR"
                )
            }
        )
        self.assertEqual("zone", profile["unit"])
        self.assertEqual(
            [600, 480, 180, 480, 600], [row["duration"] for row in profile["segments"]]
        )
        self.assertEqual([2, 4, 1, 4, 1], [row["zone"] for row in profile["segments"]])
        self.assertEqual([2, 4, 1, 4, 1], [row["value"] for row in profile["segments"]])

    def test_heart_rate_and_pace_percent_targets_get_zones(self):
        lthr = planned_profile({"description": "- 5m 60% LTHR\n- 5m 100% LTHR"})
        self.assertEqual([1, 4], [row["zone"] for row in lthr["segments"]])
        pace = planned_profile({"description": "- 5m 80% Pace\n- 5m 97% Pace"})
        self.assertEqual("%PACE", pace["unit"])
        self.assertEqual([2, 4], [row["zone"] for row in pace["segments"]])

    def test_absolute_targets_without_thresholds_stay_uncolored(self):
        profile = planned_profile({"description": "- 5m 150-160bpm\n- 5m Z2 HR"})
        self.assertIsNone(profile)
        profile = planned_profile({"description": "- 5m 150-160bpm"})
        self.assertIsNone(profile["segments"][0]["zone"])
        self.assertEqual("bpm", profile["unit"])

    def test_absolute_targets_are_colored_from_thresholds_and_marked_estimated(self):
        settings = ZoneSettings(ftp=250, lthr=170)
        watts = planned_profile({"description": "- 5m 125w\n- 5m 240-260w"}, settings)
        self.assertEqual([1, 4], [row["zone"] for row in watts["segments"]])
        self.assertTrue(watts["estimated"])
        bpm = planned_profile({"description": "- 5m 150-160bpm"}, settings)
        self.assertEqual([3], [row["zone"] for row in bpm["segments"]])
        self.assertTrue(bpm["estimated"])
        # The matching threshold is required: no FTP, no watt zones.
        only_lthr = planned_profile(
            {"description": "- 5m 200w"}, ZoneSettings(lthr=170)
        )
        self.assertIsNone(only_lthr["segments"][0]["zone"])
        self.assertNotIn("estimated", only_lthr)

    def test_relative_targets_are_not_marked_estimated(self):
        profile = planned_profile(
            {"description": "- 5m 100%\n- 5m Z2"}, ZoneSettings(ftp=250, lthr=170)
        )
        self.assertNotIn("estimated", profile)

    def test_repeated_distance_blocks_get_a_distance_profile(self):
        profile = planned_profile(
            {
                "description": (
                    "- 2km Z1 Pace\n\n3x\n- 1km Z4 Pace\n- 400mtr Z1 Pace\n\n"
                    "- 1km Z1 Pace"
                )
            }
        )
        self.assertEqual("distance", profile["axis"])
        self.assertEqual(
            [2000, 1000, 400, 1000, 400, 1000, 400, 1000],
            [row["distance"] for row in profile["segments"]],
        )
        self.assertEqual(
            [1, 4, 1, 4, 1, 4, 1, 1], [row["zone"] for row in profile["segments"]]
        )

    def test_percent_targets_follow_custom_zone_limits(self):
        description = "- 5m 70%\n- 5m 100%"
        self.assertEqual(
            [2, 4],
            [
                row["zone"]
                for row in planned_profile({"description": description})["segments"]
            ],
        )
        custom = ZoneSettings(power_limits=(50, 65, 80, 95, 110, 140))
        self.assertEqual(
            [3, 5],
            [
                row["zone"]
                for row in planned_profile({"description": description}, custom)[
                    "segments"
                ]
            ],
        )

    def test_heart_rate_percent_of_max_uses_the_athletes_max_heart_rate(self):
        description = "- 5m 70% HR"
        default = planned_profile({"description": description})
        self.assertEqual(2, default["segments"][0]["zone"])
        # 70 % of 200 bpm is 140 bpm, 82 % of a 170 bpm threshold.
        known = planned_profile(
            {"description": description}, ZoneSettings(lthr=170, max_hr=200)
        )
        self.assertEqual(2, known["segments"][0]["zone"])
        low_threshold = planned_profile(
            {"description": description}, ZoneSettings(lthr=140, max_hr=200)
        )
        self.assertEqual(4, low_threshold["segments"][0]["zone"])

    def test_recorded_heart_rate_profile_uses_the_activity_threshold(self):
        activity = {
            "streams": {"time": list(range(61)), "heartrate": [140] * 61},
            "lthr": 170,
        }
        self.assertEqual(2, recorded_profile(activity)["segments"][0]["zone"])
        activity.pop("lthr")
        self.assertIsNone(recorded_profile(activity)["segments"][0]["zone"])

    def test_recorded_profile_keeps_gaps_and_uses_only_historical_ftp(self):
        samples = [100] * 61
        samples[20:40] = [None] * 20
        activity = {
            "streams": {"time": list(range(61)), "watts": samples},
            "icu_ftp": 200,
        }
        profile = recorded_profile(activity)
        self.assertEqual("recorded", profile["source"])
        self.assertEqual(60, len(profile["segments"]))
        self.assertEqual(100, profile["segments"][0]["value"])
        self.assertEqual(1, profile["segments"][0]["zone"])
        self.assertIsNone(profile["segments"][25]["value"])
        activity.pop("icu_ftp")
        self.assertIsNone(recorded_profile(activity)["segments"][0]["zone"])

    def test_sparse_or_invalid_recordings_are_not_filled(self):
        self.assertIsNone(
            recorded_profile({"streams": {"time": [0, 100], "watts": [200, 200]}})
        )
        self.assertIsNone(
            recorded_profile(
                {"streams": {"time": [0, 1], "watts": [float("nan"), 200]}}
            )
        )
