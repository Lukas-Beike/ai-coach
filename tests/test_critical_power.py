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
    """Three separate sessions, one exact model effort each."""
    return [
        _ride(name, [(t, cp + w_prime / t, 0.0)], **kwargs)
        for name, t in (("short", 180), ("mid", 420), ("long", 720))
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
            [180, 420, 720],
            [row["left_out_seconds"] for row in fit["sensitivity"]["leave_one_out"]],
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
            ("critical-power-speed", 1, "M4", "experimental", "unknown"),
            (
                result["method"],
                result["method_version"],
                result["card"],
                result["status"],
                result["sensor"],
            ),
        )
        self.assertIn("keine FTP", result["scope"])


class StopRuleTests(unittest.TestCase):
    def assertWithheld(self, fit, reason):
        self.assertEqual("withheld", fit["status"])
        self.assertIn(reason, fit["reason"])
        self.assertNotIn("cp_watts", fit)
        self.assertNotIn("sensitivity", fit)

    def test_two_efforts_give_no_estimate(self):
        fit = _fit(_model_rides()[:2])
        self.assertEqual("insufficient_data", fit["status"])
        self.assertEqual(2, len(fit["efforts"]))
        self.assertNotIn("cp_watts", fit)

    def test_residual_above_three_percent_is_withheld(self):
        records = _model_rides()
        records[1]["power_profile"]["duration_curve"][0]["watts"] = 315.0
        self.assertWithheld(_fit(records), "3 %")

    def test_non_positive_parameter_is_withheld(self):
        records = [
            _ride(name, [(t, 200.0, 0.0)])
            for name, t in (("a", 180), ("b", 420), ("c", 720))
        ]
        self.assertWithheld(_fit(records), "Nicht positiver")

    def test_implausible_parameters_are_withheld(self):
        self.assertWithheld(_fit(_model_rides(cp=700.0)), "Plausibilitätsbereich")
        self.assertWithheld(
            _fit(_model_rides(w_prime=60000.0)), "Plausibilitätsbereich"
        )

    def test_leave_one_out_non_positive_parameter_is_withheld(self):
        # Within 3 % of the full fit, but the 420/720 s pair alone gives W′ < 0.
        records = [
            _ride("a", [(180, 300.0, 0.0)]),
            _ride("b", [(420, 257.0, 0.0)]),
            _ride("c", [(720, 257.0, 0.0)]),
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
            "one", [(180, 350.0, 2940.0), (420, 300.0, 0.0), (720, 275.0, 4920.0)]
        )
        self.assertEqual(3, len(_fit([apart])["efforts"]))
        close = _ride(
            "one", [(180, 350.0, 2941.0), (420, 300.0, 0.0), (720, 275.0, 4920.0)]
        )
        self.assertEqual(2, len(_fit([close])["efforts"]))

    def test_lower_effort_from_another_session_replaces_an_overlap(self):
        records = [
            _ride("one", [(180, 400.0, 0.0), (720, 275.0, 0.0)]),
            _ride("two", [(180, 350.0, 0.0)]),
            _ride("three", [(420, 292.857142857, 0.0)]),
        ]
        fit = _fit(records)
        self.assertEqual(
            ["two", "three", "one"], [e["activity_id"] for e in fit["efforts"]]
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


if __name__ == "__main__":
    unittest.main()
