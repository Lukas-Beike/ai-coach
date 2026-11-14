import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.planning.race_plan import (
    course_sections,
    race_plan,
    read_race_plan,
    target_seconds,
)

HALF = {
    "id": "race-1",
    "sport": "run",
    "distance": "21100",
    "target": "Unter 1:45:00 bleiben",
    "planned_duration_s": None,
    "course_profile": "km 0–8 flach\nkm 8–11 +4 %\nkm 11–15 −80 Hm\nkm 15–21,1",
}


class RacePlanTests(unittest.TestCase):
    def test_course_profile_lines_become_sections(self):
        sections, rejected = course_sections(HALF["course_profile"], 21.1)
        self.assertFalse(rejected)
        self.assertEqual(
            [(0, 8, 0), (8, 11, 4), (11, 15, -2), (15, 21.1, 0)],
            [(s["from_km"], s["to_km"], s["grade_pct"]) for s in sections],
        )
        for profile, distance in [
            ("km 0-8 flach\nkm 9-21,1 +1 %", 21.1),  # gap
            ("km 0-8 flach; km 8-15 +1 %", 21.1),  # short of the distance
            ("km 3-8 flach", None),  # does not start at 0
        ]:
            with self.subTest(profile=profile):
                self.assertEqual(([], True), course_sections(profile, distance))
        self.assertEqual(([], False), course_sections("Wellig, Ziel bergauf", 10))

    def test_target_time_forms(self):
        for text, expected in [
            ("Unter 1:45:00 bleiben", 6300),
            ("3:30 h", 12600),
            ("Sub 45", None),
            ('{"distance":21100}', None),
        ]:
            with self.subTest(text=text):
                self.assertEqual(expected, target_seconds(text))

    def test_running_splits_the_target_time_by_equal_effort(self):
        # Minetti et al. (2002) cost, evaluated by hand: C(0) = 3.6,
        # C(+0.04) = 4.451247 (ratio 1.236457), C(-0.02) = 3.228861 (0.896906).
        # Weighted length 21.396995 km over 6300 s.
        pacing = race_plan(HALF, None)["pacing"]
        self.assertEqual(("ready", "equal_effort", "course_profile"), (
            pacing["status"], pacing["method"], pacing["sections_from"]
        ))
        self.assertEqual(
            [(2355, 294), (1092, 364), (1056, 264), (1796, 294)],
            [(s["time_s"], s["pace_s_per_km"]) for s in pacing["sections"]],
        )

    def test_cycling_varies_target_power_by_five_percent(self):
        ride = {
            **HALF,
            "sport": "ride",
            "distance": "",
            "target": "Ziel 230 W",
        }
        pacing = race_plan(ride, None)["pacing"]
        self.assertEqual(230, pacing["target_w"])
        self.assertEqual(
            [(0, 230), (5, 242), (-5, 218), (0, 230)],
            [(s["power_pct"], s["power_w"]) for s in pacing["sections"]],
        )
        no_watts = race_plan({**ride, "target": ""}, None)["pacing"]["sections"]
        self.assertEqual([None] * 4, [s["power_w"] for s in no_watts])

    def test_missing_inputs_leave_their_part_unavailable(self):
        even = race_plan({**HALF, "course_profile": "km 2-9 wellig"}, None)
        self.assertEqual(("even", True), (
            even["pacing"]["sections_from"], even["pacing"]["profile_rejected"]
        ))
        self.assertEqual([(0, 21.1, 0)], [
            (s["from_km"], s["to_km"], s["grade_pct"]) for s in even["pacing"]["sections"]
        ])
        for change, reason in [
            ({"sport": "swim"}, "sport"),
            ({"distance": "Halbmarathon", "course_profile": ""}, "distance"),
            ({"target": "schnell"}, "duration"),
        ]:
            with self.subTest(reason=reason):
                plan = race_plan({**HALF, **change}, None)
                self.assertEqual(
                    {"status": "unavailable", "reason": reason}, plan["pacing"]
                )
        planned = race_plan({**HALF, "target": "", "planned_duration_s": 5400}, None)
        self.assertEqual({"seconds": 5400, "source": "planned_duration"}, planned["duration"])
        unknown = race_plan({**HALF, "target": ""}, None)["carbohydrates"]
        self.assertEqual((None, [], None), (
            unknown["during"], unknown["before"], unknown["weight"]
        ))

    def test_weight_and_its_source_reach_the_carbohydrates(self):
        weight = {"value": 70, "source": "Garmin"}
        carbohydrates = race_plan(HALF, weight)["carbohydrates"]
        self.assertEqual({"kg": 70, "source": "Garmin"}, carbohydrates["weight"])
        self.assertEqual([700, 840], carbohydrates["before"][0]["grams"])
        self.assertEqual("Thomas, Erdman und Burke 2016", carbohydrates["source"])

    def test_read_race_plan_reads_the_competition_and_tolerates_no_weight(self):
        competitions = Mock()
        competitions.get.side_effect = {"race-1": HALF}.get
        performance = Mock()
        performance.performance_state.return_value = {
            "performance": {"metrics": {"weight_kg": {"value": 70, "source": "Profil"}}}
        }
        plan = read_race_plan(lambda: competitions, lambda: performance, "race-1")
        self.assertEqual("Profil", plan["carbohydrates"]["weight"]["source"])
        self.assertIsNone(read_race_plan(lambda: competitions, lambda: performance, "x"))
        performance.performance_state.side_effect = AppError(503, "busy")
        with self.assertLogs("intervals_coach", "WARNING"):
            plan = read_race_plan(lambda: competitions, lambda: performance, "race-1")
        self.assertIsNone(plan["carbohydrates"]["weight"])


if __name__ == "__main__":
    unittest.main()
