"""Subjective ratings carry their scale, direction and source (issue #1671)."""

import unittest
from typing import Any, ClassVar

from backend.athlete.checkins import CHECKIN_SCORE_FIELDS
from backend.canonical.rating_scales import (
    GARMIN_FEEL_SCALE,
    GARMIN_RPE_SCALE,
    INTERVALS_FEEL_SCALE,
    INTERVALS_RPE_SCALE,
    LOCAL_CHECKIN_SCALES,
    LOCAL_SESSION_RPE_SCALE,
    RatingScale,
)
from backend.coach.context import COACH_ACTIVITY_FIELDS
from backend.coach.prompt import COACH_PROMPT
from backend.performance.session_rpe_load import session_load
from backend.planning.context import CHECKIN_FIELDS


class RatingScaleTests(unittest.TestCase):
    def test_intervals_feel_labels_and_normalizes_strong_to_weak(self) -> None:
        self.assertEqual("stark", INTERVALS_FEEL_SCALE.label(1))
        self.assertEqual(0.0, INTERVALS_FEEL_SCALE.normalized(1))
        self.assertEqual("schwach", INTERVALS_FEEL_SCALE.label(5))
        self.assertEqual(1.0, INTERVALS_FEEL_SCALE.normalized(5))

    def test_checkin_stress_points_to_worse(self) -> None:
        stress = LOCAL_CHECKIN_SCALES["stress"]
        self.assertAlmostEqual(0.8, stress.normalized(8))

    def test_higher_motivation_is_better(self) -> None:
        motivation = LOCAL_CHECKIN_SCALES["motivation"]
        self.assertEqual(0.0, motivation.normalized(10))
        self.assertEqual(1.0, motivation.normalized(0))

    def test_rejects_values_and_labels_outside_the_scale(self) -> None:
        with self.assertRaises(ValueError):
            INTERVALS_FEEL_SCALE.normalized(0)
        with self.assertRaises(ValueError):
            RatingScale("bad", 1, 4, "worse", {5: "x"})
        with self.assertRaises(ValueError):
            RatingScale("bad", 4, 1, "worse")

    def test_label_of_a_fraction_is_none(self) -> None:
        self.assertIsNone(INTERVALS_FEEL_SCALE.label(2.5))


def _range(scale: RatingScale) -> str:
    return f"{scale.minimum}–{scale.maximum}"


class CoachRuleTests(unittest.TestCase):
    """Rule 8h states the canonical scales of every rating the Coach reads."""

    RULE = COACH_PROMPT[COACH_PROMPT.index("8h. ") :].splitlines()[0]

    def test_rule_names_the_garmin_scales_with_best_at_one(self) -> None:
        # The Intervals.icu ratings are no Coach input any more (#1728).
        self.assertNotIn("recovery fatigue/soreness/stress/mood", self.RULE)
        self.assertNotIn("Intervals", self.RULE)
        self.assertEqual("worse", GARMIN_FEEL_SCALE.higher_is)
        self.assertIn(f"activity rpe {_range(GARMIN_RPE_SCALE)}", self.RULE)
        self.assertIn(f"feel {_range(GARMIN_FEEL_SCALE)} (1 = best)", self.RULE)

    def test_rule_names_the_local_scales_and_directions(self) -> None:
        soreness, stress = (
            LOCAL_CHECKIN_SCALES["soreness"],
            LOCAL_CHECKIN_SCALES["stress"],
        )
        motivation = LOCAL_CHECKIN_SCALES["motivation"]
        self.assertEqual(
            ("worse", "worse", "better"),
            (soreness.higher_is, stress.higher_is, motivation.higher_is),
        )
        self.assertIn("check-in soreness/stress 0–10 higher = worse", self.RULE)
        self.assertIn("motivation 0–10 higher = better", self.RULE)
        self.assertIs(LOCAL_CHECKIN_SCALES["session_rpe"], LOCAL_SESSION_RPE_SCALE)
        self.assertIn(
            f"check-in and feedback session_rpe {_range(LOCAL_SESSION_RPE_SCALE)}",
            self.RULE,
        )

    def test_rule_covers_every_rating_field_and_forbids_comparing_scales(self) -> None:
        self.assertTrue({"rpe", "feel"} <= set(COACH_ACTIVITY_FIELDS))
        self.assertTrue(set(CHECKIN_SCORE_FIELDS) <= set(CHECKIN_FIELDS))
        for field in set(CHECKIN_SCORE_FIELDS) | {"rpe", "feel"}:
            self.assertIn(field, self.RULE)
        self.assertIn("athlete-entered, not measured", self.RULE)
        self.assertIn("Never compare ratings of different scales", self.RULE)


class SessionRpeScaleTests(unittest.TestCase):
    SUMMARY: ClassVar[dict[str, Any]] = {
        "id": "act_1",
        "started_at": "2026-11-01T08:00:00+00:00",
        "started_at_local": "2026-11-01T09:00:00",
        "elapsed_duration_s": 3600,
        "rpe": 6,
        "sources": {"rpe": "Intervals.icu"},
    }

    def test_local_rpe_load_is_unchanged_and_names_its_scale(self) -> None:
        entry, value = session_load(self.SUMMARY, {"session_rpe": 5})
        self.assertEqual(300.0, value)
        self.assertEqual(LOCAL_SESSION_RPE_SCALE.scale_id, entry["rpe_scale"])

    def test_provider_rpe_names_the_intervals_scale(self) -> None:
        entry, value = session_load(self.SUMMARY, None)
        self.assertEqual(360.0, value)
        self.assertEqual(INTERVALS_RPE_SCALE.scale_id, entry["rpe_scale"])

    def test_unrated_session_has_no_scale(self) -> None:
        entry, value = session_load({**self.SUMMARY, "rpe": None}, None)
        self.assertIsNone(value)
        self.assertIsNone(entry["rpe_scale"])


if __name__ == "__main__":
    unittest.main()
