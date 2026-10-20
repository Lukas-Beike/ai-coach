import unittest

from backend.activities.zone_settings import (
    HR_ZONE_LIMITS,
    POWER_ZONE_LIMITS,
    ZoneSettings,
)
from backend.canonical.vocabulary import Environment, Sport

RIDE = {
    "types": ["Ride", "VirtualRide"],
    "ftp": 250,
    "lthr": 160,
    "max_hr": 190,
    "power_zones": [50, 70, 85, 100, 115, 140, 999],
    "hr_zones": [100, 120, 140, 160, 175, 190, 200],
}
RUN = {
    "types": ["Run"],
    "lthr": 170,
    "pace_zones": [75, 85, 92, 100, 105, 112, 999],
}


class ZoneSettingsTests(unittest.TestCase):
    def test_settings_are_chosen_per_sport(self):
        settings = [RUN, RIDE]
        ride = ZoneSettings.from_sport_settings(settings, Sport.RIDE)
        run = ZoneSettings.from_sport_settings(settings, Sport.RUN)
        self.assertEqual((250, 160, 190), (ride.ftp, ride.lthr, ride.max_hr))
        self.assertEqual((None, 170), (run.ftp, run.lthr))
        self.assertEqual(
            ZoneSettings(), ZoneSettings.from_sport_settings(settings, Sport.SWIM)
        )

    def test_custom_limits_replace_the_defaults(self):
        ride = ZoneSettings.from_sport_settings([RIDE], Sport.RIDE)
        self.assertEqual((50, 70, 85, 100, 115, 140), ride.power_limits)
        # Heart-rate zones arrive as bpm and are kept as percent of LTHR.
        self.assertEqual(
            [62.5, 75, 87.5, 100, 109.375, 118.75],
            [round(limit, 3) for limit in ride.hr_limits],
        )
        run = ZoneSettings.from_sport_settings([RUN], Sport.RUN)
        self.assertEqual((75, 85, 92, 100, 105, 112), run.pace_limits)
        self.assertEqual(HR_ZONE_LIMITS, run.hr_limits)

    def test_invalid_zone_lists_fall_back_to_the_defaults(self):
        for zones in (
            "50,70",
            [50, 999],
            [50, 70, 85, 100, 115, 125, 140, 999],
            [50, 70, 85, 100, 115, None, 999],
            [50, 70, 70, 100, 115, 140, 999],
            [50, 70, 85, 100, 115, float("nan"), 999],
            [True, 70, 85, 100, 115, 140, 999],
        ):
            settings = ZoneSettings.from_sport_settings(
                [{"types": ["Ride"], "power_zones": zones}], Sport.RIDE
            )
            self.assertEqual(POWER_ZONE_LIMITS, settings.power_limits, zones)

    def test_zone_models_with_fewer_zones_keep_their_own_limits(self):
        settings = ZoneSettings.from_sport_settings(
            [{"types": ["Ride"], "ftp": 200, "power_zones": [55, 75, 90, 105, 999]}],
            Sport.RIDE,
        )
        self.assertEqual((55, 75, 90, 105), settings.power_limits)
        self.assertEqual(4, settings.power_zone(100))
        # Above the last limit is the top zone of this model, not Z7.
        self.assertEqual(5, settings.power_zone(130))
        self.assertEqual(5, settings.absolute_zone("W", 260))

    def test_indoor_workouts_use_the_indoor_ftp(self):
        setting = {"types": ["Ride", "VirtualRide"], "ftp": 250, "indoor_ftp": 200}
        for environment, ftp in (
            (Environment.OUTDOOR, 250),
            (Environment.UNKNOWN, 250),
            (Environment.INDOOR, 200),
            (Environment.VIRTUAL, 200),
        ):
            settings = ZoneSettings.from_sport_settings(
                [setting], Sport.RIDE, environment
            )
            self.assertEqual(ftp, settings.ftp, environment)
        no_indoor = ZoneSettings.from_sport_settings(
            [{"types": ["Ride"], "ftp": 250}], Sport.RIDE, Environment.INDOOR
        )
        self.assertEqual(250, no_indoor.ftp)

    def test_heart_rate_zones_need_a_threshold(self):
        settings = ZoneSettings.from_sport_settings(
            [{"types": ["Run"], "hr_zones": [100, 120, 140, 160, 175, 190, 200]}],
            Sport.RUN,
        )
        self.assertEqual(HR_ZONE_LIMITS, settings.hr_limits)

    def test_malformed_sport_settings_are_ignored(self):
        for value in (None, "x", [None, 3, {"types": "Ride"}], {"types": ["Ride"]}):
            self.assertEqual(
                ZoneSettings(), ZoneSettings.from_sport_settings(value, Sport.RIDE)
            )

    def test_absolute_zone_needs_the_matching_threshold(self):
        ride = ZoneSettings.from_sport_settings([RIDE], Sport.RIDE)
        self.assertEqual(3, ride.absolute_zone("W", 200))
        self.assertEqual(4, ride.absolute_zone("bpm", 150))
        self.assertIsNone(ride.absolute_zone("pace", 200))
        self.assertIsNone(ZoneSettings().absolute_zone("W", 200))
