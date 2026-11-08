import unittest
from datetime import date, timedelta

from backend.performance.critical_power import critical_power_speed, fit_line

TODAY = date(2026, 11, 2)


def _ride(activity_id, points, *, environment="outdoor", days_ago=1):
    return {
        "activity_id": activity_id,
        "date": (TODAY - timedelta(days=days_ago)).isoformat(),
        "sport": "ride",
        "environment": environment,
        "source": "Intervals.icu original watts stream",
        "power_profile": {
            "duration_curve": [
                {"duration_seconds": d, "watts": w, "start_seconds": s}
                for d, w, s in points
            ]
        },
    }


def _run(activity_id, points, *, environment="outdoor", days_ago=1):
    return {
        "activity_id": activity_id,
        "date": (TODAY - timedelta(days=days_ago)).isoformat(),
        "sport": "run",
        "environment": environment,
        "running_profile": {
            "speed": [
                {"duration_seconds": d, "speed_mps": v, "start_seconds": s}
                for d, v, s in points
            ]
        },
    }


def _model_rides(cp=250.0, w_prime=18000.0, **kwargs):
    """Four separate sessions, one exact model effort each (3/7/12/20 min)."""
    return [
        _ride(name, [(t, cp + w_prime / t, 0.0)], **kwargs)
        for name, t in (
            ("short", 180),
            ("mid", 420),
            ("long", 720),
            ("longest", 1200),
        )
    ]


def _fit(records, sport="ride", environment="outdoor"):
    result = critical_power_speed(records, TODAY, input_fingerprint="fp")
    return next(
        fit
        for fit in result["fits"]
        if fit["sport"] == sport and fit["environment"] == environment
    )


class ReferenceCaseTests(unittest.TestCase):
    def test_card_reference_powers_recover_cp_and_w_prime(self):
        powers = [250 + 18000 / t for t in (180, 420, 720)]
        self.assertEqual(350, powers[0])
        self.assertAlmostEqual(292.857142857, powers[1], places=9)
        self.assertEqual(275, powers[2])
        # Card M4 v4: the 20-min reference point is 265 W.
        self.assertEqual(265, 250 + 18000 / 1200)
        slope, intercept = fit_line(
            [180, 420, 720],
            [p * t for p, t in zip(powers, (180, 420, 720), strict=True)],
        )
        self.assertAlmostEqual(250, slope, places=9)
        self.assertAlmostEqual(18000, intercept, places=6)
        fit = _fit(_model_rides())
        self.assertEqual("ok", fit["status"])
        self.assertEqual((250.0, 18000), (fit["cp_watts"], fit["w_prime_joules"]))
        self.assertEqual(
            {"cp_watts": 250.0, "w_prime_joules": 18000},
            fit["sensitivity"]["inverse_time"],
        )
        self.assertEqual(
            [180, 420, 720, 1200],
            [row["left_out_seconds"] for row in fit["sensitivity"]["leave_one_out"]],
        )
        self.assertEqual(
            {"duration_seconds": [180, 420, 720], "cp_watts": 250.0},
            {
                key: fit["sensitivity"]["three_point"][key]
                for key in ("duration_seconds", "cp_watts")
            },
        )
        self.assertTrue(all(row["relative"] == 0 for row in fit["residuals"]))
        self.assertEqual(1, fit["data_age_days"])

    def test_card_reference_distances_recover_cs_and_d_prime(self):
        distances = [4 * t + 200 for t in (180, 420, 720)]
        self.assertEqual([920, 1880, 3080], distances)
        records = [
            _run(f"r{t}", [(t, (4 * t + 200) / t, 0.0)]) for t in (180, 420, 720)
        ]
        fit = _fit(records, "run")
        self.assertEqual("ok", fit["status"])
        self.assertEqual((4.0, 200.0), (fit["cs_mps"], fit["d_prime_meters"]))

    def test_result_is_always_an_experimental_model_estimate(self):
        result = critical_power_speed(_model_rides(), TODAY, input_fingerprint="fp")
        self.assertEqual(
            ("critical-power-speed", 2, "M4", "experimental", "unknown"),
            (
                result["method"],
                result["method_version"],
                result["card"],
                result["status"],
                result["sensor"],
            ),
        )
        self.assertIn("keine FTP", result["scope"])
        self.assertIn("weniger verlässlich", result["scope"])

    def test_card_worked_example_four_points_lower_cp_than_three(self):
        # Card M4 v4 worked example: 330/290/275/262 W at 3/7/12/20 min give
        # CP 249.7 W and W′ 16,096 J; the 3/7/12 fit gives CP 256.6 W, 13,515 J.
        records = [
            _ride(f"w{t}", [(t, watts, 0.0)])
            for t, watts in ((180, 330.0), (420, 290.0), (720, 275.0), (1200, 262.0))
        ]
        fit = _fit(records)
        self.assertEqual("ok", fit["status"])
        self.assertEqual((249.7, 16096), (fit["cp_watts"], fit["w_prime_joules"]))
        three = fit["sensitivity"]["three_point"]
        self.assertEqual((256.6, 13515), (three["cp_watts"], three["w_prime_joules"]))

    def test_w_prime_and_d_prime_are_marked_less_reliable(self):
        result = critical_power_speed(_model_rides(), TODAY, input_fingerprint="fp")
        self.assertEqual(
            {"low"}, {fit["intercept_reliability"] for fit in result["fits"]}
        )

    def test_running_keeps_three_efforts_without_a_three_point_sensitivity(self):
        records = [
            _run(f"r{t}", [(t, (4 * t + 200) / t, 0.0)]) for t in (180, 420, 720)
        ]
        fit = _fit(records, "run")
        self.assertEqual(
            [180, 420, 720], [e["duration_seconds"] for e in fit["efforts"]]
        )
        self.assertNotIn("three_point", fit["sensitivity"])

    def test_cycling_fits_report_an_unchecked_power_source(self):
        # Card M4 v3: Garmin and Wahoo mark no estimated power, so every ride
        # fit says its power source is unchecked; running fits carry no field.
        result = critical_power_speed(_model_rides(), TODAY, input_fingerprint="fp")
        sources = {
            (fit["sport"], fit["environment"]): fit.get("power_source")
            for fit in result["fits"]
        }
        self.assertEqual(
            {
                ("ride", "outdoor"): "unchecked",
                ("ride", "indoor"): "unchecked",
                ("run", "outdoor"): None,
            },
            sources,
        )


class StopRuleTests(unittest.TestCase):
    def assertWithheld(self, fit, reason):
        self.assertEqual("withheld", fit["status"])
        self.assertIn(reason, fit["reason"])
        self.assertNotIn("cp_watts", fit)
        self.assertNotIn("sensitivity", fit)

    def test_without_a_twenty_minute_effort_there_is_no_cycling_estimate(self):
        fit = _fit(_model_rides()[:3])
        self.assertEqual("insufficient_data", fit["status"])
        self.assertEqual(3, len(fit["efforts"]))
        self.assertIn("3, 7, 12, 20", fit["reason"])
        self.assertNotIn("cp_watts", fit)

    def test_residual_above_three_percent_is_withheld(self):
        records = _model_rides()
        records[1]["power_profile"]["duration_curve"][0]["watts"] = 315.0
        self.assertWithheld(_fit(records), "3 %")

    def test_non_positive_parameter_is_withheld(self):
        records = [
            _ride(name, [(t, 200.0, 0.0)])
            for name, t in (("a", 180), ("b", 420), ("c", 720), ("d", 1200))
        ]
        self.assertWithheld(_fit(records), "Nicht positiver")

    def test_implausible_parameters_are_withheld(self):
        self.assertWithheld(_fit(_model_rides(cp=700.0)), "Plausibilitätsbereich")
        self.assertWithheld(
            _fit(_model_rides(w_prime=60000.0)), "Plausibilitätsbereich"
        )

    def test_leave_one_out_non_positive_parameter_is_withheld(self):
        # Within 3 % of the full fit, but a three-effort fit gives W′ <= 0.
        records = [
            _ride("a", [(180, 262.0, 0.0)]),
            _ride("b", [(420, 255.0, 0.0)]),
            _ride("c", [(720, 257.0, 0.0)]),
            _ride("d", [(1200, 256.0, 0.0)]),
        ]
        fit = _fit(records)
        self.assertWithheld(fit, "Ohne eine Belastung")


class EffortSelectionTests(unittest.TestCase):
    def test_overlapping_bests_of_one_session_count_once(self):
        session = _ride(
            "one", [(180, 350.0, 0.0), (420, 292.857, 0.0), (720, 275.0, 0.0)]
        )
        fit = _fit([session])
        self.assertEqual("insufficient_data", fit["status"])
        self.assertEqual(1, len(fit["efforts"]))

    def test_efforts_of_one_session_need_thirty_minutes_between(self):
        apart = _ride(
            "one",
            [
                (180, 350.0, 2940.0),
                (420, 300.0, 0.0),
                (720, 275.0, 4920.0),
                (1200, 265.0, 7440.0),
            ],
        )
        self.assertEqual(4, len(_fit([apart])["efforts"]))
        close = _ride(
            "one",
            [
                (180, 350.0, 2941.0),
                (420, 300.0, 0.0),
                (720, 275.0, 4920.0),
                (1200, 265.0, 7440.0),
            ],
        )
        self.assertEqual(3, len(_fit([close])["efforts"]))

    def test_lower_effort_from_another_session_replaces_an_overlap(self):
        records = [
            _ride("one", [(180, 400.0, 0.0), (720, 275.0, 0.0)]),
            _ride("two", [(180, 350.0, 0.0)]),
            _ride("three", [(420, 292.857142857, 0.0)]),
            _ride("four", [(1200, 265.0, 0.0)]),
        ]
        fit = _fit(records)
        self.assertEqual(
            ["two", "three", "one", "four"],
            [e["activity_id"] for e in fit["efforts"]],
        )
        self.assertEqual(250.0, fit["cp_watts"])

    def test_indoor_rides_and_indoor_runs_stay_out_of_outdoor_fits(self):
        indoor = _model_rides(environment="indoor")
        self.assertEqual("insufficient_data", _fit(indoor)["status"])
        self.assertEqual("ok", _fit(indoor, environment="indoor")["status"])
        runs = [
            _run(f"r{t}", [(t, (4 * t + 200) / t, 0.0)], environment="indoor")
            for t in (180, 420, 720)
        ]
        self.assertEqual("insufficient_data", _fit(runs, "run")["status"])

    def test_data_age_is_the_oldest_effort(self):
        records = _model_rides()
        records[0]["date"] = (TODAY - timedelta(days=20)).isoformat()
        self.assertEqual(20, _fit(records)["data_age_days"])


class EffortContextTests(unittest.TestCase):
    def test_race_efforts_are_flagged_and_others_are_not(self):
        rides = _model_rides()
        rides[0]["effort_context"] = "race"

        efforts = _fit(rides)["efforts"]

        self.assertEqual(
            [
                ("short", "race"),
                ("mid", "training"),
                ("long", "training"),
                ("longest", "training"),
            ],
            [(e["activity_id"], e["effort_context"]) for e in efforts],
        )


if __name__ == "__main__":
    unittest.main()
