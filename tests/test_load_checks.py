"""Load-based plan notes: completed and planned load, spikes, weekly rise, unknown."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any, ClassVar

from backend.activities.workout_load import AthleteThresholds
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
)
from backend.planning import load_checks, plan_checks
from tests.canonical_domain_support import provenance, zone_configuration

TODAY = date(2026, 11, 2)


@dataclass
class Obs:
    kind: MetricKind
    sport: Sport
    value: Any


def inputs(*, present: bool = True, pace: bool = True) -> SimpleNamespace:
    """Current inputs whose source-policy provider winners are ``present`` or none."""
    observations = (
        Obs(MetricKind.FTP, Sport.RIDE, SimpleNamespace(value=250.0)),
        Obs(MetricKind.THRESHOLD_HR, Sport.RIDE, SimpleNamespace(value=165.0)),
        Obs(MetricKind.THRESHOLD_HR, Sport.RUN, SimpleNamespace(value=170.0)),
    )

    if pace:
        observations += (
            Obs(MetricKind.THRESHOLD_PACE, Sport.RUN, SimpleNamespace(value=4.0)),
        )
    return SimpleNamespace(zone_thresholds=observations if present else ())


def thresholds(*, pace: bool = True, ftp: bool = True) -> load_checks.LoadThresholds:
    return load_checks.LoadThresholds(
        {
            Sport.RUN: AthleteThresholds(
                zones=ZoneSettings(lthr=170.0),
                threshold_speed_mps=4.0 if pace else None,
            ),
            Sport.RIDE: AthleteThresholds(
                zones=ZoneSettings(ftp=250.0 if ftp else None, lthr=165.0)
            ),
        }
    )


def ride_done(day: str, **extra: Any) -> dict[str, Any]:
    return {
        "sport": "ride",
        "started_at_local": f"{day}T08:00:00",
        "moving_duration_s": 3600,
        **extra,
    }


def run_done(day: str, **extra: Any) -> dict[str, Any]:
    return {
        "sport": "run",
        "started_at_local": f"{day}T08:00:00",
        "moving_duration_s": 3600,
        **extra,
    }


def planned(local_id: str, day: str, sport: str, steps: str, **extra: Any):
    return {
        "local_id": local_id,
        "date": day,
        "sport": sport,
        "planned_duration_s": 3600,
        "name": "Session",
        "description": steps,
        **extra,
    }


def check(units, completed=(), thr=None, illness=""):
    return plan_checks.check_plan(
        today=TODAY,
        units=units,
        completed=list(completed),
        competitions=[],
        illness=illness,
        thresholds=thr if thr is not None else thresholds(),
    )


def only(findings, code):
    return [item for item in findings if item["code"] == code]


class CompletedLoadTests(unittest.TestCase):
    def load(self, row, sport, thr=None):
        return load_checks.completed_load(
            row, sport, (thr or thresholds()).for_sport(sport)
        )

    def test_ride_uses_normalized_power_over_ftp(self) -> None:
        result = self.load(ride_done("2026-10-30", normalized_power=200), Sport.RIDE)
        self.assertAlmostEqual(64.0, result.load)
        self.assertEqual("normalized_power_over_ftp", result.basis)
        self.assertTrue(result.precise)

    def test_ride_without_normalized_power_uses_average_power(self) -> None:
        result = self.load(ride_done("2026-10-30", avg_power=200), Sport.RIDE)
        self.assertEqual("average_power_over_ftp", result.basis)
        self.assertFalse(result.precise)

    def test_ride_without_power_falls_back_to_heart_rate(self) -> None:
        result = self.load(ride_done("2026-10-30", avg_hr=148.5), Sport.RIDE)
        self.assertEqual("heart_rate_over_lthr_fallback", result.basis)
        self.assertAlmostEqual(81.0, result.load)
        self.assertFalse(result.precise)

    def test_run_prefers_grade_adjusted_pace(self) -> None:
        row = run_done("2026-10-30", weighted_avg_speed_mps=3.2, avg_speed_mps=2.0)
        result = self.load(row, Sport.RUN)
        self.assertAlmostEqual(64.0, result.load)
        self.assertEqual("grade_adjusted_pace_over_threshold_pace", result.basis)
        self.assertTrue(result.precise)

    def test_run_uses_average_pace_then_heart_rate(self) -> None:
        pace = self.load(run_done("2026-10-30", avg_speed_mps=3.2), Sport.RUN)
        self.assertEqual("average_pace_over_threshold_pace", pace.basis)
        self.assertFalse(pace.precise)
        hr = self.load(run_done("2026-10-30", avg_hr=136), Sport.RUN)
        self.assertEqual("heart_rate_over_lthr_fallback", hr.basis)

    def test_missing_threshold_or_data_gives_no_load(self) -> None:
        row = run_done("2026-10-30", weighted_avg_speed_mps=3.2)
        self.assertIsNone(self.load(row, Sport.RUN, thresholds(pace=False)))
        self.assertIsNone(self.load(ride_done("2026-10-30"), Sport.RIDE))
        self.assertIsNone(
            self.load(
                ride_done("2026-10-30", normalized_power=200),
                Sport.RIDE,
                thresholds(ftp=False),
            )
        )


class ThresholdTests(unittest.TestCase):
    def test_fresh_sync_gives_sport_thresholds(self) -> None:
        result = load_checks.load_thresholds(inputs(), TODAY)
        self.assertIsNone(result.unavailable)
        self.assertEqual(250.0, result.for_sport(Sport.RIDE).zones.ftp)
        self.assertEqual(4.0, result.for_sport(Sport.RUN).threshold_speed_mps)

    def test_missing_pace_stays_unknown(self) -> None:
        result = load_checks.load_thresholds(inputs(pace=False), TODAY)
        self.assertIsNone(result.for_sport(Sport.RUN).threshold_speed_mps)

    def test_no_provider_threshold_is_unavailable(self) -> None:
        result = load_checks.load_thresholds(inputs(present=False), TODAY)
        self.assertEqual("missing_thresholds", result.unavailable)
        self.assertEqual({}, dict(result.by_sport))

    def test_a_garmin_winner_gives_thresholds_without_any_sync(self) -> None:
        garmin = SimpleNamespace(
            zone_thresholds=(
                Obs(MetricKind.THRESHOLD_HR, Sport.RUN, SimpleNamespace(value=172.0)),
            ),
        )
        result = load_checks.load_thresholds(garmin, TODAY)
        self.assertIsNone(result.unavailable)
        self.assertEqual(172.0, result.for_sport(Sport.RUN).zones.lthr)


class LocalThresholdPrecedenceTests(unittest.TestCase):
    """Locally confirmed zones win over the provider winners, as in the Coach context."""

    @staticmethod
    def local(metric: ZoneConfigurationMetric, **values: Any) -> Any:
        return zone_configuration(
            metric=metric,
            sport=values.pop("sport", Sport.RIDE),
            provenance=provenance(None, provider=None),
            limits=(100.0, 200.0, 300.0, 400.0)
            if metric is ZoneConfigurationMetric.POWER
            else (2.0, 3.0, 4.0, 6.0),
            maximum=None,
            resting=None,
            **values,
        )

    def test_local_values_override_the_provider_winners(self) -> None:
        configurations = [
            self.local(ZoneConfigurationMetric.POWER, threshold=300.0),
            self.local(ZoneConfigurationMetric.PACE, sport=Sport.RUN, threshold=5.0),
        ]
        result = load_checks.load_thresholds(inputs(), TODAY, configurations)
        self.assertEqual(300.0, result.for_sport(Sport.RIDE).zones.ftp)
        self.assertEqual(5.0, result.for_sport(Sport.RUN).threshold_speed_mps)
        self.assertEqual(170.0, result.for_sport(Sport.RUN).zones.lthr)

    def test_without_provider_thresholds_local_values_remain(self) -> None:
        configurations = [self.local(ZoneConfigurationMetric.POWER, threshold=300.0)]
        result = load_checks.load_thresholds(
            inputs(present=False), TODAY, configurations
        )
        self.assertIsNone(result.unavailable)
        self.assertEqual(300.0, result.for_sport(Sport.RIDE).zones.ftp)
        self.assertIsNone(result.for_sport(Sport.RUN).zones.lthr)

    def test_planned_load_follows_the_local_ftp(self) -> None:
        unit = {
            "date": "2026-11-04",
            "sport": "ride",
            "description": "- 60m 225W",
        }
        loads = []
        for ftp in (250.0, 300.0):
            result = load_checks.load_thresholds(
                inputs(),
                TODAY,
                [self.local(ZoneConfigurationMetric.POWER, threshold=ftp)]
                if ftp != 250.0
                else [],
            )
            loads.append(load_checks.plan_sessions([unit], result)[0].estimate)
        self.assertNotEqual(loads[0].intensity_factor, loads[1].intensity_factor)


class SessionSpikeTests(unittest.TestCase):
    def test_ride_spike_is_graded(self) -> None:
        done = [ride_done("2026-10-28", normalized_power=200)]
        notice = check([planned("a", "2026-11-04", "ride", "- 60m 90%")], done)
        warning = check([planned("a", "2026-11-04", "ride", "- 60m 100%")], done)
        self.assertEqual(
            "notice", only(notice, "load_spike")[0]["evidence"]["severity"]
        )
        spike = only(warning, "load_spike")[0]
        self.assertEqual("warning", spike["evidence"]["severity"])
        self.assertEqual(56, spike["evidence"]["increase_percent"])
        self.assertEqual("precise", spike["evidence"]["precision"])
        self.assertFalse(spike["blocking"])
        self.assertIn("not directly validated", spike["evidence_strength"])

    def test_run_spike_by_load_with_same_duration(self) -> None:
        done = [run_done("2026-10-28", weighted_avg_speed_mps=3.2)]
        easy = check([planned("a", "2026-11-04", "run", "- 60m 80% pace")], done)
        threshold = check([planned("a", "2026-11-04", "run", "- 60m 100% pace")], done)
        self.assertEqual([], only(easy, "load_spike"))
        self.assertEqual(1, len(only(threshold, "load_spike")))

    def test_heart_rate_reference_is_labelled_less_precise(self) -> None:
        done = [ride_done("2026-10-28", avg_hr=148.5)]
        found = only(
            check([planned("a", "2026-11-04", "ride", "- 60m 100%")], done),
            "load_spike",
        )
        self.assertEqual("less_precise", found[0]["evidence"]["precision"])

    def test_highest_of_30_days_is_the_reference_per_sport(self) -> None:
        done = [
            ride_done("2026-10-20", normalized_power=250),
            ride_done("2026-10-28", normalized_power=150),
            ride_done("2026-09-01", normalized_power=300),
        ]
        plan = [planned("a", "2026-11-04", "ride", "- 60m 100%")]
        self.assertEqual([], only(check(plan, done), "load_spike"))

    def test_no_history_no_spike_note(self) -> None:
        plan = [planned("a", "2026-11-04", "ride", "- 60m 100%")]
        self.assertEqual([], only(check(plan), "load_spike"))


class WeeklyRiseTests(unittest.TestCase):
    history: ClassVar[list[dict[str, Any]]] = [
        ride_done("2026-10-27", normalized_power=200),
        ride_done("2026-10-20", normalized_power=200),
        ride_done("2026-10-13", normalized_power=200),
    ]
    plan: ClassVar[list[dict[str, Any]]] = [
        planned("a", "2026-11-10", "ride", "- 60m 80%"),
        planned("b", "2026-11-12", "ride", "- 60m 80%"),
    ]

    def test_clear_rise_over_previous_weeks_is_a_notice(self) -> None:
        found = only(check(self.plan, self.history), "weekly_load_rise")
        self.assertEqual(1, len(found))
        evidence = found[0]["evidence"]
        self.assertEqual("ride", evidence["sport"])
        self.assertEqual("2026-11-09", evidence["week_start"])
        self.assertEqual(128, evidence["planned_week_load"])
        self.assertEqual(64, evidence["baseline_mean_load"])
        self.assertEqual("notice", evidence["severity"])
        self.assertFalse(found[0]["blocking"])
        self.assertEqual(["a", "b"], found[0]["local_ids"])

    def test_small_rise_and_thin_history_give_no_note(self) -> None:
        small = [planned("a", "2026-11-10", "ride", "- 60m 85%")]
        self.assertEqual([], only(check(small, self.history), "weekly_load_rise"))
        thin = self.history[:2]
        self.assertEqual([], only(check(self.plan, thin), "weekly_load_rise"))

    def test_sports_are_compared_separately(self) -> None:
        run_week = [planned("r", "2026-11-10", "run", "- 120m 100% pace")]
        self.assertEqual([], only(check(run_week, self.history), "weekly_load_rise"))

    def test_baseline_weeks_with_unknown_sessions_are_left_out(self) -> None:
        history = [
            *self.history,
            ride_done("2026-10-14", avg_power=None),
            ride_done("2026-10-21"),
            ride_done("2026-10-28"),
        ]
        self.assertEqual([], only(check(self.plan, history), "weekly_load_rise"))

    def test_activity_done_today_counts_and_replaces_todays_plan(self) -> None:
        done = [*self.history, ride_done("2026-11-02", normalized_power=250)]
        later = [planned("a", "2026-11-04", "ride", "- 60m 80%")]
        found = only(check(later, done), "weekly_load_rise")
        self.assertEqual(1, len(found))
        self.assertEqual("2026-11-02", found[0]["evidence"]["week_start"])
        both = [planned("t", "2026-11-02", "ride", "- 60m 100%"), *later]
        self.assertEqual(
            found[0]["evidence"]["planned_week_load"],
            only(check(both, done), "weekly_load_rise")[0]["evidence"][
                "planned_week_load"
            ],
        )

    def test_week_with_unknown_load_is_skipped(self) -> None:
        plan = [*self.plan, planned("x", "2026-11-11", "ride", "Easy Z2")]
        self.assertEqual([], only(check(plan, self.history), "weekly_load_rise"))


class IndoorFtpTests(unittest.TestCase):
    def test_a_provider_indoor_ftp_is_not_read(self) -> None:
        result = load_checks.load_thresholds(inputs(), TODAY)
        indoor = result.for_sport(Sport.RIDE, Environment.INDOOR)
        self.assertEqual(250.0, indoor.zones.ftp)
        self.assertEqual(250.0, result.for_sport(Sport.RIDE).zones.ftp)

    def test_completed_and_planned_indoor_rides_share_the_indoor_ftp(self) -> None:
        indoor = AthleteThresholds(zones=ZoneSettings(ftp=200.0))
        thr = load_checks.LoadThresholds(thresholds().by_sport, indoor_ride=indoor)
        done = [ride_done("2026-10-28", normalized_power=200, environment="indoor")]
        plan = [planned("a", "2026-11-04", "ride", "- 60m 90%", environment="indoor")]
        found = only(check(plan, done, thr), "load_spike")
        self.assertEqual([], found)
        outdoor = [planned("a", "2026-11-04", "ride", "- 60m 130%")]
        self.assertEqual(1, len(only(check(outdoor, done, thr), "load_spike")))


class UnknownLoadTests(unittest.TestCase):
    def test_unknown_note_keeps_its_identity_when_sessions_change(self) -> None:
        one = check([planned("a", "2026-11-04", "ride", "Easy Z2")])
        two = check(
            [
                planned("a", "2026-11-04", "ride", "Easy Z2"),
                planned("b", "2026-11-05", "ride", "Easy Z2"),
            ]
        )
        self.assertEqual([], plan_checks.new_findings(one, two))

    def test_unparsed_steps_are_named_not_guessed(self) -> None:
        found = only(
            check([planned("a", "2026-11-04", "ride", "Easy Z2")]), "load_unknown"
        )
        self.assertEqual(1, len(found))
        self.assertEqual(["missing_workout_steps"], found[0]["evidence"]["reasons"])
        self.assertFalse(found[0]["blocking"])

    def test_stale_thresholds_give_only_an_unknown_note(self) -> None:
        stale = load_checks.LoadThresholds(unavailable="stale_thresholds")
        done = [ride_done("2026-10-28", normalized_power=200)]
        plan = [planned("a", "2026-11-04", "ride", "- 60m 100%")]
        found = check(plan, done, stale)
        self.assertEqual(["load_unknown"], [item["code"] for item in found])
        self.assertEqual(["stale_thresholds"], found[0]["evidence"]["reasons"])

    def test_missing_run_pace_is_unknown(self) -> None:
        plan = [planned("a", "2026-11-04", "run", "- 60m 5:00/km pace")]
        found = check(plan, thr=thresholds(pace=False))
        self.assertEqual(
            ["missing_threshold_pace"],
            only(found, "load_unknown")[0]["evidence"]["reasons"],
        )

    def test_without_thresholds_no_load_note_is_made(self) -> None:
        found = plan_checks.check_plan(
            today=TODAY,
            units=[planned("a", "2026-11-04", "ride", "Easy Z2")],
            completed=[],
            competitions=[],
        )
        self.assertEqual([], found)


class HardFromIntensityTests(unittest.TestCase):
    def test_computed_intensity_decides_hard_over_text(self) -> None:
        easy = planned("a", "2026-11-04", "ride", "- 60m 60%", name="Z5 recovery")
        hard = planned("b", "2026-11-05", "ride", "- 20m 60%\n- 20m 95%\n- 10m 60%")
        found = check([easy, hard])
        self.assertEqual([], only(found, "back_to_back_hard"))
        self.assertTrue(plan_checks.is_hard({**hard, plan_checks.COMPUTED_HARD: True}))
        self.assertFalse(
            plan_checks.is_hard({**easy, plan_checks.COMPUTED_HARD: False})
        )

    def test_back_to_back_uses_step_intensity(self) -> None:
        first = planned("a", "2026-11-04", "run", "- 15m 95% pace\n- 45m 70% pace")
        second = planned("b", "2026-11-05", "ride", "- 60m 100%")
        self.assertEqual(1, len(only(check([first, second]), "back_to_back_hard")))

    def test_easy_pace_ratio_is_not_hard(self) -> None:
        easy = planned("a", "2026-11-04", "run", "- 60m 85% pace", name="Z5 text")
        other = planned("b", "2026-11-05", "ride", "- 60m 100%")
        self.assertEqual([], only(check([easy, other]), "back_to_back_hard"))

    def test_unknown_intensity_falls_back_to_key_and_text(self) -> None:
        text = planned("a", "2026-11-04", "ride", "Z5 intervals")
        key = planned("b", "2026-11-05", "run", "Easy", planned_intensity=0.9)
        self.assertEqual(1, len(only(check([text, key]), "back_to_back_hard")))


class MixedPlanTests(unittest.TestCase):
    def test_run_ride_and_strength_plan(self) -> None:
        done = [
            run_done("2026-10-28", weighted_avg_speed_mps=3.2, distance_m=10000),
            ride_done("2026-10-29", normalized_power=200),
        ]
        plan = [
            planned("r", "2026-11-04", "run", "- 60m 100% pace"),
            planned("b", "2026-11-05", "ride", "- 60m 100%"),
            planned("s", "2026-11-06", "strength", "Heavy 5x5"),
        ]
        found = check(plan, done)
        self.assertEqual(
            ["load_spike", "load_spike"],
            [item["code"] for item in found if item["code"] == "load_spike"],
        )
        self.assertFalse(any(item["blocking"] for item in found))
        for item in found:
            self.assertNotIn("s", item["local_ids"])
        self.assertEqual(
            {"r", "b"},
            {i for item in only(found, "load_spike") for i in item["local_ids"]},
        )


class RiskTests(unittest.TestCase):
    def test_spike_growing_into_warning_is_new(self) -> None:
        done = [ride_done("2026-10-28", normalized_power=200)]
        before = check([planned("a", "2026-11-04", "ride", "- 60m 90%")], done)
        after = check([planned("a", "2026-11-04", "ride", "- 60m 100%")], done)
        self.assertEqual(after, plan_checks.new_findings(before, after))
        self.assertEqual([], plan_checks.new_findings(after, before))


class IndoorConfigurationTests(unittest.TestCase):
    def test_indoor_only_local_configuration_keeps_thresholds_usable(self) -> None:
        configuration = LocalThresholdPrecedenceTests.local(
            ZoneConfigurationMetric.POWER,
            threshold=280.0,
            environment=Environment.INDOOR,
        )
        result = load_checks.load_thresholds(
            inputs(present=False), TODAY, [configuration]
        )
        self.assertIsNone(result.unavailable)
        indoor = result.for_sport(Sport.RIDE, Environment.INDOOR)
        self.assertEqual(280.0, indoor.zones.ftp)


class ConfigurationValidityTests(unittest.TestCase):
    def test_intervals_provider_configurations_are_ignored(self) -> None:
        provider = zone_configuration(
            metric=ZoneConfigurationMetric.POWER,
            sport=Sport.RIDE,
            threshold=300.0,
            maximum=None,
            resting=None,
            limits=(100.0, 200.0, 300.0, 400.0),
        )
        self.assertIs(provider.provenance.provider, ProviderId.INTERVALS)
        result = load_checks.load_thresholds(inputs(present=False), TODAY, [provider])
        self.assertEqual("missing_thresholds", result.unavailable)

    def test_other_provider_configurations_count(self) -> None:
        garmin = zone_configuration(
            metric=ZoneConfigurationMetric.POWER,
            sport=Sport.RIDE,
            threshold=300.0,
            maximum=None,
            resting=None,
            limits=(100.0, 200.0, 300.0, 400.0),
            provenance=provenance("zones", provider=ProviderId.GARMIN),
        )
        result = load_checks.load_thresholds(inputs(present=False), TODAY, [garmin])
        self.assertIsNone(result.unavailable)
        self.assertEqual(300.0, result.for_sport(Sport.RIDE).zones.ftp)

    def test_workout_date_selects_the_valid_configuration(self) -> None:
        later = LocalThresholdPrecedenceTests.local(
            ZoneConfigurationMetric.POWER,
            threshold=300.0,
            valid_from=date(2026, 11, 10),
        )
        result = load_checks.load_thresholds(inputs(), TODAY, [later])
        self.assertEqual(250.0, result.for_sport(Sport.RIDE).zones.ftp)
        self.assertEqual(
            300.0, result.for_sport(Sport.RIDE, day=date(2026, 11, 12)).zones.ftp
        )


if __name__ == "__main__":
    unittest.main()
