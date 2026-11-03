"""Planned intensity distribution per week and its comparison with the model."""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

from backend.activities.workout_load import AthleteThresholds, WorkoutEstimate
from backend.activities.zone_settings import ZoneSettings
from backend.planning import intensity_distribution as dist
from backend.planning import plan_checks
from backend.planning.plan_guard_service import PlanGuardService, build_planning_brief
from backend.planning.planned_unit_load import (
    PlannedUnitEstimator,
    estimate_planned_unit,
)

THRESHOLDS = AthleteThresholds(ZoneSettings(ftp=250, lthr=170, max_hr=190))
TODAY = date(2026, 11, 2)


def estimate(unit: Mapping[str, Any]) -> WorkoutEstimate:
    return estimate_planned_unit(unit, THRESHOLDS)


def unit(local_id: str, day: str, sport: str, text: str, **extra: Any) -> dict:
    return {
        "local_id": local_id,
        "date": day,
        "sport": sport,
        "description": text,
        **extra,
    }


def week(low: int, moderate: int, high: int) -> list[dict]:
    """A week with the given minutes in Z2 (low), Z3 (moderate) and Z5 (high)."""
    return [
        unit("a", "2026-11-03", "Ride", f"- {low}m Z2\n"),
        unit("b", "2026-11-05", "Run", f"- {moderate}m 85% HR\n"),
        unit("c", "2026-11-07", "Ride", f"- {high}m Z5\n"),
    ]


class DistributionTests(unittest.TestCase):
    def weeks(self, units: list[dict], today: date = TODAY) -> list[dict]:
        return dist.planned_weeks(units, estimate, today)

    def test_pyramidal_in_range_and_out_of_range(self) -> None:
        inside = self.weeks(week(300, 60, 20))[0]
        self.assertEqual(
            {"low": 18000, "moderate": 3600, "high": 1200}, inside["seconds"]
        )
        self.assertEqual({}, dist.deviations("pyramidal", inside))
        outside = self.weeks(week(120, 180, 20))[0]
        self.assertEqual(
            {"low", "moderate"}, set(dist.deviations("pyramidal", outside))
        )

    def test_polarized_notes_a_moderate_heavy_week(self) -> None:
        heavy = self.weeks(week(240, 120, 20))
        self.assertEqual({}, dist.deviations("pyramidal", heavy[0]))
        findings = dist.distribution_findings("polarized", heavy)
        self.assertEqual(["intensity_distribution"], [f["code"] for f in findings])
        self.assertFalse(findings[0]["blocking"])
        self.assertIn("moderate", findings[0]["evidence"]["deviating_bands"])
        self.assertIn("Z1-Z2 low", findings[0]["evidence"]["zone_mapping"])

    def test_threshold_and_sweet_spot_ranges(self) -> None:
        easy = self.weeks(week(300, 60, 20))[0]
        for model in ("threshold", "sweet_spot"):
            self.assertIn("low", dist.deviations(model, easy), model)
        middle = self.weeks(week(180, 150, 20))[0]
        self.assertEqual({}, dist.deviations("sweet_spot", middle))
        self.assertEqual({}, dist.deviations("threshold", middle))

    def test_unknown_intensity_is_uncovered_not_low(self) -> None:
        units = [
            unit("a", "2026-11-03", "Run", "lockerer Lauf", duration_minutes=120),
            unit("b", "2026-11-05", "Ride", "- 30m Z2\n"),
        ]
        result = self.weeks(units)[0]
        self.assertEqual(7200, result["uncovered_s"])
        self.assertEqual(1800, result["seconds"]["low"])
        self.assertLess(result["coverage"], dist.MIN_COVERAGE)
        self.assertEqual({}, dist.deviations("polarized", result))
        self.assertEqual([], dist.distribution_findings("polarized", [result]))

    def test_mixed_week_excludes_strength(self) -> None:
        units = [
            *week(240, 120, 20),
            unit("s", "2026-11-04", "WeightTraining", "Kraft", planned_duration_s=3000),
        ]
        result = self.weeks(units)[0]
        self.assertNotIn("s", result["local_ids"])
        self.assertEqual(0, result["uncovered_s"])
        self.assertEqual(22800, sum(result["seconds"].values()))

    def test_easy_and_partial_weeks_are_not_judged(self) -> None:
        easy = self.weeks([unit("a", "2026-11-03", "Ride", "- 240m Z2\n")])[0]
        self.assertEqual({}, dist.deviations("polarized", easy))
        partial = self.weeks(week(240, 120, 20), date(2026, 11, 4))[0]
        self.assertTrue(partial["partial"])
        self.assertEqual({}, dist.deviations("polarized", partial))

    def test_finding_identity_is_the_week(self) -> None:
        guard = GuardIntegrationTests().guard
        before = guard("polarized", week(240, 120, 20)).findings()
        more = [*week(240, 120, 20), unit("d", "2026-11-08", "Ride", "- 20m Z2\n")]
        after = guard("polarized", more).findings()
        self.assertEqual([], plan_checks.new_findings(before, after))

    def test_weeks_are_separate_and_unknown_model_is_silent(self) -> None:
        units = [*week(240, 120, 20), unit("n", "2026-11-10", "Run", "- 60m Z2\n")]
        self.assertEqual(
            ["2026-11-02", "2026-11-09"], [w["week_start"] for w in self.weeks(units)]
        )
        self.assertEqual({}, dist.deviations("unknown", self.weeks(units)[0]))


class EstimatorTests(unittest.TestCase):
    def test_reads_inputs_once(self) -> None:
        manager = MagicMock()
        configurations = MagicMock(return_value=())
        estimator = PlannedUnitEstimator(
            lambda: manager, lambda: "reader", configurations
        )
        ride = unit("a", "2026-11-03", "Ride", "- 30m Z2\n")
        with (
            patch(
                "backend.planning.planned_unit_load.read_zone_thresholds",
                return_value=(),
            ) as read,
            patch("backend.planning.planned_unit_load.resolve_reader"),
        ):
            bands = estimator(ride).band_seconds
            self.assertEqual(1800, (bands or {}).get("low"))
            estimator(ride)
        read.assert_called_once()
        configurations.assert_called_once()


class GuardIntegrationTests(unittest.TestCase):
    def guard(self, model: str, units: list[dict]) -> PlanGuardService:
        return PlanGuardService(
            planned_units=lambda: units,
            completed_activities=list,
            competitions=list,
            illness=lambda: "",
            progress=lambda: {"week_list": []},
            training_model=lambda: model,
            today=lambda: TODAY,
            estimate_unit=estimate,
        )

    def test_note_is_returned_and_does_not_block(self) -> None:
        notes = self.guard("polarized", week(240, 120, 20)).verify([], [])
        self.assertEqual(["intensity_distribution"], [n["code"] for n in notes])
        self.assertEqual(
            plan_checks.EVIDENCE["intensity_distribution"],
            notes[0]["evidence_strength"],
        )

    def test_no_note_in_range_and_none_twice(self) -> None:
        self.assertEqual([], self.guard("pyramidal", week(300, 60, 20)).verify([], []))
        guard = self.guard("polarized", week(240, 120, 20))
        self.assertEqual([], guard.verify(guard.findings(), []))

    def test_brief_field(self) -> None:
        brief = self.guard("polarized", week(240, 120, 20)).brief()
        planned = brief["planned_distribution"]
        self.assertEqual(dist.MODEL_RANGES["polarized"], planned["reference_ranges"])
        self.assertEqual("2026-11-02", planned["weeks"][0]["week_start"])
        self.assertIsNone(
            build_planning_brief(
                progress={},
                completed=[],
                competitions=[],
                training_model="polarized",
                today=TODAY,
            )["planned_distribution"]
        )


def done(day: str, sport: str, minutes: int, zone: str) -> dict:
    return {
        "sport": sport,
        "started_at_local": f"{day}T07:00:00",
        "moving_duration_s": minutes * 60,
        "power_zone_times": [
            {"id": f"Z{number}", "secs": minutes * 60 if f"Z{number}" == zone else 0}
            for number in range(1, 8)
        ],
    }


class RunningWeekTests(unittest.TestCase):
    """Monday and Tuesday completed, the rest of the week planned."""

    TODAY = date(2026, 11, 4)

    def weeks(self, units: list[dict], completed: list[dict]) -> list[dict]:
        return dist.planned_weeks(units, estimate, self.TODAY, completed)

    def test_completed_days_are_combined_with_the_planned_rest(self) -> None:
        completed = [
            done("2026-11-02", "ride", 90, "Z5"),
            done("2026-11-03", "run", 60, "Z2"),
        ]
        planned = [
            unit("p1", "2026-11-05", "Ride", "- 60m Z2\n"),
            unit("p2", "2026-11-07", "Ride", "- 60m Z2\n"),
        ]
        week = self.weeks(planned, completed)[0]
        self.assertFalse(week["partial"])
        self.assertEqual("running week: completed + planned", week["basis"])
        self.assertEqual(
            {"low": 3600 + 7200, "moderate": 0, "high": 5400}, week["seconds"]
        )
        found = dist.distribution_findings("pyramidal", [week])
        self.assertEqual(
            {"moderate", "high"}, set(found[0]["evidence"]["deviating_bands"])
        )
        self.assertTrue(found[0]["message"].startswith("Running week: completed"))

    def test_planned_alone_stays_partial_and_unjudged(self) -> None:
        planned = [unit("p1", "2026-11-05", "Ride", "- 120m Z5\n")]
        week = dist.planned_weeks(planned, estimate, self.TODAY)[0]
        self.assertTrue(week["partial"])
        self.assertEqual("planned", week["basis"])
        self.assertEqual({}, dist.deviations("pyramidal", week))

    def test_coverage_minimum_still_applies(self) -> None:
        completed = [{**done("2026-11-02", "ride", 150, "Z2"), "power_zone_times": []}]
        planned = [unit("p1", "2026-11-05", "Ride", "- 30m Z2\n")]
        week = self.weeks(planned, completed)[0]
        self.assertLess(week["coverage"], dist.MIN_COVERAGE)
        self.assertEqual({}, dist.deviations("polarized", week))

    def test_planned_unit_already_done_today_is_not_counted_twice(self) -> None:
        completed = [done("2026-11-04", "ride", 60, "Z2")]
        planned = [unit("p1", "2026-11-04", "Ride", "- 60m Z2\n")] + week(300, 60, 20)
        week_row = self.weeks(planned, completed)[0]
        self.assertNotIn("p1", week_row["local_ids"])
        self.assertEqual(18000 + 3600, week_row["seconds"]["low"])


if __name__ == "__main__":
    unittest.main()
