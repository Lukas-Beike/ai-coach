import unittest

from backend.activities.workout_load import (
    AthleteThresholds,
    estimate_workout,
    zone_band,
)
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import Sport
from backend.planning.planned_unit_load import estimate_planned_unit

SOURCES = {"ftp": "Intervals.icu", "lthr": "Garmin", "threshold_pace": "Intervals.icu"}
FULL = AthleteThresholds(
    ZoneSettings(ftp=250, lthr=170, max_hr=190),
    threshold_speed_mps=1000 / 270,
    sources=SOURCES,
)
NONE = AthleteThresholds()
INTERVALS = "5x\n- 4m 105%\n- 3m 60%\n"


class RideTests(unittest.TestCase):
    def test_repeats_percent_bands_and_load(self):
        result = estimate_workout("- 10m 55%\n\n" + INTERVALS, Sport.RIDE, FULL)
        self.assertEqual(2700, result.duration_s)
        self.assertEqual(
            {"low": 1500, "moderate": 1200, "high": 0}, result.band_seconds
        )
        self.assertAlmostEqual(0.88, result.intensity_factor, places=2)
        self.assertAlmostEqual(58.3, result.load, places=1)
        self.assertEqual("normalized_power_over_ftp", result.load_basis)
        self.assertEqual("derived", result.source)
        self.assertEqual({"ftp": "Intervals.icu"}, result.threshold_sources)

    def test_zone_and_range_targets_need_no_threshold(self):
        result = estimate_workout("- 30m Z2\n- 10m 90-100%\n", Sport.RIDE, NONE)
        self.assertEqual({"low": 1800, "moderate": 600, "high": 0}, result.band_seconds)
        self.assertEqual(0.95, result.steps[1].intensity)
        self.assertIsNotNone(result.load)

    def test_absolute_watts_need_ftp(self):
        known = estimate_workout("- 1h 200w\n", Sport.RIDE, FULL)
        self.assertAlmostEqual(0.8, known.steps[0].intensity)
        self.assertAlmostEqual(64.0, known.load)
        unknown = estimate_workout("- 1h 200w\n", Sport.RIDE, NONE)
        self.assertEqual(3600, unknown.duration_s)
        self.assertIsNone(unknown.load)
        self.assertIsNone(unknown.band_seconds)
        self.assertEqual(("missing_ftp",), unknown.unknown)

    def test_one_unknown_step_keeps_duration_but_not_load(self):
        result = estimate_workout("- 20m 55%\n- 10m 250w\n", Sport.RIDE, NONE)
        self.assertEqual(1800, result.duration_s)
        self.assertIsNone(result.load)
        self.assertIsNone(result.intensity_factor)


class RunTests(unittest.TestCase):
    def test_pace_percent_and_distance_derived_from_threshold_pace(self):
        result = estimate_workout("- 10km 90% Pace\n", Sport.RUN, FULL)
        speed = 0.9 * 1000 / 270
        self.assertAlmostEqual(10000 / speed, result.duration_s)
        self.assertEqual(10000, result.distance_m)
        self.assertEqual("relative_pace_speed", result.load_basis)
        self.assertAlmostEqual(0.9, result.intensity_factor)

    def test_distance_step_without_threshold_pace_is_unknown(self):
        result = estimate_workout("- 10km Z2 Pace\n", Sport.RUN, NONE)
        self.assertIsNone(result.duration_s)
        self.assertIsNone(result.load)
        self.assertEqual(10000, result.distance_m)
        self.assertEqual(("missing_pace_for_distance_step",), result.unknown)

    def test_absolute_pace_gives_distance_and_intensity(self):
        result = estimate_workout("- 10m 4:30/km Pace\n", Sport.RUN, FULL)
        self.assertAlmostEqual(1000 / 270 * 600, result.distance_m)
        self.assertAlmostEqual(1.0, result.steps[0].intensity)
        without = estimate_workout("- 10m 4:30/km Pace\n", Sport.RUN, NONE)
        self.assertIsNone(without.steps[0].intensity)
        self.assertAlmostEqual(1000 / 270 * 600, without.distance_m)
        self.assertEqual(("missing_threshold_pace",), without.unknown)

    def test_heart_rate_targets(self):
        lthr = estimate_workout("- 20m 75-80% LTHR\n", Sport.RUN, FULL)
        self.assertAlmostEqual(0.775, lthr.steps[0].intensity)
        self.assertEqual({"lthr": "Garmin"}, lthr.threshold_sources)
        bpm = estimate_workout("- 20m 150-160bpm\n", Sport.RUN, FULL)
        self.assertAlmostEqual(155 / 170, bpm.steps[0].intensity)

    def test_percent_of_max_hr_needs_max_hr(self):
        missing = estimate_workout("- 20m 80% HR\n", Sport.RUN, AthleteThresholds())
        self.assertEqual(("missing_max_hr",), missing.unknown)
        assumed = AthleteThresholds(ZoneSettings(max_hr=190))
        step = estimate_workout("- 20m 80% HR\n", Sport.RUN, assumed).steps[0]
        self.assertEqual("percent_of_max_hr_assumed_lthr_share", step.basis)
        exact = estimate_workout("- 20m 80% HR\n", Sport.RUN, FULL).steps[0]
        self.assertAlmostEqual(0.8 * 190 / 170, exact.intensity)

    def test_ramp_uses_the_mean_of_both_ends(self):
        step = estimate_workout("- 10m ramp 60-80%\n", Sport.RIDE, NONE).steps[0]
        self.assertAlmostEqual(0.7, step.intensity)
        pace = estimate_workout("- 10m ramp 60-80% Pace\n", Sport.RUN, NONE).steps[0]
        self.assertAlmostEqual(0.7, pace.intensity)

    def test_bare_run_target_is_ambiguous_but_watts_are_not(self):
        for text in ("- 40m Z2\n", "- 10m 75%\n"):
            result = estimate_workout(text, Sport.RUN, FULL)
            self.assertEqual(("ambiguous_run_target",), result.unknown)
            self.assertIsNone(result.load)
        watts = estimate_workout("- 10m 200w\n", Sport.RUN, FULL)
        self.assertEqual((), watts.unknown)
        ftp = estimate_workout("- 20m 85-95% FTP\n", Sport.RUN, FULL)
        self.assertEqual((), ftp.unknown)
        self.assertAlmostEqual(0.9, ftp.steps[0].intensity)

    def test_zero_pace_is_unknown(self):
        result = estimate_workout("- 10m 0:00/km Pace\n", Sport.RUN, FULL)
        self.assertEqual(("invalid_pace",), result.unknown)

    def test_zones_beyond_the_limits_are_unknown(self):
        for text in ("- 20m Z10\n", "- 20m Z1-Z10\n"):
            result = estimate_workout(text, Sport.RIDE, FULL)
            self.assertEqual(("zone_out_of_range",), result.unknown)

    def test_mixed_steps_use_quadratic_mean(self):
        result = estimate_workout("- 30m Z2 Pace\n- 30m 80% LTHR\n", Sport.RUN, FULL)
        self.assertEqual("mixed_step_intensity", result.load_basis)
        self.assertIsNotNone(result.load)


class UnknownTests(unittest.TestCase):
    def test_unparseable_text_stays_unknown(self):
        for text in ("easy jog 45 min", "- 10m", "- 10m hard", ""):
            with self.subTest(text=text):
                result = estimate_workout(
                    text, Sport.RUN, FULL, fallback_duration_s=2700
                )
                self.assertEqual(2700, result.duration_s)
                self.assertIsNone(result.load)
                self.assertIsNone(result.band_seconds)
                self.assertEqual((), result.steps)
                self.assertEqual(1, len(result.unknown))

    def test_strength_has_no_step_targets(self):
        result = estimate_workout("- 10m 80%\n", Sport.STRENGTH, FULL)
        self.assertEqual(("sport_without_step_targets",), result.unknown)
        self.assertIsNone(result.load)

    def test_zone_above_configured_limits_is_unknown(self):
        zones = ZoneSettings(power_limits=(55, 75, 90))
        result = estimate_workout("- 10m Z6\n", Sport.RIDE, AthleteThresholds(zones))
        self.assertEqual(("zone_out_of_range",), result.unknown)

    def test_band_depends_on_zone_count(self):
        self.assertEqual(
            ["low", "moderate", "moderate", "high"],
            [zone_band(zone, 7) for zone in (2, 3, 4, 5)],
        )
        self.assertEqual("high", zone_band(4, 5))


class PlannedUnitTests(unittest.TestCase):
    def test_mixed_run_and_ride_week(self):
        units = [
            {"sport": "Ride", "description": "- 10m 55%\n\n" + INTERVALS},
            {"sport": "Run", "description": "- 10km 90% Pace\n"},
            {"sport": "WeightTraining", "planned_duration_s": 3000},
            {"sport": "Run", "description": "lockerer Lauf", "duration_minutes": 40},
        ]
        results = [estimate_planned_unit(unit, FULL) for unit in units]
        self.assertEqual(["ride", "run", "strength", "run"], [r.sport for r in results])
        self.assertIsNotNone(results[0].load)
        self.assertIsNotNone(results[1].load)
        self.assertIsNone(results[2].load)
        self.assertEqual(3000, results[2].duration_s)
        self.assertIsNone(results[3].load)
        self.assertEqual(2400, results[3].duration_s)


if __name__ == "__main__":
    unittest.main()
