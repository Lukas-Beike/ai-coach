"""Read-only translation of stored equipment, competition and workout sport tokens.

Equipment, competitions and workouts keep their sport tokens exactly as saved. These
tables give the canonical ``Sport`` for read-side decisions and never rewrite a
stored value. Equipment and competition lookups are exact-token only. Workout
lookups also accept the listed free-text aliases and ignore case and separator
runs. Text that is not listed returns ``None`` (unknown), never a substring or
fuzzy guess.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from backend.canonical.vocabulary import Environment, Sport

# Every token accepted by the equipment sport validator.
EQUIPMENT_SPORT_TOKENS: Final[Mapping[str, Sport]] = {
    "Ride": Sport.RIDE,
    "VirtualRide": Sport.RIDE,
    "Run": Sport.RUN,
    "Swim": Sport.SWIM,
    "WeightTraining": Sport.STRENGTH,
    "Other": Sport.OTHER,
}

# Every Intervals.icu competition token the competition sport aliases resolve to.
COMPETITION_SPORT_TOKENS: Final[Mapping[str, Sport]] = {
    "Ride": Sport.RIDE,
    "VirtualRide": Sport.RIDE,
    "Run": Sport.RUN,
    "WeightTraining": Sport.STRENGTH,
}


DEFAULT_WORKOUT_SPORT_TOKEN: Final = "Ride"

# Free-text spellings (casefolded, separators collapsed to one space) that the
# workout library and planned units resolve to a stored workout sport token.
WORKOUT_SPORT_ALIASES: Final[Mapping[str, str]] = {
    "cycling": "Ride",
    "rad": "Ride",
    "rad outdoor": "Ride",
    "radfahren": "Ride",
    "ride": "Ride",
    "virtualride": "VirtualRide",
    "virtual ride": "VirtualRide",
    "rad indoor": "VirtualRide",
    "indoor cycling": "VirtualRide",
    "virtual cycling": "VirtualRide",
    "running": "Run",
    "lauf": "Run",
    "laufen": "Run",
    "run": "Run",
    "strength": "WeightTraining",
    "kraft": "WeightTraining",
    "krafttraining": "WeightTraining",
    "weighttraining": "WeightTraining",
    "bike": "Ride",
    "biking": "Ride",
    "bicycle": "Ride",
    "bike workout": "Ride",
    "cycling workout": "Ride",
    "swim": "Swim",
    "swimming": "Swim",
    "schwimmen": "Swim",
    "run workout": "Run",
    "jogging": "Run",
    "jog": "Run",
    "gym": "WeightTraining",
    "weights": "WeightTraining",
    "weight training": "WeightTraining",
    "hiking": "Hike",
    "walking": "Walk",
    "row": "Rowing",
    "rowing": "Rowing",
    "yoga": "Yoga",
}


def _workout_entries(
    sport: Sport, environment: Environment, tokens: tuple[str, ...]
) -> dict[str, tuple[Sport, Environment]]:
    return {token: (sport, environment) for token in tokens}


# Every stored workout sport token, with its canonical sport and environment.
# Generic tokens ("Workout", "Other") and unlisted sports are Sport.OTHER.
WORKOUT_SPORT_TOKENS: Final[Mapping[str, tuple[Sport, Environment]]] = {
    **_workout_entries(
        Sport.RIDE,
        Environment.UNKNOWN,
        (
            "Ride",
            "EBikeRide",
            "EMountainBikeRide",
            "GravelRide",
            "Handcycle",
            "MountainBikeRide",
            "Velomobile",
        ),
    ),
    **_workout_entries(Sport.RIDE, Environment.VIRTUAL, ("VirtualRide",)),
    **_workout_entries(Sport.RUN, Environment.UNKNOWN, ("Run",)),
    **_workout_entries(Sport.RUN, Environment.VIRTUAL, ("VirtualRun",)),
    **_workout_entries(Sport.RUN, Environment.OUTDOOR, ("TrailRun",)),
    **_workout_entries(Sport.SWIM, Environment.UNKNOWN, ("Swim",)),
    **_workout_entries(Sport.SWIM, Environment.OUTDOOR, ("OpenWaterSwim",)),
    **_workout_entries(Sport.WALK, Environment.UNKNOWN, ("Walk",)),
    **_workout_entries(Sport.HIKE, Environment.OUTDOOR, ("Hike",)),
    **_workout_entries(Sport.STRENGTH, Environment.UNKNOWN, ("WeightTraining",)),
    **_workout_entries(Sport.ROW, Environment.UNKNOWN, ("Rowing",)),
    **_workout_entries(Sport.ROW, Environment.VIRTUAL, ("VirtualRow",)),
    **_workout_entries(
        Sport.NORDIC_SKI, Environment.UNKNOWN, ("NordicSki", "RollerSki")
    ),
    **_workout_entries(Sport.ALPINE_SKI, Environment.UNKNOWN, ("AlpineSki",)),
    **_workout_entries(Sport.ALPINE_SKI, Environment.OUTDOOR, ("BackcountrySki",)),
    **_workout_entries(Sport.YOGA, Environment.UNKNOWN, ("Yoga",)),
    **_workout_entries(
        Sport.OTHER,
        Environment.UNKNOWN,
        (
            "Badminton",
            "Canoeing",
            "Crossfit",
            "Elliptical",
            "Golf",
            "HighIntensityIntervalTraining",
            "IceSkate",
            "InlineSkate",
            "Kayaking",
            "Kitesurf",
            "Padel",
            "Pilates",
            "Pickleball",
            "Racquetball",
            "Rugby",
            "RockClimbing",
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
            "Transition",
            "WaterSport",
            "Wheelchair",
            "Windsurf",
            "Workout",
            "Other",
        ),
    ),
}

_WORKOUT_TOKENS_BY_FOLD: Final[Mapping[str, str]] = {
    token.casefold(): token for token in WORKOUT_SPORT_TOKENS
}
_SEPARATORS: Final = re.compile(r"[\s_-]+")


def workout_stored_token(value: Any) -> str | None:
    """Return the stored workout sport token for free text, or None if unknown.

    Blank or absent text means the default token. Aliases and token spellings
    match case-insensitively; unlisted text is unknown, never guessed.
    """
    raw = str(value or DEFAULT_WORKOUT_SPORT_TOKEN).strip()
    folded = raw.casefold()
    token = WORKOUT_SPORT_ALIASES.get(folded) or WORKOUT_SPORT_ALIASES.get(
        _SEPARATORS.sub(" ", folded)
    )
    return token or _WORKOUT_TOKENS_BY_FOLD.get(folded)


def workout_canonical_sport(stored: Any) -> Sport | None:
    """Return the canonical sport of a stored workout sport, or None if unknown."""
    token = workout_stored_token(stored)
    entry = WORKOUT_SPORT_TOKENS.get(token) if token else None
    return None if entry is None else entry[0]


def workout_sport_environment(stored: Any) -> tuple[Sport, Environment] | None:
    """Return the canonical sport and environment of a stored workout sport."""
    token = workout_stored_token(stored)
    return WORKOUT_SPORT_TOKENS.get(token) if token else None


def _lookup(table: Mapping[str, Sport], token: Any) -> Sport | None:
    if not isinstance(token, str):
        return None
    return table.get(token)


def equipment_canonical_sport(record: Mapping[str, Any]) -> Sport | None:
    """Return the canonical sport of a stored equipment record, or None if unknown."""
    return _lookup(EQUIPMENT_SPORT_TOKENS, record.get("sport"))
