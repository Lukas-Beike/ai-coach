"""Stored workout sport tokens translate to canonical sports without changing wire types."""

from __future__ import annotations

import re
import unittest
from typing import Any

from backend.canonical.stored_sports import (
    WORKOUT_SPORT_ALIASES,
    WORKOUT_SPORT_TOKENS,
    resolve_workout_sport,
    workout_stored_token,
)
from backend.canonical.vocabulary import Environment, Sport
from backend.planning.sport import planned_sport_environment
from backend.providers.intervals_activity_mapping import INTERVALS_ACTIVITY_TYPES
from backend.providers.intervals_workouts import (
    INTERVALS_WORKOUT_SPORTS,
    INTERVALS_WORKOUT_TYPES,
    intervals_workout_sport,
)

# Frozen copies of the vocabulary as it was defined in the provider module.
LEGACY_TYPES = frozenset(
    (
        "Ride",
        "Run",
        "Swim",
        "WeightTraining",
        "Hike",
        "Walk",
        "AlpineSki",
        "BackcountrySki",
        "Badminton",
        "Canoeing",
        "Crossfit",
        "EBikeRide",
        "EMountainBikeRide",
        "Elliptical",
        "Golf",
        "GravelRide",
        "Handcycle",
        "HighIntensityIntervalTraining",
        "IceSkate",
        "InlineSkate",
        "Kayaking",
        "Kitesurf",
        "MountainBikeRide",
        "NordicSki",
        "OpenWaterSwim",
        "Padel",
        "Pilates",
        "Pickleball",
        "Racquetball",
        "Rugby",
        "RockClimbing",
        "RollerSki",
        "Rowing",
        "Sail",
        "Skateboard",
        "Snowboard",
        "Snowshoe",
        "Soccer",
        "Squash",
        "StairStepper",
        "StandUpPaddling",
        "Surfing",
        "TableTennis",
        "Tennis",
        "TrailRun",
        "Transition",
        "Velomobile",
        "VirtualRide",
        "VirtualRow",
        "VirtualRun",
        "WaterSport",
        "Wheelchair",
        "Windsurf",
        "Workout",
        "Yoga",
        "Other",
    )
)
# fmt: off
LEGACY_ALIASES = {
    "cycling": "Ride", "rad": "Ride", "rad outdoor": "Ride", "radfahren": "Ride",
    "ride": "Ride", "virtualride": "VirtualRide", "virtual ride": "VirtualRide",
    "rad indoor": "VirtualRide", "indoor cycling": "VirtualRide",
    "virtual cycling": "VirtualRide", "running": "Run", "lauf": "Run",
    "laufen": "Run", "run": "Run", "strength": "WeightTraining",
    "kraft": "WeightTraining", "krafttraining": "WeightTraining",
    "weighttraining": "WeightTraining", "bike": "Ride", "biking": "Ride",
    "bicycle": "Ride", "bike workout": "Ride", "cycling workout": "Ride",
    "swim": "Swim", "swimming": "Swim", "schwimmen": "Swim",
    "run workout": "Run", "jogging": "Run", "jog": "Run",
    "gym": "WeightTraining", "weights": "WeightTraining",
    "weight training": "WeightTraining", "hiking": "Hike", "walking": "Walk",
    "row": "Rowing", "rowing": "Rowing", "yoga": "Yoga",
}
# fmt: on


def legacy_wire_type(value: Any) -> str:
    raw = str(value or "Ride").strip()
    normalized = re.sub(r"[\s_-]+", " ", raw.casefold())
    found = LEGACY_ALIASES.get(raw.casefold()) or LEGACY_ALIASES.get(normalized)
    if found:
        return found
    for activity_type in LEGACY_TYPES:
        if activity_type.casefold() == raw.casefold():
            return activity_type
    return "Other"


def spellings() -> list[Any]:
    values: list[Any] = [None, "", "  ", "new activity", "Curling", 0, 7]
    for alias in LEGACY_ALIASES:
        values += [alias, alias.upper(), f"  {alias.title()} "]
        values += [alias.replace(" ", "-"), alias.replace(" ", "_")]
    for token in LEGACY_TYPES:
        values += [token, token.lower(), token.upper(), f" {token} "]
    values += ["Rad-Indoor", "trailrun", "Virtual  Ride"]
    return values


class WorkoutSportParityTest(unittest.TestCase):
    def test_vocabulary_is_unchanged(self) -> None:
        self.assertEqual(INTERVALS_WORKOUT_TYPES, LEGACY_TYPES)
        self.assertEqual(dict(INTERVALS_WORKOUT_SPORTS), LEGACY_ALIASES)
        self.assertEqual(set(WORKOUT_SPORT_TOKENS), LEGACY_TYPES)
        self.assertEqual(dict(WORKOUT_SPORT_ALIASES), LEGACY_ALIASES)

    def test_every_alias_targets_a_stored_token(self) -> None:
        self.assertLessEqual(
            set(WORKOUT_SPORT_ALIASES.values()), set(WORKOUT_SPORT_TOKENS)
        )

    def test_wire_type_matches_legacy_for_every_spelling(self) -> None:
        for value in spellings():
            with self.subTest(value=value):
                self.assertEqual(
                    intervals_workout_sport(value), legacy_wire_type(value)
                )

    def test_alias_to_stored_to_canonical_chain(self) -> None:
        for alias, token in LEGACY_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertEqual(workout_stored_token(alias), token)
                self.assertEqual(intervals_workout_sport(alias), token)
                resolved = resolve_workout_sport(alias)
                assert resolved is not None
                self.assertEqual(
                    (resolved.sport, resolved.environment),
                    WORKOUT_SPORT_TOKENS[token],
                )

    def test_environment_matches_legacy_activity_table(self) -> None:
        for value in spellings():
            with self.subTest(value=value):
                legacy = INTERVALS_ACTIVITY_TYPES.get(
                    legacy_wire_type(value), (Sport.OTHER, Environment.UNKNOWN)
                )
                self.assertEqual(planned_sport_environment({"type": value}), legacy)

    def test_unknown_text_is_none_and_wires_as_other(self) -> None:
        self.assertIsNone(workout_stored_token("Curling"))
        self.assertIsNone(resolve_workout_sport("Curling"))
        self.assertEqual(intervals_workout_sport("Curling"), "Other")

    def test_blank_defaults_to_ride(self) -> None:
        for blank in (None, ""):
            resolved = resolve_workout_sport(blank)
            assert resolved is not None
            self.assertEqual(resolved.sport, Sport.RIDE)

    def test_generic_tokens_are_other(self) -> None:
        for token in ("Workout", "Other", "Golf"):
            resolved = resolve_workout_sport(token)
            assert resolved is not None
            self.assertEqual(resolved.sport, Sport.OTHER)


if __name__ == "__main__":
    unittest.main()
