"""Local run blocks to Garmin workout JSON mapping, including explicit rejections."""

from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from backend.activities.workout_text import structured_blocks
from backend.providers.garmin_run_workout import (
    PAYLOAD_VERSION,
    GarminRunMappingError,
    GarminRunTargets,
    comparable_steps,
    run_workout,
)

TARGETS = GarminRunTargets(
    ftp=250,
    threshold_hr=170,
    max_hr=190,
    threshold_speed=4.0,
    power_limits=(55, 75, 90, 105, 120, 150),
    hr_limits=(68, 83, 94, 105),
    pace_limits=(80, 90, 100),
)
RUN_TEXT = (
    "Warmup\n- 10m 60-70% LTHR\n\n"
    "Main set 3x\n- 4m 5:00/km Pace\n- 1m 140-150bpm\n\n"
    "Cooldown\n- 1km Z1 HR"
)


def step(target: str, kind: str = "power", **values: Any) -> dict[str, Any]:
    return {"kind": kind, "target": target, "ramp": False, "duration": 300.0, **values}


def block(*steps: dict[str, Any], header: str = "", repeat: int = 1) -> dict[str, Any]:
    return {"header": header, "repeat": repeat, "steps": list(steps)}


def first_step(target: str, kind: str = "power", **targets: Any) -> dict[str, Any]:
    document = run_workout(
        name="Run",
        description="",
        blocks=[block(step(target, kind))],
        targets=GarminRunTargets(**targets) if targets else TARGETS,
    )
    return document["workoutSegments"][0]["workoutSteps"][0]


def values(executable: dict[str, Any]) -> tuple[Any, ...]:
    return (
        executable["targetType"]["workoutTargetTypeKey"],
        executable["targetValueOne"],
        executable["targetValueTwo"],
    )


class DocumentTests(unittest.TestCase):
    def document(self) -> dict[str, Any]:
        return run_workout(
            name="Tempo " * 20,
            description="d" * 1200,
            blocks=structured_blocks(RUN_TEXT),
            targets=TARGETS,
        )

    def test_warmup_repeat_group_and_cooldown_shape(self) -> None:
        document = self.document()
        steps = document["workoutSegments"][0]["workoutSteps"]

        self.assertEqual(1, PAYLOAD_VERSION)
        self.assertEqual(80, len(document["workoutName"]))
        self.assertEqual(1000, len(document["description"]))
        self.assertEqual(
            {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
            document["sportType"],
        )
        self.assertEqual(
            ["ExecutableStepDTO", "RepeatGroupDTO", "ExecutableStepDTO"],
            [item["type"] for item in steps],
        )
        self.assertEqual(
            ["warmup", "repeat", "cooldown"],
            [item["stepType"]["stepTypeKey"] for item in steps],
        )
        self.assertEqual([1, 2, 5], [item["stepOrder"] for item in steps])
        group = steps[1]
        self.assertEqual(3, group["numberOfIterations"])
        self.assertEqual(3.0, group["endConditionValue"])
        self.assertEqual("iterations", group["endCondition"]["conditionTypeKey"])
        self.assertFalse(group["smartRepeat"])
        self.assertEqual([3, 4], [item["stepOrder"] for item in group["workoutSteps"]])
        self.assertEqual(
            ["interval", "interval"],
            [item["stepType"]["stepTypeKey"] for item in group["workoutSteps"]],
        )

    def test_end_conditions_and_estimated_duration(self) -> None:
        document = self.document()
        warmup, group, cooldown = document["workoutSegments"][0]["workoutSteps"]

        self.assertEqual("time", warmup["endCondition"]["conditionTypeKey"])
        self.assertEqual(600.0, warmup["endConditionValue"])
        self.assertEqual("distance", cooldown["endCondition"]["conditionTypeKey"])
        self.assertEqual(3, cooldown["endCondition"]["conditionTypeId"])
        self.assertEqual(1000.0, cooldown["endConditionValue"])
        self.assertIsNone(group["workoutSteps"][0]["zoneNumber"])
        # 600 + 3 * (240 + 60); the distance step has no time.
        self.assertEqual(1500, document["estimatedDurationInSecs"])

    def test_step_type_from_folded_header(self) -> None:
        def kind(header: str) -> str:
            document = run_workout(
                name="n", description="", blocks=[block(step("200W"), header=header)]
            )
            return document["workoutSegments"][0]["workoutSteps"][0]["stepType"][
                "stepTypeKey"
            ]

        for header, expected in {
            "Aufwärmen": "warmup",
            "Einlaufen": "warmup",
            "Warm-up": "warmup",
            "Abwärmen": "cooldown",
            "Auslaufen": "cooldown",
            "Cool down": "cooldown",
            "Main set 4x": "interval",
            "": "interval",
        }.items():
            with self.subTest(header):
                self.assertEqual(expected, kind(header))


class TargetTests(unittest.TestCase):
    def test_absolute_targets(self) -> None:
        self.assertEqual(("power.zone", 250.0, 280.0), values(first_step("280-250W")))
        self.assertEqual(("power.zone", 200.0, 200.0), values(first_step("200W")))
        self.assertEqual(
            ("heart.rate.zone", 140.0, 150.0), values(first_step("140-150BPM", "hr"))
        )

    def test_pace_is_slower_first_and_converts_miles(self) -> None:
        self.assertEqual(
            ("pace.zone", 3.333, 3.333), values(first_step("5:00/KM PACE", "pace"))
        )
        self.assertEqual(
            ("pace.zone", 3.333, 3.704),
            values(first_step("4:30/KM-5:00/KM PACE", "pace")),
        )
        self.assertEqual(
            ("pace.zone", 3.333, 3.704),
            values(first_step("5:00-4:30/KM PACE", "pace")),
        )
        self.assertEqual(
            ("pace.zone", 2.682, 2.682),
            values(first_step("10:00/MI PACE", "pace")),
        )

    def test_percent_bases_resolve_to_absolute_ranges(self) -> None:
        self.assertEqual(
            ("power.zone", 225.0, 250.0), values(first_step("90-100% FTP"))
        )
        self.assertEqual(("power.zone", 200.0, 200.0), values(first_step("80%")))
        self.assertEqual(
            ("heart.rate.zone", 102.0, 119.0), values(first_step("60-70% LTHR", "hr"))
        )
        self.assertEqual(
            ("heart.rate.zone", 152.0, 171.0), values(first_step("80-90% HR", "hr"))
        )
        self.assertEqual(
            ("pace.zone", 3.2, 3.6), values(first_step("80-90% PACE", "pace"))
        )

    def test_zones_use_limits_and_the_zone_one_floor(self) -> None:
        self.assertEqual(("power.zone", 125.0, 138.0), values(first_step("Z1")))
        self.assertEqual(("power.zone", 138.0, 225.0), values(first_step("Z2-Z3")))
        self.assertEqual(
            ("heart.rate.zone", 85.0, 116.0), values(first_step("Z1 HR", "hr"))
        )
        self.assertEqual(
            ("pace.zone", 2.0, 3.6), values(first_step("Z1-Z2 PACE", "pace"))
        )
        basis = first_step(
            "Z2 HR", "hr", threshold_hr=170, hr_zone_basis=180, hr_limits=(60, 80)
        )
        self.assertEqual(("heart.rate.zone", 108.0, 144.0), values(basis))

    def test_open_heart_rate_zone_ends_at_the_maximum(self) -> None:
        self.assertEqual(
            ("heart.rate.zone", 178.0, 190.0), values(first_step("Z5 HR", "hr"))
        )

    def refused(self, target: str, kind: str = "power", **targets: Any) -> str:
        with self.assertRaises(GarminRunMappingError) as raised:
            first_step(target, kind, **targets)
        self.assertEqual(422, raised.exception.status)
        self.assertEqual("garmin_run_unsupported", raised.exception.reason)
        self.assertIn("Schritt 1", str(raised.exception))
        return str(raised.exception)

    def test_missing_references_are_named(self) -> None:
        none: dict[str, Any] = {"power_limits": (55,)}
        self.assertIn("FTP", self.refused("90%", **none))
        self.assertIn("Schwellenpuls", self.refused("60% LTHR", "hr", **none))
        self.assertIn("maximale Herzfrequenz", self.refused("80% HR", "hr", **none))
        self.assertIn("Schwellentempo", self.refused("90% PACE", "pace", **none))
        self.assertIn("FTP", self.refused("Z2", **none))

    def test_unsupported_targets_are_refused(self) -> None:
        self.refused("Z7")
        self.refused("Z0")
        self.refused("Z8 HR", "hr")
        self.refused("Z2", power_limits=(), ftp=250)
        self.assertIn("Obergrenze", self.refused("Z7"))
        self.assertIn("Obergrenze", self.refused("Z4 PACE", "pace"))
        self.assertIn(
            "Obergrenze",
            self.refused("Z5 HR", "hr", threshold_hr=170, hr_limits=(68, 83, 94, 105)),
        )
        self.refused("1:50/100M PACE", "pace")
        self.refused("5:00/KM-8:00/MI PACE", "pace")
        self.refused("5:00 PACE", "pace")
        self.refused("150BPM")
        self.refused("200W", "hr")
        self.refused("80% LTHR")
        self.refused("80%", "hr")
        self.refused("fast", "swim")

    def test_ramps_and_missing_amounts_are_refused(self) -> None:
        with self.assertRaises(GarminRunMappingError) as raised:
            run_workout(
                name="n",
                description="",
                blocks=[block(step("200W"), step("200W", ramp=True))],
            )
        self.assertIn("Schritt 2", str(raised.exception))
        self.assertIn("Rampen", str(raised.exception))
        with self.assertRaises(GarminRunMappingError):
            run_workout(
                name="n",
                description="",
                blocks=[block({"kind": "power", "target": "200W", "ramp": False})],
            )
        with self.assertRaises(GarminRunMappingError):
            run_workout(name="n", description="", blocks=[])


class ComparableTests(unittest.TestCase):
    def test_equal_to_a_read_back_copy_with_extra_fields(self) -> None:
        sent = run_workout(
            name="Run",
            description="text",
            blocks=structured_blocks(RUN_TEXT),
            targets=TARGETS,
        )
        read_back = deepcopy(sent)
        read_back.update(workoutId=7, ownerId=9, description=None)
        segment = read_back["workoutSegments"][0]
        segment["sportType"]["sportTypeId"] = 1
        for item in segment["workoutSteps"]:
            item.update(stepId=1, childStepId=None, description="x")
            for child in item.get("workoutSteps", []):
                child.update(stepId=2, strokeType={"strokeTypeId": 0}, description=None)
                child["endConditionValue"] = int(child["endConditionValue"])
                child["targetValueOne"] += 0.00001
            item["endCondition"]["displayOrder"] = 99

        self.assertEqual(comparable_steps(sent), comparable_steps(read_back))
        self.assertEqual(
            [
                ("warmup", "time", 600.0, "heart.rate.zone", 102.0, 119.0),
                ("repeat", 3, 2),
                ("interval", "time", 240.0, "pace.zone", 3.333, 3.333),
                ("interval", "time", 60.0, "heart.rate.zone", 140.0, 150.0),
                ("cooldown", "distance", 1000.0, "heart.rate.zone", 85.0, 116.0),
            ],
            comparable_steps(sent),
        )

    def test_a_pace_on_the_rounding_edge_stays_equal_after_read_back(self) -> None:
        # 4:46/km is 3.49650... m/s: sent as 3.497, so read-back drift stays equal.
        sent = run_workout(
            name="n",
            description="",
            blocks=[block(step("4:46/KM PACE", "pace"))],
        )
        read_back = deepcopy(sent)
        target = read_back["workoutSegments"][0]["workoutSteps"][0]
        target["targetValueOne"] -= 0.00001
        target["targetValueTwo"] += 0.00001

        self.assertEqual(
            3.497, sent["workoutSegments"][0]["workoutSteps"][0]["targetValueOne"]
        )
        self.assertEqual(comparable_steps(sent), comparable_steps(read_back))

    def test_differences_are_visible(self) -> None:
        blocks = [block(step("200W"), step("210W"), repeat=2)]
        sent = run_workout(name="n", description="", blocks=blocks)
        for change in (
            lambda w: w["workoutSegments"][0]["workoutSteps"][0].update(
                numberOfIterations=3
            ),
            lambda w: w["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"][
                1
            ].update(targetValueTwo=215.0),
            lambda w: w["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"].pop(),
        ):
            changed = deepcopy(sent)
            change(changed)
            self.assertNotEqual(comparable_steps(sent), comparable_steps(changed))


class BlockTests(unittest.TestCase):
    def test_blocks_keep_headers_repeats_and_steps(self) -> None:
        blocks = structured_blocks(RUN_TEXT)

        self.assertEqual(
            ["Warmup", "Main set 3x", "Cooldown"], [b["header"] for b in blocks]
        )
        self.assertEqual([1, 3, 1], [b["repeat"] for b in blocks])
        self.assertEqual([1, 2, 1], [len(b["steps"]) for b in blocks])
        self.assertEqual(
            {
                "kind": "pace",
                "target": "5:00/KM PACE",
                "ramp": False,
                "duration": 240.0,
            },
            blocks[1]["steps"][0],
        )

    def test_block_without_header_text_has_empty_header(self) -> None:
        blocks = structured_blocks("- 10m 60%\n\n2x\n- 5m 90%")

        self.assertEqual(["", "2x"], [b["header"] for b in blocks])


if __name__ == "__main__":
    unittest.main()
