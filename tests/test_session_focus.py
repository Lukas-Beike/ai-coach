"""Session focus: validation, fallback order, checks, history and export."""

from __future__ import annotations

import re
import unittest
from datetime import date
from pathlib import Path

from backend import change_history
from backend.activities.workout_load import StepEstimate, WorkoutEstimate
from backend.canonical.vocabulary import Sport
from backend.errors import AppError
from backend.planning import plan_checks
from backend.planning.changes import prepare_structured_training_change
from backend.planning.library import normalize_library_workout
from backend.planning.plan_guard_service import planned_focus
from backend.planning.planned_units import (
    normalize_planned_unit,
    planned_unit_payload_hash,
    planned_workout_update_candidate,
)
from backend.planning.session_focus import (
    ALL_FOCI,
    SessionFocus,
    allowed_foci,
    carry_focus,
    session_focus,
    unambiguous_values,
)
from backend.planning.workout_export import build_planned_workout_export
from backend.planning.workouts import normalize_workout
from backend.providers.intervals_workouts import intervals_event_payload

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 2)
LOCAL_ID = "12345678-1234-5678-1234-567812345678"


def unit(sport="Run", **extra):
    return {
        "date": "2026-11-03",
        "sport": sport,
        "name": extra.pop("name", "Einheit"),
        "description": extra.pop("description", "- 30m Z2"),
        "duration_minutes": 30,
        "target": "AUTO",
        **extra,
    }


def planned(sport="Run", **extra):
    return normalize_planned_unit(unit(sport, **extra), local_id=LOCAL_ID)


class NormalizationTests(unittest.TestCase):
    def test_focus_is_validated_per_sport(self):
        stored = planned("Run", session_focus="Tempo")
        self.assertEqual(stored["session_focus"], "tempo")
        stored = planned("Ride", session_focus="sweet_spot")
        self.assertEqual(stored["session_focus"], "sweet_spot")
        self.assertEqual(allowed_foci(Sport.SWIM), ())
        for sport, focus in (
            ("Run", "sweet_spot"),
            ("Run", "legs"),
            ("WeightTraining", "tempo"),
            ("Swim", "easy"),
            ("Run", "bogus"),
        ):
            with self.subTest(sport=sport, focus=focus), self.assertRaises(AppError):
                planned(sport, session_focus=focus)

    def test_strength_intensity_only_on_strength(self):
        stored = planned(
            "WeightTraining", session_focus="legs", strength_intensity="heavy"
        )
        self.assertEqual(stored["strength_intensity"], "heavy")
        for sport, value in (("Run", "heavy"), ("WeightTraining", "extreme")):
            with self.subTest(sport=sport), self.assertRaises(AppError):
                planned(sport, strength_intensity=value)

    def test_empty_values_are_removed_and_templates_keep_the_focus(self):
        stored = planned("Run", session_focus=" ", strength_intensity=None)
        self.assertNotIn("session_focus", stored)
        template = normalize_library_workout(
            {**unit("WeightTraining"), "date": None, "session_focus": "full_body"}
        )
        self.assertEqual(template["session_focus"], "full_body")

    def test_update_sets_clears_and_drops_focus_on_sport_change(self):
        current = planned("Run", session_focus="tempo")
        set_to = planned_workout_update_candidate(
            current, "update", {"session_focus": "long"}
        )
        self.assertEqual(set_to["session_focus"], "long")
        cleared = planned_workout_update_candidate(
            current, "update", {"session_focus": None}
        )
        self.assertNotIn("session_focus", normalize_planned_unit(cleared))
        resent = planned_workout_update_candidate(
            current, "update", {"sport": "Run", "description": "- 20m Z2"}
        )
        self.assertEqual(resent["session_focus"], "tempo")
        moved = planned_workout_update_candidate(
            current, "update", {"sport": "WeightTraining"}
        )
        self.assertNotIn("session_focus", moved)


class FallbackTests(unittest.TestCase):
    def test_set_focus_is_set_and_keywords_are_derived(self):
        self.assertEqual(
            session_focus(planned("Run", session_focus="easy")),
            SessionFocus("easy", None, "set"),
        )
        cases = (
            ("WeightTraining", "Leg Day", "legs"),
            ("WeightTraining", "3×5 Squats", "legs"),
            ("WeightTraining", "Beintag", "legs"),
            ("WeightTraining", "Bulgarian split squat, hip thrust", "legs"),
            ("WeightTraining", "Bankdrücken, Klimmzug", "upper"),
            ("WeightTraining", "Squats und Bankdrücken", "full_body"),
            ("WeightTraining", "Box jumps", "plyometrics"),
            ("Run", "Schwelle 3×10 min", "threshold"),
            ("Run", "Intervalle", "vo2max"),
            ("Run", "Regeneration", "recovery"),
            ("Run", "Grundlage", "endurance"),
            ("Ride", "Locker rollen", "easy"),
        )
        for sport, text, expected in cases:
            with self.subTest(text=text):
                found = session_focus(unit(sport, name=text, description=""))
                self.assertEqual((found.value, found.origin), (expected, "derived"))

    def test_name_focus_wins_and_negated_legs_do_not_count(self):
        # The athlete's unit of 2026-11-09 (#1802): derived as full body before.
        upper = unit(
            "WeightTraining",
            name="Krafttraining Oberkörper",
            description=(
                "Oberkörper moderat: Schrägbankdrücken, Lat Pulldown, Face Pulls, "
                "Dips, Rudern, Seitheben und Bizeps. Kein Muskelversagen; "
                "Beine schonen."
            ),
        )
        self.assertEqual(
            session_focus(upper),
            SessionFocus("upper", "moderate", "derived", "derived"),
        )
        self.assertFalse(session_focus(upper).is_leg_strength)
        cases = (
            ("Kraft", "Bankdrücken, Rudern, ohne Beine", "upper"),
            ("Kraft", "Bankdrücken; kein Beintraining heute", "upper"),
            ("Strength", "Bench press, rows, no legs", "upper"),
            ("Krafttraining Unterkörper", "Kniebeuge, dazu Rudern", "legs"),
            ("Ganzkörper", "Bankdrücken", "full_body"),
            ("Kraft", "Kniebeuge und Rudern", "full_body"),
        )
        for name, text, expected in cases:
            with self.subTest(text=text):
                found = session_focus(
                    unit("WeightTraining", name=name, description=text)
                )
                self.assertEqual(found.value, expected)

    def test_strength_intensity_from_text_without_a_structure(self):
        cases = (
            ("Kraft schwer", "", "heavy"),
            ("Kraft", "Oberkörper moderat", "moderate"),
            ("Kraft leicht", "", "light"),
            ("Kraft", "nicht schwer, Technik", None),
            ("Kraft", "3x10", None),
        )
        for name, text, expected in cases:
            with self.subTest(name=name, text=text):
                found = session_focus(
                    unit("WeightTraining", name=name, description=text)
                )
                self.assertEqual(found.strength_intensity, expected)
                self.assertEqual(
                    found.intensity_origin, None if expected is None else "derived"
                )
        # A set intensity still wins over the text.
        found = session_focus(
            unit("WeightTraining", name="Kraft schwer", strength_intensity="light")
        )
        self.assertEqual(
            (found.strength_intensity, found.intensity_origin), ("light", "set")
        )

    def test_generic_words_do_not_derive_a_hard_focus(self):
        for text in ("Z2 bei 60% FTP", "Sync mit Intervals.icu", "easy Z2"):
            with self.subTest(text=text):
                found = session_focus(unit("Ride", name="Ausfahrt", description=text))
                self.assertNotIn(found.value, ("threshold", "vo2max"))

    def test_remote_payload_keeps_only_a_fitting_focus(self):
        remote = planned("Run")
        carry_focus(remote, {"session_focus": "long"})
        self.assertEqual(remote["session_focus"], "long")
        strength = planned("WeightTraining")
        carry_focus(strength, {"session_focus": "long"})
        self.assertNotIn("session_focus", strength)

    def test_unknown_stays_unknown(self):
        self.assertEqual(
            session_focus(unit("Run", name="Lauf", description="")), SessionFocus()
        )
        self.assertEqual(session_focus(unit("Swim", name="Tempo")), SessionFocus())

    def test_parsed_steps_come_before_keywords(self):
        def step(zone, seconds):
            return StepEstimate(
                "work", "power", seconds, None, 1.0, zone, "high", None, None
            )

        def estimate(*steps, duration=1800.0, intensity=0.9):
            return WorkoutEstimate(
                "ride", steps, duration, None, None, intensity, None, None, (), {}
            )

        locker = unit("Ride", name="Locker", description="")
        cases = (
            (estimate(step(4, 1200)), "threshold"),
            (estimate(step(5, 600)), "vo2max"),
            (estimate(step(3, 1500)), "tempo"),
            (estimate(step(2, 6000), duration=6000.0, intensity=0.6), "long"),
            (estimate(step(2, 1800), intensity=0.6), "easy"),
        )
        for found, expected in cases:
            with self.subTest(expected=expected):
                focus = session_focus(locker, found)
                self.assertEqual((focus.value, focus.origin), (expected, "derived"))
        # Unresolved intensity falls through to the keywords.
        unresolved = estimate(step(None, 1800), intensity=None)
        self.assertEqual(session_focus(locker, unresolved).value, "easy")

    def test_leg_helper_for_followup_checks(self):
        self.assertTrue(SessionFocus("legs", "heavy", "set").is_leg_strength)
        self.assertTrue(SessionFocus("plyometrics", None, "set").is_leg_strength)
        self.assertFalse(SessionFocus("upper", None, "set").is_leg_strength)


class FrontendParityTests(unittest.TestCase):
    def test_labels_cover_every_focus(self):
        source = (ROOT / "public" / "plan-views.js").read_text(encoding="utf-8")
        labels = source.split("const FOCUS_LABELS = {", 1)[1].split("};", 1)[0]
        self.assertEqual(set(re.findall(r"(\w+):", labels)), set(ALL_FOCI))


class CheckTests(unittest.TestCase):
    def test_set_focus_decides_hardness_before_text(self):
        easy = unit(
            "Run", name="Locker", description="Z4 Intervalle", session_focus="easy"
        )
        self.assertFalse(plan_checks.is_hard(easy))
        self.assertTrue(plan_checks.is_hard(unit("Run", session_focus="threshold")))
        self.assertTrue(plan_checks.is_hard(unit("Ride", session_focus="sweet_spot")))
        self.assertFalse(plan_checks.is_hard(unit("Run", session_focus="long")))

    def test_derived_keyword_focus_marks_hard_without_other_evidence(self):
        self.assertTrue(
            plan_checks.is_hard(unit("Run", name="Schwelle 3×10", description=""))
        )

    def test_back_to_back_uses_the_focus(self):
        units = [
            {**unit("Run", session_focus="vo2max"), "local_id": "a"},
            {
                **unit("Ride", session_focus="race"),
                "local_id": "b",
                "date": "2026-11-04",
            },
        ]
        findings = plan_checks.check_plan(
            today=TODAY, units=units, completed=[], competitions=[]
        )
        self.assertIn("back_to_back_hard", [f["code"] for f in findings])

    def test_strength_intensity_decides_heavy_before_text(self):
        light = unit(
            "WeightTraining",
            description="schwer 5RM",
            session_focus="legs",
            strength_intensity="light",
        )
        heavy = unit("WeightTraining", description="3x10", strength_intensity="heavy")
        self.assertFalse(plan_checks.is_heavy_strength(light))
        self.assertTrue(plan_checks.is_heavy_strength(heavy))
        findings = plan_checks.check_plan(
            today=TODAY,
            units=[
                {**heavy, "local_id": "s"},
                {**unit("Run", session_focus="threshold"), "local_id": "r"},
            ],
            completed=[],
            competitions=[],
        )
        self.assertIn("strength_hard_same_day", [f["code"] for f in findings])

    def test_planning_brief_lists_focus_with_origin(self):
        units = [
            {**unit("Run", session_focus="easy"), "local_id": "a"},
            {**unit("WeightTraining", name="Beintag", description=""), "local_id": "b"},
        ]
        rows = planned_focus(units, lambda _unit: None, TODAY)  # type: ignore[arg-type,return-value]
        self.assertEqual(
            [(r["session_focus"], r["focus_origin"]) for r in rows],
            [("easy", "set"), ("legs", "derived")],
        )


class CoachAndHistoryTests(unittest.TestCase):
    def test_coach_create_and_plan_draft_round_trip(self):
        change = prepare_structured_training_change(
            {
                "action": "create",
                **unit("Run"),
                "rationale": "Aufbau",
                "session_focus": "tempo",
            },
            today=TODAY,
        )
        self.assertEqual(change["session_focus"], "tempo")
        draft = normalize_workout(
            {
                **unit("WeightTraining"),
                "rationale": "x",
                "session_focus": "legs",
                "strength_intensity": "moderate",
            },
            today=TODAY,
        )
        stored = normalize_planned_unit(draft, local_id=LOCAL_ID)
        self.assertEqual(
            (stored["session_focus"], stored["strength_intensity"]),
            ("legs", "moderate"),
        )
        with self.assertRaises(AppError):
            normalize_workout(
                {**unit("Run"), "rationale": "x", "session_focus": "legs"},
                today=TODAY,
            )

    def test_history_projection_covers_the_fields(self):
        stored = planned(
            "WeightTraining", session_focus="legs", strength_intensity="heavy"
        )
        for entity in ("planned_unit", "workout_library"):
            projected = change_history.audit_projection(entity, stored)
            self.assertEqual(projected["session_focus"], "legs")
            self.assertEqual(projected["strength_intensity"], "heavy")
        before = change_history.audit_projection(
            "planned_unit", planned("WeightTraining")
        )
        after = change_history.audit_projection("planned_unit", stored)
        diff = change_history.audit_diff(before, after)
        self.assertIn("session_focus", diff["fields"])

    def test_focus_does_not_change_remote_comparison_hash(self):
        self.assertEqual(
            planned_unit_payload_hash(planned("Run")),
            planned_unit_payload_hash(planned("Run", session_focus="tempo")),
        )


class ExportTests(unittest.TestCase):
    def test_export_payload_is_unchanged_by_the_focus(self):
        def event(sport="Run", **extra):
            stored = planned(sport, date=TODAY.isoformat(), **extra)
            return intervals_event_payload(
                LOCAL_ID, build_planned_workout_export(stored, today=TODAY)
            )

        self.assertEqual(event(), event(session_focus="tempo"))
        self.assertEqual(
            event("WeightTraining", description="3x8 Kniebeuge"),
            event(
                "WeightTraining",
                description="3x8 Kniebeuge",
                session_focus="legs",
                strength_intensity="heavy",
            ),
        )


class UnambiguousValuesTests(unittest.TestCase):
    @staticmethod
    def step(zone, seconds):
        return StepEstimate(
            "work", "power", seconds, None, 1.0, zone, "high", None, None
        )

    def estimate(self, *steps, duration=1800.0, intensity=0.9):
        return WorkoutEstimate(
            "ride", steps, duration, None, None, intensity, None, None, (), {}
        )

    def test_one_keyword_is_unambiguous_several_are_not(self):
        self.assertEqual(
            unambiguous_values(unit("Run", name="Lockerer Lauf", description="")),
            {"session_focus": "easy"},
        )
        for name in ("Schwelle und Intervalle", "Lange Grundlage", "Tempo, Schwelle"):
            with self.subTest(name):
                self.assertEqual(
                    unambiguous_values(unit("Run", name=name, description="")), {}
                )
        self.assertEqual(
            unambiguous_values(unit("Run", name="Lauf", description="")), {}
        )

    def test_steps_decide_unless_the_text_names_only_other_foci(self):
        locker = unit("Ride", name="Locker", description="")
        threshold = self.estimate(self.step(4, 1200))
        self.assertEqual(
            unambiguous_values(unit("Ride", name="Fahrt", description=""), threshold),
            {"session_focus": "threshold"},
        )
        # Steps and text agree.
        self.assertEqual(
            unambiguous_values(
                unit("Ride", name="Schwelle 4x8", description=""), threshold
            ),
            {"session_focus": "threshold"},
        )
        # Steps say threshold, the text says easy: contested.
        self.assertEqual(unambiguous_values(locker, threshold), {})

    def test_stored_and_unsupported_values_are_left_alone(self):
        self.assertEqual(
            unambiguous_values(
                unit("Run", name="Lockerer Lauf", description="", session_focus="long")
            ),
            {},
        )
        self.assertEqual(unambiguous_values(unit("Swim", name="Locker")), {})

    def test_strength_focus_and_intensity_need_one_answer(self):
        legs = unit("WeightTraining", name="Kniebeuge schwer", description="")
        self.assertEqual(
            unambiguous_values(legs),
            {"session_focus": "legs", "strength_intensity": "heavy"},
        )
        # Legs plus upper body is the one defined full-body case.
        mixed = unit("WeightTraining", name="Kniebeuge und Bankdrücken", description="")
        self.assertEqual(unambiguous_values(mixed), {"session_focus": "full_body"})
        # Two unrelated groups, or two intensities, stay a suggestion.
        for name in ("Beine und Core", "Kniebeuge leicht bis schwer"):
            with self.subTest(name):
                result = unambiguous_values(
                    unit("WeightTraining", name=name, description="")
                )
                self.assertNotIn(
                    "strength_intensity" if "leicht" in name else "session_focus",
                    result,
                )
        # The intensity is filled on its own when the focus is already stored.
        self.assertEqual(
            unambiguous_values(
                unit("WeightTraining", name="Core leicht", session_focus="core")
            ),
            {"strength_intensity": "light"},
        )
        self.assertEqual(
            unambiguous_values(
                unit(
                    "WeightTraining",
                    name="Core",
                    session_focus="core",
                    strength_intensity="heavy",
                )
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
