"""Sport and environment classification, including legacy activity_kind parity."""

from __future__ import annotations

import unittest
from itertools import product
from typing import Any

from backend.activities.identity import activity_kind
from backend.canonical.sports import (
    classify_environment_text,
    classify_sport_text,
    legacy_activity_family,
)
from backend.canonical.vocabulary import Environment, Sport


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


def legacy_family(text: str) -> str:
    """Local copy of the legacy activity_kind term logic for one string."""
    value = text.casefold()
    if any(
        term in value for term in ("ride", "bike", "cycling", "rad", "velo", "bicycle")
    ):
        return "cycling"
    if any(term in value for term in ("run", "lauf", "jog")):
        return "running"
    if any(term in value for term in ("swim", "schwimm")):
        return "swimming"
    if any(term in value for term in ("strength", "kraft", "weight", "gym")):
        return "strength"
    return "other"


SPORT_CASES: tuple[tuple[str, Sport], ...] = (
    # Intervals.icu activity types
    ("Ride", Sport.RIDE),
    ("VirtualRide", Sport.RIDE),
    ("GravelRide", Sport.RIDE),
    ("Run", Sport.RUN),
    ("TrailRun", Sport.RUN),
    ("Swim", Sport.SWIM),
    ("WeightTraining", Sport.STRENGTH),
    ("Walk", Sport.WALK),
    ("Hike", Sport.HIKE),
    ("Rowing", Sport.ROW),
    ("NordicSki", Sport.NORDIC_SKI),
    ("AlpineSki", Sport.ALPINE_SKI),
    ("Yoga", Sport.YOGA),
    ("Workout", Sport.OTHER),
    # Garmin typeKeys
    ("treadmill_running", Sport.RUN),
    ("lap_swimming", Sport.SWIM),
    ("strength_training", Sport.STRENGTH),
    ("indoor_rowing", Sport.ROW),
    ("cross_country_skiing", Sport.NORDIC_SKI),
    ("resort_skiing", Sport.ALPINE_SKI),
    ("walking", Sport.WALK),
    # German
    ("Radfahren", Sport.RIDE),
    ("Laufband", Sport.RUN),
    ("Schwimmen", Sport.SWIM),
    ("Krafttraining", Sport.STRENGTH),
    ("Gehen", Sport.WALK),
    ("Wandern", Sport.HIKE),
    ("Rudern", Sport.ROW),
    # Blank input
    ("", Sport.OTHER),
    ("   ", Sport.OTHER),
)

# Legacy order is a parity requirement, so an earlier term wins over a later one.
LEGACY_ORDER_CASES: tuple[tuple[str, Sport], ...] = (
    ("Run/Ride", Sport.RIDE),
    ("Hike Ride", Sport.RIDE),
    ("Trail Walk Run", Sport.RUN),
    ("Yoga Swim", Sport.SWIM),
    ("Virtual Gym", Sport.STRENGTH),
    # "lauf" is a legacy run term checked before the nordic term "langlauf".
    ("Langlauf", Sport.RUN),
    # "row" is a substring of "crowd"; substring matching is the legacy behaviour.
    ("Crowd", Sport.ROW),
)

ENVIRONMENT_CASES: tuple[tuple[str, Environment], ...] = (
    ("Zwift", Environment.VIRTUAL),
    ("Virtual Ride", Environment.VIRTUAL),
    ("Virtual Indoor Ride", Environment.VIRTUAL),
    ("Indoor Cycling", Environment.INDOOR),
    ("Trainer", Environment.INDOOR),
    ("Treadmill Run", Environment.INDOOR),
    ("Laufband", Environment.INDOOR),
    # OUTDOOR is never inferred from text.
    ("Outdoor Ride", Environment.UNKNOWN),
    ("Morning Ride", Environment.UNKNOWN),
    ("", Environment.UNKNOWN),
)

# Provider labels and German words, plus mixed texts. Several Garmin type keys
# contain no term from the spec list, so they stay OTHER: "road_biking",
# "mountain_biking" (no "bike") and "hiking" (no "hike"). Provider mappers should
# map such type keys explicitly rather than rely on this text fallback.
PARITY_SAMPLES: tuple[str, ...] = (
    "hiking",
    "Ride",
    "VirtualRide",
    "GravelRide",
    "MountainBikeRide",
    "Run",
    "RUN",
    "rUn",
    "TrailRun",
    "VirtualRun",
    "Swim",
    "WeightTraining",
    "Walk",
    "Hike",
    "Rowing",
    "NordicSki",
    "AlpineSki",
    "Yoga",
    "Workout",
    "road_biking",
    "mountain_biking",
    "cycling",
    "treadmill_running",
    "lap_swimming",
    "strength_training",
    "indoor_rowing",
    "walking",
    "resort_skiing",
    "cross_country_skiing",
    "Radfahren",
    "Laufen",
    "Laufband",
    "Schwimmen",
    "Krafttraining",
    "Gehen",
    "Wandern",
    "Rudern",
    "Langlauf",
    "Run/Ride",
    "Ride to Walk",
    "Laufband Kraft",
    "Virtual Gym",
    "Crowd",
    "Rowing Machine",
    "Bike Gym",
    "ZWIFT",
    "unknown",
    "",
    "   ",
)

PARITY_FRAGMENTS: tuple[str, ...] = (
    "ride",
    "bike",
    "run",
    "lauf",
    "swim",
    "kraft",
    "gym",
    "walk",
    "hike",
    "row",
    "nordic",
    "yoga",
    "zwift",
    "x",
    "",
)


class ClassifySportTextTests(unittest.TestCase):
    def test_classifies_provider_labels_and_german_words(self) -> None:
        for text, expected in SPORT_CASES:
            with self.subTest(text=text):
                self.assertIs(expected, classify_sport_text(text))

    def test_legacy_term_order_wins_over_later_terms(self) -> None:
        for text, expected in LEGACY_ORDER_CASES:
            with self.subTest(text=text):
                self.assertIs(expected, classify_sport_text(text))

    def test_matching_is_case_insensitive(self) -> None:
        self.assertIs(Sport.RIDE, classify_sport_text("VIRTUALRIDE"))
        self.assertIs(Sport.RUN, classify_sport_text("tRaIlRuN"))

    def test_non_text_input_is_other_without_raising(self) -> None:
        for value in (None, 42, 1.5, b"Ride", ["Ride"]):
            with self.subTest(value=value):
                self.assertIs(Sport.OTHER, classify_sport_text(untyped(value)))


class ClassifyEnvironmentTextTests(unittest.TestCase):
    def test_names_virtual_and_indoor_environments(self) -> None:
        for text, expected in ENVIRONMENT_CASES:
            with self.subTest(text=text):
                self.assertIs(expected, classify_environment_text(text))

    def test_virtual_term_is_checked_before_indoor(self) -> None:
        self.assertIs(
            Environment.VIRTUAL,
            classify_environment_text("Virtual Indoor Ride"),
        )

    def test_non_text_input_is_unknown_without_raising(self) -> None:
        for value in (None, 0, ("Zwift",)):
            with self.subTest(value=value):
                self.assertIs(
                    Environment.UNKNOWN,
                    classify_environment_text(untyped(value)),
                )


class LegacyActivityFamilyTests(unittest.TestCase):
    def test_every_sport_maps_to_its_legacy_family(self) -> None:
        expected = {
            Sport.RIDE: "cycling",
            Sport.RUN: "running",
            Sport.SWIM: "swimming",
            Sport.STRENGTH: "strength",
            Sport.WALK: "other",
            Sport.HIKE: "other",
            Sport.ROW: "other",
            Sport.NORDIC_SKI: "other",
            Sport.ALPINE_SKI: "other",
            Sport.YOGA: "other",
            Sport.OTHER: "other",
        }
        self.assertEqual(set(Sport), set(expected))
        for sport, family in expected.items():
            with self.subTest(sport=sport.value):
                self.assertEqual(family, legacy_activity_family(sport))

    def test_family_matches_legacy_activity_kind_for_samples(self) -> None:
        generated = tuple(
            separator.join(pair)
            for pair in product(PARITY_FRAGMENTS, repeat=2)
            for separator in (" ", "/")
        )
        for text in (*PARITY_SAMPLES, *generated):
            with self.subTest(text=text):
                expected = legacy_family(text)
                self.assertEqual(
                    expected,
                    legacy_activity_family(classify_sport_text(text)),
                )
                self.assertEqual(expected, activity_kind({"type": text}))


if __name__ == "__main__":
    unittest.main()
