"""Read-only canonical sport translation for stored equipment and competitions."""

from __future__ import annotations

import unittest
from typing import Any

from backend.athlete.equipment import EQUIPMENT_SPORTS
from backend.canonical.stored_sports import (
    COMPETITION_SPORT_TOKENS,
    EQUIPMENT_SPORT_TOKENS,
    competition_canonical_sport,
    equipment_canonical_sport,
)
from backend.canonical.vocabulary import Sport
from backend.planning.competitions import COMPETITION_SPORTS


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


EXPECTED_EQUIPMENT: dict[str, Sport] = {
    "Ride": Sport.RIDE,
    "VirtualRide": Sport.RIDE,
    "Run": Sport.RUN,
    "Swim": Sport.SWIM,
    "WeightTraining": Sport.STRENGTH,
    "Other": Sport.OTHER,
}

EXPECTED_COMPETITION: dict[str, Sport] = {
    "Ride": Sport.RIDE,
    "VirtualRide": Sport.RIDE,
    "Run": Sport.RUN,
    "WeightTraining": Sport.STRENGTH,
}


class StoredEquipmentSportTests(unittest.TestCase):
    def test_every_allowed_equipment_token_maps_to_a_canonical_sport(self) -> None:
        self.assertEqual(
            set(EQUIPMENT_SPORTS),
            {"Ride", "VirtualRide", "Run", "Swim", "WeightTraining", "Other"},
        )
        self.assertEqual(set(EQUIPMENT_SPORTS), set(EQUIPMENT_SPORT_TOKENS))
        for token in EQUIPMENT_SPORTS:
            with self.subTest(token=token):
                self.assertIsInstance(EQUIPMENT_SPORT_TOKENS[token], Sport)

    def test_equipment_translation_table_is_exact(self) -> None:
        self.assertEqual(dict(EQUIPMENT_SPORT_TOKENS), EXPECTED_EQUIPMENT)

    def test_equipment_accessor_reads_the_stored_sport_token(self) -> None:
        for token, sport in EXPECTED_EQUIPMENT.items():
            with self.subTest(token=token):
                self.assertIs(equipment_canonical_sport({"sport": token}), sport)

    def test_equipment_accessor_returns_none_for_unknown_or_non_text_tokens(
        self,
    ) -> None:
        unknown: list[Any] = [
            None,
            "",
            "Workout",
            "ride",
            "Virtual Ride",
            "Cycling",
            "Bike",
            "Running",
            "Strength",
            untyped(5),
            untyped(["Ride"]),
        ]
        for token in unknown:
            with self.subTest(token=token):
                self.assertIsNone(equipment_canonical_sport({"sport": token}))

    def test_equipment_accessor_returns_none_when_sport_is_missing(self) -> None:
        self.assertIsNone(equipment_canonical_sport({}))


class StoredCompetitionSportTests(unittest.TestCase):
    def test_every_competition_token_maps_to_a_canonical_sport(self) -> None:
        self.assertEqual(
            set(COMPETITION_SPORTS.values()), set(COMPETITION_SPORT_TOKENS)
        )
        for token in COMPETITION_SPORT_TOKENS:
            with self.subTest(token=token):
                self.assertIsInstance(COMPETITION_SPORT_TOKENS[token], Sport)

    def test_competition_translation_table_is_exact(self) -> None:
        self.assertEqual(dict(COMPETITION_SPORT_TOKENS), EXPECTED_COMPETITION)

    def test_competition_accessor_reads_the_stored_sport_token(self) -> None:
        for token, sport in EXPECTED_COMPETITION.items():
            with self.subTest(token=token):
                self.assertIs(competition_canonical_sport({"sport": token}), sport)

    def test_competition_accessor_does_not_guess_from_aliases_or_substrings(
        self,
    ) -> None:
        unknown: list[Any] = [
            None,
            "Cycling",
            "cycling",
            "Lauf",
            "Swim",
            "Other",
            "Virtual Ride",
            "Weight Training",
            "Running race",
            untyped(7),
        ]
        for token in unknown:
            with self.subTest(token=token):
                self.assertIsNone(competition_canonical_sport({"sport": token}))

    def test_competition_accessor_returns_none_when_sport_is_missing(self) -> None:
        self.assertIsNone(competition_canonical_sport({"name": "Race"}))
