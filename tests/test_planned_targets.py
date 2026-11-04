"""Executed work laps against the planned steps' targets."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

from session_stream_support import synthetic_session

from backend.activities.workout_load import AthleteThresholds, step_target_range
from backend.activities.workout_text import structured_steps
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import Sport
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.performance.planned_targets import planned_target_execution
from backend.performance.session_execution import session_execution

THRESHOLDS = AthleteThresholds(
    zones=ZoneSettings(ftp=250.0, lthr=170.0, max_hr=190.0),
    threshold_speed_mps=4.0,
)
PLAN = "- 10m Z2 Pace\n\n5x\n- 3m 4:20-4:30/km Pace\n- 90s Z1 Pace\n\n- 5m Z1 Pace"


def _bound(value: float | None) -> float:
    """A resolved target bound; the test fails when it is unknown."""
    assert value is not None
    return value


def _run(last_speed: float = 3.6) -> dict[str, Any]:
    segments: list[tuple[str, int, float, tuple[float, float]]] = [
        ("warmup", 600, 3.0, (120.0, 135.0))
    ]
    for rep in range(5):
        speed = last_speed if rep == 4 else 3.8
        segments.append(("work", 180, speed, (150.0, 168.0)))
        if rep < 4:
            segments.append(("recovery", 90, 2.5, (168.0, 140.0)))
    segments.append(("cooldown", 300, 2.8, (140.0, 125.0)))
    return synthetic_session(segments)


def _display_streams(session: dict[str, Any]) -> dict[str, Any]:
    streams = session["streams"]
    return {
        "time_s": list(streams["time"]),
        "channels": {"speed_mps": {"values": list(streams["velocity_smooth"])}},
    }


class StepTargetRangeTests(unittest.TestCase):
    def test_every_target_form_resolves_to_bounds(self) -> None:
        cases = {
            "- 10m 4:05-4:15/km Pace": ("speed", 1000 / 255, 1000 / 245),
            "- 10m 95-105% Pace": ("speed", 3.8, 4.2),
            "- 10m Z2 Pace": ("speed", 3.1, 3.508),
            "- 10m 160-165bpm HR": ("heartrate", 160.0, 165.0),
            "- 10m 240-260W": ("watts", 240.0, 260.0),
            "- 10m 90-95%": ("watts", 225.0, 237.5),
        }
        for text, (metric, low, high) in cases.items():
            step = structured_steps(text)[0]
            sport = Sport.RUN if "Pace" in text or "HR" in text else Sport.RIDE
            with self.subTest(text=text):
                target = step_target_range(step, THRESHOLDS, sport)
                self.assertEqual(target.metric, metric)
                self.assertAlmostEqual(_bound(target.low), low, places=2)
                self.assertAlmostEqual(_bound(target.high), high, places=2)

    def test_single_values_widen_and_unknowns_say_why(self) -> None:
        single = step_target_range(
            structured_steps("- 10m 250W")[0], THRESHOLDS, Sport.RIDE
        )
        self.assertAlmostEqual(_bound(single.low), 243.75)
        self.assertAlmostEqual(_bound(single.high), 256.25)
        ramp = structured_steps("- 10m ramp 50-75%")[0]
        self.assertEqual(
            step_target_range(ramp, THRESHOLDS, Sport.RIDE).unknown, "ramp"
        )
        missing = AthleteThresholds(zones=ZoneSettings())
        target = step_target_range(
            structured_steps("- 10m 90%")[0], missing, Sport.RIDE
        )
        self.assertIsNone(target.metric)
        self.assertIsNotNone(target.unknown)


class OpenTopZoneTests(unittest.TestCase):
    def test_the_top_zone_has_no_upper_bound(self) -> None:
        sprint = structured_steps("- 20s Z7")[0]
        target = step_target_range(sprint, THRESHOLDS, Sport.RIDE)
        self.assertAlmostEqual(_bound(target.low), 375.0)
        self.assertEqual(target.high, float("inf"))


def _ride(watts: list[float]) -> dict[str, Any]:
    segments: list[tuple[str, int, float, tuple[float, float]]] = [
        ("warmup", 600, 150.0, (110.0, 125.0))
    ]
    for value in watts:
        segments += [
            ("work", 360, value, (145.0, 165.0)),
            ("recovery", 180, 120.0, (165.0, 130.0)),
        ]
    return synthetic_session(segments, sport="ride", output="watts", cadence=90.0)


class PlannedTargetExecutionTests(unittest.TestCase):
    def test_progressions_pair_every_rep_with_its_own_step(self) -> None:
        plan = "- 10m Z1\n\n- 6m 85%\n- 3m 50%\n- 6m 95%\n- 3m 50%\n- 6m 105%\n- 3m 50%"
        result = planned_target_execution(
            session_execution(_ride([212.0, 238.0, 262.0])),
            structured_steps(plan),
            THRESHOLDS,
            "ride",
        )
        self.assertEqual(
            [rep["planned_target"] for rep in result["reps"]], ["85%", "95%", "105%"]
        )
        self.assertEqual(result["summary"]["in_target"], 3)

    def test_open_top_zone_reps_above_its_floor_are_in_target(self) -> None:
        result = planned_target_execution(
            session_execution(_ride([425.0, 430.0])),
            structured_steps("- 10m Z1\n\n2x\n- 6m Z7\n- 3m Z1"),
            THRESHOLDS,
            "ride",
        )
        self.assertEqual(result["reps"][0]["target_watts"], [375, None])
        self.assertEqual(result["reps"][0]["deviation_pct"], 0.0)

    def test_short_reps_leave_heart_rate_targets_unscored(self) -> None:
        segments: list[tuple[str, int, float, tuple[float, float]]] = [
            ("warmup", 600, 3.0, (120.0, 130.0))
        ]
        for _ in range(4):
            segments += [
                ("work", 45, 5.0, (140.0, 160.0)),
                ("recovery", 60, 2.5, (160.0, 140.0)),
            ]
        result = planned_target_execution(
            session_execution(synthetic_session(segments)),
            structured_steps("- 10m Z1 Pace\n\n4x\n- 45s 170-175bpm HR\n- 60s Z1 Pace"),
            THRESHOLDS,
            "run",
        )
        self.assertEqual(result["reps"][0]["target_unknown"], "short_rep_heart_rate")
        self.assertNotIn("deviation_pct", result["reps"][0])

    def test_absolute_paces_count_without_a_threshold_pace(self) -> None:
        no_pace = AthleteThresholds(zones=ZoneSettings())
        result = planned_target_execution(
            session_execution(_run()),
            structured_steps("5x\n- 3m 4:20-4:30/km Pace\n- 90s 6:00-7:00/km Pace"),
            no_pace,
            "run",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["in_target"], 4)

    def test_each_rep_is_compared_with_its_planned_step(self) -> None:
        session = _run()
        execution = session_execution(session)
        result = planned_target_execution(
            execution,
            structured_steps(PLAN),
            THRESHOLDS,
            "run",
            planned_unit_id="unit-1",
            streams=_display_streams(session),
        )
        self.assertEqual(result["status"], "ok")
        reps = result["reps"]
        self.assertEqual(len(reps), 5)
        first, last = reps[0], reps[-1]
        self.assertEqual(first["target_pace_s_per_km"], [260, 270])
        self.assertEqual(first["deviation_pct"], 0.0)
        self.assertEqual(first["time_in_target_pct"], 100)
        self.assertEqual(first["planned_duration_s"], 180)
        self.assertEqual(first["planned_recovery_s"], 90)
        self.assertEqual(first["recovery_s"], 90)
        self.assertLess(last["deviation_pct"], 0)
        self.assertEqual(last["time_in_target_pct"], 0)
        self.assertEqual(
            result["summary"],
            {
                "planned_work_steps": 5,
                "executed_work_laps": 5,
                "compared": 5,
                "in_target": 4,
                "above_target": 0,
                "below_target": 1,
            },
        )

    def test_heart_rate_targets_use_the_second_half(self) -> None:
        execution = session_execution(_run())
        plan = "- 10m Z2 Pace\n\n5x\n- 3m 160-170bpm HR\n- 90s Z1 Pace"
        result = planned_target_execution(
            execution, structured_steps(plan), THRESHOLDS, "run"
        )
        self.assertEqual(result["reps"][0]["target_bpm"], [160, 170])
        self.assertEqual(result["reps"][0]["deviation_pct"], 0.0)

    def test_heart_rate_time_in_target_reads_the_second_half(self) -> None:
        session = _run()
        streams = _display_streams(session)
        streams["channels"]["heart_rate_bpm"] = {
            "values": list(session["streams"]["heartrate"])
        }
        plan = "- 10m Z2 Pace\n\n5x\n- 3m 160-170bpm HR\n- 90s Z1 Pace"
        result = planned_target_execution(
            session_execution(session),
            structured_steps(plan),
            THRESHOLDS,
            "run",
            streams=streams,
        )
        # Heart rate climbs 150-168 bpm: its second half is inside 160-170.
        self.assertGreaterEqual(result["reps"][0]["time_in_target_pct"], 85)

    def test_rep_counts_beyond_the_listed_reps_and_speed_targets_on_power_rides(
        self,
    ) -> None:
        execution = session_execution(_ride([250.0, 250.0]))
        execution["rep_summary"]["rep_count"] = 50
        session = _ride([250.0, 250.0])
        times = list(session["streams"]["time"])
        streams = {
            "time_s": times,
            "channels": {"speed_mps": {"values": [9.0] * len(times)}},
        }
        result = planned_target_execution(
            execution,
            structured_steps("- 10m Z1\n\n2x\n- 6m 1:50-2:00/km Pace\n- 3m Z1"),
            THRESHOLDS,
            "ride",
            streams=streams,
        )
        self.assertEqual(result["summary"]["executed_work_laps"], 50)
        # 9 m/s from the displayed speed is inside 1:50-2:00/km.
        self.assertEqual(result["reps"][0]["target_kmh"], [30.0, 32.7])
        self.assertEqual(result["reps"][0]["deviation_pct"], 0.0)

    def test_continuous_sessions_and_unresolved_plans_are_not_covered(self) -> None:
        steady = session_execution(
            synthetic_session([("lap", 1800, 3.0, (140.0, 145.0))], kinds=False)
        )
        result = planned_target_execution(
            steady, structured_steps(PLAN), THRESHOLDS, "run"
        )
        self.assertEqual(result["status"], "not_covered")
        ramps = planned_target_execution(
            session_execution(_run()),
            structured_steps("- 10m ramp 50-75%\n- 10m ramp 75-50%"),
            THRESHOLDS,
            "ride",
        )
        self.assertEqual(ramps["status"], "not_covered")
        self.assertEqual(ramps["unknown_targets"], ["ramp"])


class CoachPlannedTargetsTests(unittest.TestCase):
    def _service(self, thresholds: Any) -> CoachActivityReadToolService:
        return CoachActivityReadToolService(
            Mock(), Mock(), Mock(), Mock(), unit_thresholds=thresholds
        )

    def test_matched_unit_brings_planned_targets(self) -> None:
        session = _run()
        detail = {
            "analysis": {"execution": session_execution(session)},
            "streams": _display_streams(session),
        }
        thresholds = Mock()
        thresholds.thresholds.return_value = THRESHOLDS
        unit = {"id": "unit-1", "description": PLAN, "target": "PACE"}
        result = self._service(thresholds)._planned_targets(
            detail, {"sport": "run"}, {"planned_unit_id": "unit-1"}, [unit]
        )
        assert result is not None
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["planned_unit_id"], "unit-1")
        thresholds.thresholds.assert_called_once_with(unit)

    def test_a_unit_without_focus_matches_by_day_and_sport(self) -> None:
        session = _run()
        detail = {"analysis": {"execution": session_execution(session)}}
        thresholds = Mock()
        thresholds.thresholds.return_value = THRESHOLDS
        unit = {
            "id": "unit-1",
            "date": "2026-11-03T00:00:00",
            "description": PLAN,
            "type": "Run",
        }
        other = {
            "id": "unit-2",
            "date": "2026-11-04T00:00:00",
            "description": PLAN,
            "type": "Run",
        }
        result = self._service(thresholds)._planned_targets(
            detail,
            {"sport": "run", "started_at_local": "2026-11-03T07:00:00"},
            {"status": "unknown"},
            [unit, other],
        )
        assert result is not None
        self.assertEqual(result["planned_unit_id"], "unit-1")

    def test_without_a_matched_unit_or_thresholds_there_is_none(self) -> None:
        detail = {"analysis": {"execution": session_execution(_run())}}
        unit = {"id": "unit-1", "description": PLAN}
        self.assertIsNone(
            self._service(None)._planned_targets(
                detail, {"sport": "run"}, {"planned_unit_id": "unit-1"}, [unit]
            )
        )
        self.assertIsNone(
            self._service(Mock())._planned_targets(
                detail, {"sport": "run"}, {"status": "unknown"}, [unit]
            )
        )
        broken = {"id": "unit-1", "description": "Easy 30 minutes"}
        result = self._service(Mock())._planned_targets(
            detail, {"sport": "run"}, {"planned_unit_id": "unit-1"}, [broken]
        )
        assert result is not None
        self.assertEqual(result["status"], "not_covered")


if __name__ == "__main__":
    unittest.main()
