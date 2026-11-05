"""Subjective ratings carry their scale, direction and source (issue #1671)."""

import unittest
from typing import Any, ClassVar

from backend.activities.detail_summary_metrics import intervals_summary_metrics
from backend.athlete.checkins import CHECKIN_SCORE_FIELDS
from backend.canonical.rating_scales import (
    INTERVALS_FEEL_SCALE,
    INTERVALS_RPE_SCALE,
    INTERVALS_WELLNESS_SCALES,
    LOCAL_CHECKIN_SCALES,
    LOCAL_SESSION_RPE_SCALE,
    RatingScale,
)
from backend.canonical.vocabulary import MetricKind, RecordingOrigin
from backend.coach.context import COACH_ACTIVITY_FIELDS
from backend.coach.prompt import COACH_PROMPT
from backend.performance.context import SUBJECTIVE_RATINGS
from backend.performance.session_rpe_load import session_load
from backend.planning.context import CHECKIN_FIELDS


class RatingScaleTests(unittest.TestCase):
    def test_intervals_feel_labels_and_normalizes_strong_to_weak(self) -> None:
        self.assertEqual("stark", INTERVALS_FEEL_SCALE.label(1))
        self.assertEqual(0.0, INTERVALS_FEEL_SCALE.normalized(1))
        self.assertEqual("schwach", INTERVALS_FEEL_SCALE.label(5))
        self.assertEqual(1.0, INTERVALS_FEEL_SCALE.normalized(5))

    def test_intervals_mood_and_checkin_stress_both_point_to_worse(self) -> None:
        mood = INTERVALS_WELLNESS_SCALES[MetricKind.SUBJECTIVE_MOOD]
        stress = LOCAL_CHECKIN_SCALES["stress"]
        self.assertEqual("mies", mood.label(4))
        self.assertEqual(1.0, mood.normalized(4))
        self.assertAlmostEqual(0.8, stress.normalized(8))
        self.assertNotEqual(mood.scale_id, stress.scale_id)

    def test_higher_motivation_is_better(self) -> None:
        motivation = LOCAL_CHECKIN_SCALES["motivation"]
        self.assertEqual(0.0, motivation.normalized(10))
        self.assertEqual(1.0, motivation.normalized(0))

    def test_every_intervals_wellness_rating_runs_one_to_four_higher_worse(
        self,
    ) -> None:
        for kind in (kind for _key, kind in SUBJECTIVE_RATINGS):
            scale = INTERVALS_WELLNESS_SCALES[kind]
            self.assertEqual(
                (1, 4, "worse"), (scale.minimum, scale.maximum, scale.higher_is)
            )

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

    def test_rule_names_the_intervals_scales_with_best_at_one(self) -> None:
        wellness = [
            INTERVALS_WELLNESS_SCALES[kind] for _key, kind in SUBJECTIVE_RATINGS
        ]
        self.assertEqual(
            {("1–4", "worse")}, {(_range(s), s.higher_is) for s in wellness}
        )
        keys = "/".join(key for key, _kind in SUBJECTIVE_RATINGS)
        self.assertIn(f"Intervals.icu recovery {keys} 1–4", self.RULE)
        self.assertEqual("worse", INTERVALS_FEEL_SCALE.higher_is)
        self.assertIn(f"activity feel {_range(INTERVALS_FEEL_SCALE)}", self.RULE)
        self.assertIn("run from 1 = best", self.RULE)
        self.assertIn(f"activity rpe {_range(INTERVALS_RPE_SCALE)}", self.RULE)

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


class DetailMetricTests(unittest.TestCase):
    def test_rpe_and_feel_are_athlete_entered_with_their_scale(self) -> None:
        metrics = intervals_summary_metrics(
            {"icu_rpe": 7, "feel": 1, "calories": 500},
            recorded_by=RecordingOrigin.GARMIN,
        )
        self.assertEqual("athlete_entered", metrics["rpe"]["source"]["kind"])
        self.assertEqual("athlete_entered", metrics["feel"]["source"]["kind"])
        self.assertEqual("measured", metrics["calories_kcal"]["source"]["kind"])
        self.assertEqual(
            "1–5, höher = schlechter (1 stark … 5 schwach)", metrics["feel"]["scale"]
        )
        self.assertEqual("stark", metrics["feel"]["rating_label"])
        self.assertEqual(0.0, metrics["feel"]["normalized_0_1"])
        self.assertIn("höher = härter", metrics["rpe"]["scale"])
        self.assertNotIn("scale", metrics["calories_kcal"])
        self.assertNotIn("rating_label", metrics["rpe"])

    def test_off_scale_rating_keeps_value_and_scale_without_label(self) -> None:
        metrics = intervals_summary_metrics(
            {"feel": 0}, recorded_by=RecordingOrigin.GARMIN
        )
        self.assertEqual(0, metrics["feel"]["value"])
        self.assertIn("scale", metrics["feel"])
        self.assertNotIn("normalized_0_1", metrics["feel"])


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
