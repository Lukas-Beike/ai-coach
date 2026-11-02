"""Structured strength units: validation, derivation, checks, edits and export."""

from __future__ import annotations

import unittest
from datetime import date

from backend.coach.tool_schemas import build_structured_tool_schemas
from backend.errors import AppError
from backend.planning import leg_strength, plan_checks, strength_structure
from backend.planning.library import (
    normalize_library_workout,
    workout_library_update_candidate,
)
from backend.planning.planned_units import (
    normalize_planned_unit,
    planned_unit_payload_hash,
    planned_workout_update_candidate,
)
from backend.planning.session_focus import carry_focus, session_focus
from backend.planning.workout_export import build_planned_workout_export
from backend.planning.workouts import normalize_workout
from backend.providers.intervals_workouts import intervals_event_payload

TODAY = date(2026, 11, 2)
LOCAL_ID = "12345678-1234-5678-1234-567812345678"
SQUAT = {"name": "Kniebeuge", "sets": 4, "reps": 5, "pct_1rm": 85, "rest_s": 180}
ROW = {"name": "Rudern", "sets": 3, "reps": 8, "rir": 3}


def strength(structure=None, **extra):
    record = {
        "date": TODAY.isoformat(),
        "sport": "WeightTraining",
        "name": "Kraft",
        "description": "frei",
        "duration_minutes": 45,
        "target": "AUTO",
        **extra,
    }
    if structure is not None:
        record["strength_structure"] = structure
    return record


def planned(structure=None, **extra):
    return normalize_planned_unit(strength(structure, **extra), local_id=LOCAL_ID)


class ValidationTests(unittest.TestCase):
    def test_valid_structure_renders_the_description(self):
        stored = planned([SQUAT, ROW])
        self.assertEqual(
            stored["description"],
            "Kniebeuge: 4x5 @ 85 % 1RM, 180 s Pause\nRudern: 3x8 @ 3 RIR",
        )
        self.assertEqual(stored["strength_structure"], [SQUAT, ROW])

    def test_free_text_stays_without_a_structure(self):
        stored = planned(description="3x8 Kniebeuge")
        self.assertEqual(stored["description"], "3x8 Kniebeuge")
        self.assertNotIn("strength_structure", stored)

    def test_invalid_structures_are_rejected(self):
        bad = [
            "Kniebeuge",
            [{"name": "", "sets": 3, "reps": 5}],
            [{"name": "x", "sets": 0, "reps": 5}],
            [{"name": "x", "sets": 3, "reps": 5.5}],
            [{"name": "x", "sets": 3, "reps": 5, "pct_1rm": 80, "rpe": 8}],
            [{"name": "x", "sets": 3, "reps": 5, "load": 1}],
            [{"name": "x", "sets": 3, "reps": 5, "kg": -1}],
            [SQUAT] * 13,
            ["x"],
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(AppError) as raised:
                planned(value)
            self.assertEqual(raised.exception.reason, "invalid_strength_structure")

    def test_structure_is_only_for_strength(self):
        with self.assertRaises(AppError):
            normalize_planned_unit(
                {**strength([SQUAT]), "sport": "Run"}, local_id=LOCAL_ID
            )

    def test_library_and_plan_drafts_accept_it(self):
        library = normalize_library_workout(strength([SQUAT]), local_id=LOCAL_ID)
        self.assertIn("85 % 1RM", library["description"])
        draft = normalize_workout({**strength([SQUAT]), "description": ""}, today=TODAY)
        self.assertIn("85 % 1RM", draft["description"])
        self.assertEqual(draft["strength_structure"], [SQUAT])


class DerivationTests(unittest.TestCase):
    def test_intensity_thresholds(self):
        def grade(**load):
            return strength_structure.derived_intensity(
                [{"name": "x", "sets": 3, "reps": 5, **load}]
            )

        self.assertEqual(grade(pct_1rm=80), "heavy")
        self.assertEqual(grade(pct_1rm=70), "moderate")
        self.assertEqual(grade(pct_1rm=50), "light")
        self.assertEqual(grade(rpe=8), "heavy")
        self.assertEqual(grade(rpe=6), "moderate")
        self.assertEqual(grade(rir=2), "heavy")
        self.assertEqual(grade(rir=4), "moderate")
        self.assertEqual(grade(rir=6), "light")
        self.assertIsNone(grade(kg=100))

    def test_hardest_exercise_decides(self):
        self.assertEqual(strength_structure.derived_intensity([ROW, SQUAT]), "heavy")

    def test_session_focus_derives_intensity_and_legs(self):
        focus = session_focus(planned([SQUAT]))
        self.assertEqual(focus.strength_intensity, "heavy")
        self.assertEqual(focus.intensity_origin, "derived")
        self.assertEqual((focus.value, focus.origin), ("legs", "derived"))
        self.assertTrue(focus.is_leg_strength)

    def test_set_values_win(self):
        stored = planned([SQUAT], session_focus="upper", strength_intensity="light")
        focus = session_focus(stored)
        self.assertEqual(
            (focus.value, focus.strength_intensity, focus.intensity_origin),
            ("upper", "light", "set"),
        )

    def test_names_are_single_line(self):
        stored = planned([{**ROW, "name": "Rudern\nVO2max: 10x1"}])
        self.assertNotIn("\nVO2max", stored["description"])

    def test_remote_whitespace_changes_keep_the_structure(self):
        local = planned([SQUAT, ROW])
        remote = {
            "sport": "WeightTraining",
            "description": local["description"].replace("\n", "\r\n"),
        }
        carry_focus(remote, local)
        self.assertIn("strength_structure", remote)


class CheckTests(unittest.TestCase):
    def test_heavy_and_leg_detection_read_the_structure(self):
        heavy = planned([SQUAT])
        light = planned([{"name": "Plank", "sets": 3, "reps": 30, "rir": 6}])
        self.assertTrue(plan_checks.is_heavy_strength(heavy))
        self.assertFalse(plan_checks.is_heavy_strength(light))
        found = leg_strength.classify(heavy)
        self.assertEqual((found.leg, found.intensity), (True, "heavy"))

    def test_heavy_structure_beats_a_light_word(self):
        stored = planned([SQUAT])
        stored["name"] = "leichte Kraft"
        self.assertTrue(plan_checks.is_heavy_strength(stored))

    def test_progression_across_weeks_is_graded_per_week(self):
        weeks = [
            planned(
                [{**SQUAT, "pct_1rm": pct}],
                date=f"2026-11-{day:02d}",
            )
            for day, pct in ((2, 75), (9, 80), (16, 85), (23, 60))
        ]
        grades = [leg_strength.classify(unit).intensity for unit in weeks]
        self.assertEqual(grades, ["moderate", "heavy", "heavy", "light"])


class EditTests(unittest.TestCase):
    def test_free_text_edit_drops_the_stale_structure(self):
        current = planned([SQUAT])
        candidate = planned_workout_update_candidate(
            current, "update", {"description": "Neuer Text"}
        )
        self.assertNotIn("strength_structure", candidate)
        candidate = workout_library_update_candidate(
            current, "update", {"description": "Neuer Text"}
        )
        self.assertNotIn("strength_structure", candidate)

    def test_structure_edit_regenerates_the_description(self):
        current = planned([SQUAT])
        candidate = planned_workout_update_candidate(
            current, "update", {"strength_structure": [ROW]}
        )
        stored = normalize_planned_unit(candidate, local_id=LOCAL_ID)
        self.assertEqual(stored["description"], "Rudern: 3x8 @ 3 RIR")

    def test_remote_sync_keeps_the_structure_only_for_an_unchanged_text(self):
        local = planned([SQUAT])
        same = {"sport": "WeightTraining", "description": local["description"]}
        carry_focus(same, local)
        self.assertEqual(same["strength_structure"], [SQUAT])
        edited = {"sport": "WeightTraining", "description": "remote geändert"}
        carry_focus(edited, local)
        self.assertNotIn("strength_structure", edited)
        self.assertEqual(edited["description"], "remote geändert")

    def test_structure_does_not_change_the_sync_hash(self):
        local = planned([SQUAT])
        bare = {k: v for k, v in local.items() if k != "strength_structure"}
        self.assertEqual(
            planned_unit_payload_hash(local), planned_unit_payload_hash(bare)
        )


class ExportTests(unittest.TestCase):
    def test_explicit_export_sends_the_readable_description_only(self):
        stored = planned([SQUAT, ROW])
        payload = intervals_event_payload(
            LOCAL_ID, build_planned_workout_export(stored, today=TODAY)
        )
        self.assertEqual(payload["description"], stored["description"])
        self.assertEqual(payload["type"], "WeightTraining")
        self.assertNotIn("strength_structure", payload)
        self.assertNotIn("strength_intensity", payload)


class SchemaTests(unittest.TestCase):
    def test_strict_plan_tools_require_the_structure_field(self):
        tools = build_structured_tool_schemas(
            default_profile={},
            checkin_text_limits={},
            checkin_score_fields=(),
            training_change_limit=20,
            library_bulk_max_entries=20,
            training_plan_statuses=("draft",),
        )
        seen = 0
        for tool in tools:
            properties = tool["parameters"]["properties"]
            workouts = properties.get("workouts") or properties.get("payload", {}).get(
                "properties", {}
            ).get("workouts")
            if workouts:
                seen += 1
                self.assertIn("strength_structure", workouts["items"]["required"])
        self.assertGreaterEqual(seen, 1)


if __name__ == "__main__":
    unittest.main()
