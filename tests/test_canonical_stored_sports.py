"""Canonical stored sport translation for equipment, competitions and workouts."""

from __future__ import annotations

import unittest
from typing import Any

from backend.canonical.stored_sports import (
    EQUIPMENT_SPORTS,
    LEGACY_COMPETITION_TOKENS,
    LEGACY_EQUIPMENT_TOKENS,
    StoredSport,
    legacy_workout_sport,
    resolve_competition_sport,
    resolve_equipment_sport,
    resolve_workout_sport,
    workout_sport_from_record,
)
from backend.canonical.vocabulary import Environment, Sport
from backend.planning.competitions import (
    COMPETITION_SPORTS,
    competition_canonical_sport,
    competition_normalized_text_fields,
    competition_stored_sport,
)
from backend.providers.intervals_workouts import (
    intervals_competition_type,
    intervals_record_type,
    intervals_workout_type,
)

UNKNOWN = Environment.UNKNOWN


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


EXPECTED_EQUIPMENT: dict[str, StoredSport] = {
    "Ride": StoredSport(Sport.RIDE, UNKNOWN),
    "VirtualRide": StoredSport(Sport.RIDE, Environment.VIRTUAL),
    "Run": StoredSport(Sport.RUN, UNKNOWN),
    "Swim": StoredSport(Sport.SWIM, UNKNOWN),
    "WeightTraining": StoredSport(Sport.STRENGTH, UNKNOWN),
    "Other": StoredSport(Sport.OTHER, UNKNOWN),
}


class StoredEquipmentSportTests(unittest.TestCase):
    def test_equipment_tokens_translate_to_the_exact_canonical_pair(self) -> None:
        self.assertEqual(
            {
                token: (stored.sport, stored.environment)
                for token, stored in EXPECTED_EQUIPMENT.items()
            },
            dict(LEGACY_EQUIPMENT_TOKENS),
        )
        for token, expected in EXPECTED_EQUIPMENT.items():
            with self.subTest(token=token):
                self.assertEqual(resolve_equipment_sport(token), expected)

    def test_canonical_equipment_values_are_accepted_with_an_environment(self) -> None:
        self.assertEqual(
            resolve_equipment_sport("ride", "virtual"),
            StoredSport(Sport.RIDE, Environment.VIRTUAL),
        )
        for sport in EQUIPMENT_SPORTS:
            with self.subTest(sport=sport):
                self.assertEqual(
                    resolve_equipment_sport(sport.value),
                    StoredSport(sport, UNKNOWN),
                )

    def test_unknown_or_non_text_equipment_sports_are_not_resolved(self) -> None:
        unknown: list[Any] = [
            None,
            "",
            "Workout",
            "Virtual Ride",
            "Cycling",
            "Bike",
            "Running",
            "walk",
            untyped(5),
            untyped(["Ride"]),
        ]
        for token in unknown:
            with self.subTest(token=token):
                self.assertIsNone(resolve_equipment_sport(token))


class StoredCompetitionSportTests(unittest.TestCase):
    def test_competition_tokens_translate_to_the_exact_canonical_pair(self) -> None:
        self.assertEqual(
            dict(LEGACY_COMPETITION_TOKENS),
            {
                "Ride": (Sport.RIDE, UNKNOWN),
                "VirtualRide": (Sport.RIDE, Environment.VIRTUAL),
                "Run": (Sport.RUN, UNKNOWN),
                "WeightTraining": (Sport.STRENGTH, UNKNOWN),
            },
        )
        self.assertEqual(
            set(COMPETITION_SPORTS.values()), set(LEGACY_COMPETITION_TOKENS)
        )

    def test_competition_accessor_reads_canonical_and_legacy_values(self) -> None:
        stored = {
            "ride": Sport.RIDE,
            "Ride": Sport.RIDE,
            "Cycling": Sport.RIDE,
            "Rad": Sport.RIDE,
            "Virtual Ride": Sport.RIDE,
            "rad indoor": Sport.RIDE,
            "Running": Sport.RUN,
            "Lauf": Sport.RUN,
            "Strength": Sport.STRENGTH,
            "Krafttraining": Sport.STRENGTH,
        }
        for token, sport in stored.items():
            with self.subTest(token=token):
                self.assertIs(competition_canonical_sport({"sport": token}), sport)

    def test_virtual_ride_keeps_its_environment_and_provider_type(self) -> None:
        stored = resolve_competition_sport("VirtualRide")
        assert stored is not None
        self.assertEqual(stored, StoredSport(Sport.RIDE, Environment.VIRTUAL))
        self.assertEqual(intervals_competition_type(stored), "VirtualRide")
        self.assertEqual(
            intervals_competition_type(StoredSport(Sport.RIDE, UNKNOWN)), "Ride"
        )

    def test_default_competition_sport_is_canonical(self) -> None:
        self.assertNotIn("sport", competition_normalized_text_fields({}))
        self.assertEqual(competition_stored_sport({}), StoredSport(Sport.RIDE, UNKNOWN))

    def test_competition_accessor_does_not_guess_from_substrings(self) -> None:
        unknown: list[Any] = [
            None,
            "",
            "Swim",
            "Other",
            "Weight Training",
            "Running race",
            untyped(7),
        ]
        for token in unknown:
            with self.subTest(token=token):
                self.assertIsNone(competition_canonical_sport({"sport": token}))

    def test_unsupported_competition_text_is_kept_losslessly(self) -> None:
        self.assertEqual(
            competition_stored_sport({"sport": "Obstacle course"}),
            StoredSport(Sport.OTHER, UNKNOWN, "Obstacle course"),
        )


class StoredWorkoutSportTests(unittest.TestCase):
    def test_legacy_tokens_translate_and_round_trip_to_the_provider_type(self) -> None:
        for token in ("Ride", "VirtualRide", "Run", "Swim", "WeightTraining", "Hike"):
            with self.subTest(token=token):
                stored = resolve_workout_sport(token)
                assert stored is not None
                self.assertEqual(intervals_workout_type(stored), token)
                self.assertEqual(intervals_record_type(stored_record(stored)), token)

    def test_virtual_ride_is_the_virtual_environment(self) -> None:
        stored = resolve_workout_sport("VirtualRide")
        assert stored is not None
        self.assertEqual(
            (stored.sport, stored.environment), (Sport.RIDE, Environment.VIRTUAL)
        )

    def test_indoor_workouts_use_the_virtual_provider_type_like_competitions(
        self,
    ) -> None:
        for sport in (Sport.RIDE, Sport.RUN):
            with self.subTest(sport=sport):
                indoor = StoredSport(sport, Environment.INDOOR)
                virtual = StoredSport(sport, Environment.VIRTUAL)
                self.assertEqual(
                    intervals_workout_type(indoor), intervals_workout_type(virtual)
                )
                self.assertEqual(
                    intervals_competition_type(indoor),
                    intervals_competition_type(virtual),
                )
        self.assertEqual(
            intervals_workout_type(StoredSport(Sport.RIDE, Environment.INDOOR)),
            "VirtualRide",
        )

    def test_specific_token_survives_as_detail(self) -> None:
        stored = legacy_workout_sport("GravelRide")
        self.assertEqual(stored.sport, Sport.RIDE)
        self.assertEqual(stored.detail, "GravelRide")
        self.assertEqual(intervals_workout_type(stored), "GravelRide")

    def test_unresolvable_text_is_kept_losslessly(self) -> None:
        stored = legacy_workout_sport("Basket weaving")
        self.assertEqual(stored, StoredSport(Sport.OTHER, UNKNOWN, "Basket weaving"))
        self.assertEqual(intervals_workout_type(stored), "Other")

    def test_record_reads_canonical_and_legacy_fields(self) -> None:
        canonical = workout_sport_from_record(
            {"sport": "ride", "environment": "virtual"}
        )
        legacy = workout_sport_from_record({"type": "VirtualRide"})
        self.assertEqual(canonical.sport, legacy.sport)
        self.assertEqual(canonical.environment, legacy.environment)
        self.assertEqual(
            intervals_record_type({"sport": "run", "environment": "unknown"}), "Run"
        )

    def test_a_record_without_sport_uses_the_default(self) -> None:
        self.assertEqual(intervals_record_type({}), "Ride")


def stored_record(stored: StoredSport) -> dict[str, Any]:
    return stored.fields()


if __name__ == "__main__":
    unittest.main()
