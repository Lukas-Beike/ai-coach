"""Pace at heart rate: steady flat runs only; unknown stays unknown."""

import unittest
from datetime import date

from backend.performance.pace_at_hr import (
    grade_adjusted,
    output_at_heart_rate,
    pace_at_heart_rate,
    pace_at_heart_rate_trend,
    power_at_heart_rate,
    session_comparison,
)
from backend.planning.block_review import _performance

SECONDS = 2400


def _run(speed=3.0, hr=145, grade=None, altitude=None, environment="outdoor", **extra):
    times = list(range(SECONDS))
    streams = {
        "time": times,
        "velocity_smooth": [speed] * SECONDS,
        "heartrate": [hr] * SECONDS,
        "distance": [speed * t for t in times],
        "moving": [True] * SECONDS,
    }
    if grade is not None:
        streams["grade_smooth"] = [grade] * SECONDS
    if altitude is not None:
        streams["altitude"] = [altitude(t) for t in times]
    return {
        "sport": "run",
        "environment": environment,
        "trail": False,
        "streams": streams,
        **extra,
    }


def _record(day, profile, environment="outdoor"):
    return {
        "date": day,
        "sport": "run",
        "environment": environment,
        "activity_id": day,
        "pace_at_hr_profile": profile,
    }


class SessionProfileTests(unittest.TestCase):
    def test_steady_flat_run_gives_pace_in_band(self):
        profile = pace_at_heart_rate(_run(grade=0.0))
        self.assertEqual(profile["status"], "ok")
        self.assertTrue(profile["grade_adjusted"])
        self.assertIn("145", profile["bins"])

    def test_hilly_run_is_filtered(self):
        profile = pace_at_heart_rate(_run(grade=8.0))
        self.assertEqual(profile["status"], "insufficient_data")
        self.assertEqual(profile["bins"], {})

    def test_hilly_run_from_altitude_is_filtered(self):
        profile = pace_at_heart_rate(_run(altitude=lambda t: 0.5 * 3.0 * t))
        self.assertEqual(profile["status"], "insufficient_data")

    def test_flat_altitude_gives_value(self):
        profile = pace_at_heart_rate(_run(altitude=lambda t: 100.0))
        self.assertEqual(profile["status"], "ok")

    def test_run_without_heart_rate_is_unknown(self):
        activity = _run(grade=0.0)
        del activity["streams"]["heartrate"]
        self.assertEqual(pace_at_heart_rate(activity)["status"], "insufficient_data")

    def test_outdoor_run_without_terrain_is_unknown_but_indoor_is_flat(self):
        self.assertEqual(pace_at_heart_rate(_run())["status"], "insufficient_data")
        self.assertEqual(pace_at_heart_rate(_run(environment="indoor"))["status"], "ok")
        # A virtual run has no terrain either, so it is flat like a treadmill run.
        self.assertEqual(
            pace_at_heart_rate(_run(environment="virtual"))["status"], "ok"
        )

    def test_indoor_and_virtual_runs_ignore_course_altitude(self):
        for environment in ("indoor", "virtual"):
            with self.subTest(environment=environment):
                result = pace_at_heart_rate(
                    _run(environment=environment, altitude=lambda t: 0.5 * 3.0 * t)
                )
                self.assertEqual(result["status"], "ok")
                self.assertFalse(result["grade_adjusted"])

    def test_trail_and_ride_give_no_value(self):
        self.assertEqual(
            pace_at_heart_rate(_run(grade=0.0, trail=True))["status"],
            "insufficient_data",
        )
        self.assertEqual(
            pace_at_heart_rate(_run(grade=0.0, sport="ride"))["status"],
            "insufficient_data",
        )

    def test_grade_adjustment_is_neutral_on_level_ground(self):
        self.assertAlmostEqual(grade_adjusted(3.0, 0.0), 3.0)
        self.assertGreater(grade_adjusted(3.0, 2.0), 3.0)


class TrendTests(unittest.TestCase):
    def test_trend_compares_halves_in_one_band(self):
        records = [
            _record("2026-09-01", pace_at_heart_rate(_run(speed=3.0, grade=0.0))),
            _record("2026-09-20", pace_at_heart_rate(_run(speed=3.2, grade=0.0))),
        ]
        trend = pace_at_heart_rate_trend(
            records, date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 27)
        )["run"]["outdoor"]
        self.assertEqual(trend["status"], "ok")
        self.assertEqual(trend["heart_rate_band_bpm"], [140, 149])
        self.assertEqual(trend["earlier"]["pace_s_per_km"], 333.3)
        self.assertEqual(trend["later"]["pace_s_per_km"], 312.5)
        self.assertEqual(trend["change_s_per_km"], -20.8)

    def test_band_is_chosen_so_both_halves_have_sessions(self):
        records = [
            _record(
                "2026-09-01", pace_at_heart_rate(_run(speed=3.0, hr=142, grade=0.0))
            ),
            _record(
                "2026-09-02", pace_at_heart_rate(_run(speed=3.0, hr=152, grade=0.0))
            ),
            _record(
                "2026-09-20", pace_at_heart_rate(_run(speed=3.2, hr=152, grade=0.0))
            ),
        ]
        trend = pace_at_heart_rate_trend(
            records, date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 27)
        )["run"]["outdoor"]
        self.assertEqual(trend["heart_rate_band_bpm"], [145, 154])
        self.assertIsNotNone(trend["change_s_per_km"])

    def test_sessions_outside_the_block_and_one_sided_blocks_are_not_a_trend(self):
        outside = [
            _record("2026-07-01", pace_at_heart_rate(_run(grade=0.0))),
            _record("2026-07-02", pace_at_heart_rate(_run(grade=0.0))),
            _record("2026-09-20", pace_at_heart_rate(_run(grade=0.0))),
        ]
        one_sided = [
            _record("2026-09-20", pace_at_heart_rate(_run(grade=0.0))),
            _record("2026-09-21", pace_at_heart_rate(_run(grade=0.0))),
        ]
        for records in (outside, one_sided):
            trend = pace_at_heart_rate_trend(
                records, date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 27)
            )["run"]["outdoor"]
            self.assertEqual(trend["status"], "insufficient_data")
            self.assertIsNone(trend["change_s_per_km"])
        self.assertEqual(
            _performance({"pace_at_heart_rate": {"run": {"outdoor": trend}}})[
                "not_covered"
            ],
            ["pace_at_heart_rate"],
        )

    def test_single_session_or_no_coverage_is_not_a_trend(self):
        one = [_record("2026-09-01", pace_at_heart_rate(_run(grade=0.0)))]
        unknown = [_record("2026-09-01", {}), _record("2026-09-20", {})]
        for records in (one, unknown):
            trend = pace_at_heart_rate_trend(
                records, date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 27)
            )["run"]["outdoor"]
            self.assertEqual(trend["status"], "insufficient_data")
            self.assertIsNone(trend["change_s_per_km"])

    def test_block_review_marks_coverage(self):
        records = [
            _record("2026-09-01", pace_at_heart_rate(_run(speed=3.0, grade=0.0))),
            _record("2026-09-20", pace_at_heart_rate(_run(speed=3.2, grade=0.0))),
        ]
        covered = pace_at_heart_rate_trend(
            records, date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 27)
        )
        self.assertEqual(
            _performance({"pace_at_heart_rate": covered})["not_covered"], []
        )
        missing = _performance(
            {"pace_at_heart_rate": {"status": "outside_curve_window"}}
        )
        self.assertEqual(missing["not_covered"], ["pace_at_heart_rate"])
        self.assertEqual(_performance({})["not_covered"], ["pace_at_heart_rate"])


def _peer(day, pace_speed=3.0, hr=145, environment="outdoor", **extra):
    profile = pace_at_heart_rate(
        _run(speed=pace_speed, hr=hr, grade=0.0, environment=environment, **extra)
    )
    return _record(day, profile, environment)


class SessionComparisonTests(unittest.TestCase):
    def _records(self, count, own=None):
        own = own or _peer("2026-11-02", 3.1)
        peers = [_peer(f"2026-10-{10 + index:02d}") for index in range(count)]
        return [own, *peers]

    def test_compares_with_the_median_of_comparable_runs(self):
        result = session_comparison(self._records(3), "2026-11-02")
        self.assertEqual("ok", result["status"])
        self.assertEqual(3, result["comparable"]["count"])
        self.assertEqual([140, 149], result["heart_rate_band_bpm"])
        self.assertEqual(333.3, result["comparable"]["median_pace_s_per_km"])
        self.assertEqual(-10.7, result["difference_s_per_km"])
        self.assertEqual(1, len(result["sources"]))
        self.assertIn("positive difference = slower", result["direction"])

    def test_too_few_comparable_runs_is_not_covered_with_the_count(self):
        result = session_comparison(self._records(2), "2026-11-02")
        self.assertEqual("not_covered", result["status"])
        self.assertEqual(2, result["comparable"]["count"])
        self.assertNotIn("difference_s_per_km", result)

    def test_runs_older_than_42_days_and_other_environments_do_not_count(self):
        old = _peer("2026-09-01")
        indoor = _peer("2026-10-20", environment="indoor")
        result = session_comparison([*self._records(2), old, indoor], "2026-11-02")
        self.assertEqual(2, result["comparable"]["count"])

    def test_run_without_heart_rate_is_not_covered_with_the_reason(self):
        no_hr = _record(
            "2026-11-02",
            pace_at_heart_rate(
                {**_run(grade=0.0), "streams": {"time": list(range(SECONDS))}}
            ),
        )
        result = session_comparison([no_hr, *self._records(3)[1:]], "2026-11-02")
        self.assertEqual("not_covered", result["status"])
        self.assertIn("Puls", result["reason"])

    def test_unknown_session_is_not_covered(self):
        self.assertEqual(
            "not_covered", session_comparison(self._records(3), "missing")["status"]
        )


def _ride(watts=(200,), hr=131):
    times = list(range(SECONDS))
    return {
        "sport": "ride",
        "streams": {
            "time": times,
            "watts": [watts[t % len(watts)] for t in times],
            "heartrate": [hr] * SECONDS,
            "moving": [True] * SECONDS,
        },
    }


def _ride_record(day, ride):
    return {
        "date": day,
        "sport": "ride",
        "power_at_hr_profile": power_at_heart_rate(ride),
    }


class OutputAtHeartRateTests(unittest.TestCase):
    """LT1 pace and power from own steady sessions (#2427): fixtures only."""

    TODAY = date(2026, 11, 13)

    def test_ride_profile_pairs_heart_rate_with_the_power_of_the_last_minute(self):
        # 300 W and 100 W alternate every second: the minute's mean is 200 W.
        profile = power_at_heart_rate(_ride(watts=(300, 100)))
        part = profile["bins"]["130"]
        self.assertEqual("ok", profile["status"])
        self.assertEqual(SECONDS - 600 - 1, part["seconds"])
        self.assertAlmostEqual(200.0, part["work_j"] / part["seconds"], delta=0.5)
        # Coasting samples (own power zero) do not count.
        coasting = power_at_heart_rate(_ride(watts=(300, 0)))["bins"]["130"]
        self.assertAlmostEqual(coasting["seconds"], part["seconds"] / 2, delta=1)

    def test_a_run_or_a_ride_without_power_gives_no_ride_profile(self):
        self.assertEqual("insufficient_data", power_at_heart_rate(_run())["status"])
        short = _ride()
        short["streams"] = {**short["streams"], "watts": []}
        self.assertEqual("insufficient_data", power_at_heart_rate(short)["status"])

    def test_median_of_the_sessions_in_the_band_nearest_to_the_heart_rate(self):
        runs = [_peer(f"2026-11-0{day}", speed, hr=128)
                for day, speed in ((1, 3.0), (2, 3.2), (3, 2.9))]  # fmt: skip
        rides = [_ride_record(f"2026-11-0{day}", _ride(watts=(watts,)))
                 for day, watts in ((1, 190), (2, 200), (3, 230))]  # fmt: skip
        records = [*runs, *rides]
        # 128 bpm reads the 125-134 band: median speed 3.0 m/s is 333.3 s/km.
        self.assertAlmostEqual(
            333.33, output_at_heart_rate(records, "run", 128, self.TODAY), places=2
        )
        self.assertEqual(200, output_at_heart_rate(records, "ride", 131, self.TODAY))
        # No time in the band around 145 bpm, and too few sessions: no value.
        self.assertIsNone(output_at_heart_rate(records, "run", 145, self.TODAY))
        self.assertIsNone(output_at_heart_rate(records[:2], "run", 128, self.TODAY))

    def test_outdoor_runs_first_indoor_runs_only_without_enough_outdoor_ones(self):
        indoor = [_peer(f"2026-11-0{day}", 2.5, hr=128, environment="indoor")
                  for day in (1, 2, 3)]  # fmt: skip
        outdoor = [_peer(f"2026-11-0{day}", 3.0, hr=128) for day in (4, 5, 6)]
        self.assertEqual(
            400, output_at_heart_rate(indoor + outdoor[:2], "run", 128, self.TODAY)
        )
        self.assertAlmostEqual(
            333.33,
            output_at_heart_rate(indoor + outdoor, "run", 128, self.TODAY),
            places=2,
        )

    def test_sessions_older_than_60_days_do_not_count(self):
        runs = [
            _peer(day, 3.0, hr=128)
            for day in ("2026-09-14", "2026-09-15", "2026-11-01")
        ]
        self.assertIsNone(output_at_heart_rate(runs, "run", 128, self.TODAY))
        runs[0]["date"] = "2026-11-02"
        self.assertIsNotNone(output_at_heart_rate(runs, "run", 128, self.TODAY))


if __name__ == "__main__":
    unittest.main()
