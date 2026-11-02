"""Planned intensity distribution per week and its comparison with the model."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from backend.activities.workout_load import AthleteThresholds
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


def estimate(unit: dict[str, Any]) -> Any:
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
    def weeks(self, units: list[dict]) -> list[dict]:
        return dist.planned_weeks(units, estimate)

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
        easy = self.weeks(week(360, 30, 0))[0]
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

    def test_weeks_are_separate_and_unknown_model_is_silent(self) -> None:
        units = [*week(240, 120, 20), unit("n", "2026-11-10", "Run", "- 60m Z2\n")]
        self.assertEqual(
            ["2026-11-02", "2026-11-09"], [w["week_start"] for w in self.weeks(units)]
        )
        self.assertEqual({}, dist.deviations("unknown", self.weeks(units)[0]))


class EstimatorTests(unittest.TestCase):
    def test_reads_inputs_once_and_uses_sport_thresholds(self) -> None:
        reads: list[str] = []

        def thresholds() -> tuple:
            reads.append("thresholds")
            return ()

        estimator = PlannedUnitEstimator(thresholds, tuple)
        ride = unit("a", "2026-11-03", "Ride", "- 30m Z2\n")
        self.assertEqual(1800, estimator(ride).band_seconds["low"])
        estimator(ride)
        self.assertEqual(["thresholds"], reads)


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


if __name__ == "__main__":
    unittest.main()
