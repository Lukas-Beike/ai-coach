"""Canonical sport storage and the legacy sport-token translation table.

Equipment, competitions, workouts and planned units store a canonical ``Sport``
and ``Environment`` (schema version 9). Earlier schemas stored Intervals.icu
style tokens (``Ride``, ``VirtualRide``, ``WeightTraining`` ...) or free text.
This module owns the translation of those legacy tokens: the schema migration
rewrites every stored value through it, and API input that still carries a
legacy token is translated through it at the boundary. Only the Intervals.icu
adapter maps canonical values back to provider types.

A ``StoredSport`` keeps the original token losslessly in ``detail`` whenever the
canonical pair alone cannot reproduce it (``GravelRide`` is ``Sport.RIDE`` with
an unknown environment, like ``Ride``; unresolvable free text is
``Sport.OTHER``). Text that is not listed is never guessed from substrings.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from backend.canonical.vocabulary import Environment, Sport


@dataclass(frozen=True, slots=True)
class StoredSport:
    """Canonical sport and environment of a stored record, plus kept original text."""

    sport: Sport
    environment: Environment = Environment.UNKNOWN
    detail: str | None = None

    def fields(self) -> dict[str, str]:
        """Return the stored members: sport, environment and optional detail."""
        result = {"sport": self.sport.value, "environment": self.environment.value}
        if self.detail:
            result["sport_detail"] = self.detail
        return result


DEFAULT_WORKOUT_SPORT: Final = StoredSport(Sport.RIDE, Environment.UNKNOWN)
# Legacy default token of blank workout sport text.
DEFAULT_WORKOUT_SPORT_TOKEN: Final = "Ride"

# Every token accepted by the legacy equipment sport validator.
LEGACY_EQUIPMENT_TOKENS: Final[Mapping[str, tuple[Sport, Environment]]] = {
    "Ride": (Sport.RIDE, Environment.UNKNOWN),
    "VirtualRide": (Sport.RIDE, Environment.VIRTUAL),
    "Run": (Sport.RUN, Environment.UNKNOWN),
    "Swim": (Sport.SWIM, Environment.UNKNOWN),
    "WeightTraining": (Sport.STRENGTH, Environment.UNKNOWN),
    "Other": (Sport.OTHER, Environment.UNKNOWN),
}

# Every legacy competition token the competition sport aliases resolve to.
LEGACY_COMPETITION_TOKENS: Final[Mapping[str, tuple[Sport, Environment]]] = {
    "Ride": (Sport.RIDE, Environment.UNKNOWN),
    "VirtualRide": (Sport.RIDE, Environment.VIRTUAL),
    "Run": (Sport.RUN, Environment.UNKNOWN),
    "WeightTraining": (Sport.STRENGTH, Environment.UNKNOWN),
}

# Free-text competition spellings (casefolded, separators collapsed to one space).
LEGACY_COMPETITION_ALIASES: Final[Mapping[str, str]] = {
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
}

# Free-text spellings (casefolded, separators collapsed to one space) that the
# workout library and planned units resolve to a legacy workout sport token.
WORKOUT_SPORT_ALIASES: Final[Mapping[str, str]] = {
    **LEGACY_COMPETITION_ALIASES,
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


# Every legacy workout sport token, with its canonical sport and environment.
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

# The legacy token that a canonical pair stands for without any kept detail.
PRIMARY_WORKOUT_TOKENS: Final[Mapping[tuple[Sport, Environment], str]] = {
    (Sport.RIDE, Environment.UNKNOWN): "Ride",
    (Sport.RIDE, Environment.VIRTUAL): "VirtualRide",
    (Sport.RUN, Environment.UNKNOWN): "Run",
    (Sport.RUN, Environment.VIRTUAL): "VirtualRun",
    (Sport.RUN, Environment.OUTDOOR): "TrailRun",
    (Sport.SWIM, Environment.UNKNOWN): "Swim",
    (Sport.SWIM, Environment.OUTDOOR): "OpenWaterSwim",
    (Sport.WALK, Environment.UNKNOWN): "Walk",
    (Sport.HIKE, Environment.OUTDOOR): "Hike",
    (Sport.HIKE, Environment.UNKNOWN): "Hike",
    (Sport.STRENGTH, Environment.UNKNOWN): "WeightTraining",
    (Sport.ROW, Environment.UNKNOWN): "Rowing",
    (Sport.ROW, Environment.VIRTUAL): "VirtualRow",
    (Sport.NORDIC_SKI, Environment.UNKNOWN): "NordicSki",
    (Sport.ALPINE_SKI, Environment.UNKNOWN): "AlpineSki",
    (Sport.ALPINE_SKI, Environment.OUTDOOR): "BackcountrySki",
    (Sport.YOGA, Environment.UNKNOWN): "Yoga",
    (Sport.OTHER, Environment.UNKNOWN): "Other",
}

# Canonical sports a competition or a piece of equipment can be stored with.
COMPETITION_SPORTS: Final = frozenset({Sport.RIDE, Sport.RUN, Sport.STRENGTH})
EQUIPMENT_SPORTS: Final = frozenset(
    {Sport.RIDE, Sport.RUN, Sport.SWIM, Sport.STRENGTH, Sport.OTHER}
)

_WORKOUT_TOKENS_BY_FOLD: Final[Mapping[str, str]] = {
    token.casefold(): token for token in WORKOUT_SPORT_TOKENS
}
_SPORTS_BY_VALUE: Final[Mapping[str, Sport]] = {item.value: item for item in Sport}
_ENVIRONMENTS_BY_VALUE: Final[Mapping[str, Environment]] = {
    item.value: item for item in Environment
}
_SEPARATORS: Final = re.compile(r"[\s_-]+")


def parse_environment(value: Any) -> Environment | None:
    """Return the canonical environment named by a stored or submitted value."""
    if isinstance(value, Environment):
        return value
    if not isinstance(value, str):
        return None
    return _ENVIRONMENTS_BY_VALUE.get(value.strip().casefold())


def activity_type_environment(environment: Environment) -> Environment:
    """Return the environment an activity type can tell apart.

    Activity types only distinguish virtual from unspecified, so indoor counts as
    virtual and outdoor as unspecified when stored sports are compared.
    """
    if environment is Environment.INDOOR:
        return Environment.VIRTUAL
    if environment is Environment.OUTDOOR:
        return Environment.UNKNOWN
    return environment


def _canonical_sport(value: Any) -> Sport | None:
    if isinstance(value, Sport):
        return value
    if not isinstance(value, str):
        return None
    return _SPORTS_BY_VALUE.get(value.strip().casefold())


def workout_stored_token(value: Any) -> str | None:
    """Return the legacy workout sport token for free text, or None if unknown.

    Blank or absent text means the default token. Aliases and token spellings
    match case-insensitively; unlisted text is unknown, never guessed.
    """
    raw = str(value or DEFAULT_WORKOUT_SPORT_TOKEN).strip()
    folded = raw.casefold()
    token = WORKOUT_SPORT_ALIASES.get(folded) or WORKOUT_SPORT_ALIASES.get(
        _SEPARATORS.sub(" ", folded)
    )
    return token or _WORKOUT_TOKENS_BY_FOLD.get(folded)


def _from_workout_token(token: str) -> StoredSport:
    sport, environment = WORKOUT_SPORT_TOKENS[token]
    primary = PRIMARY_WORKOUT_TOKENS.get((sport, environment))
    return StoredSport(sport, environment, None if token == primary else token)


def _kept_detail(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def resolve_workout_sport(
    value: Any, environment: Any = None, detail: Any = None
) -> StoredSport | None:
    """Return the canonical sport of a canonical value, legacy token or alias.

    ``environment`` and ``detail`` accompany a canonical value. A legacy token
    carries its own environment; an explicit environment only refines a token
    whose environment is unknown. Unknown text returns None.
    """
    exact_token = isinstance(value, str) and value.strip() in WORKOUT_SPORT_TOKENS
    canonical = None if exact_token else _canonical_sport(value)
    explicit = parse_environment(environment)
    if canonical is not None:
        if explicit is None:
            # A bare canonical value spelled like a legacy token ("hike") keeps
            # that token's environment.
            folded = _WORKOUT_TOKENS_BY_FOLD.get(canonical.value)
            explicit = WORKOUT_SPORT_TOKENS[folded][1] if folded else None
        return StoredSport(
            canonical, explicit or Environment.UNKNOWN, _kept_detail(detail)
        )
    token = workout_stored_token(value)
    if token is None:
        return None
    resolved = _from_workout_token(token)
    if explicit is not None and resolved.environment is Environment.UNKNOWN:
        return StoredSport(resolved.sport, explicit, resolved.detail)
    return resolved


def legacy_workout_sport(value: Any) -> StoredSport:
    """Translate stored legacy workout text; unresolvable text is kept in detail."""
    resolved = resolve_workout_sport(value)
    if resolved is not None:
        return resolved
    return StoredSport(Sport.OTHER, Environment.UNKNOWN, _kept_detail(value))


def workout_sport_from_record(record: Mapping[str, Any]) -> StoredSport:
    """Read the sport of a workout record in canonical or legacy representation.

    A canonical ``sport`` brings its ``environment`` and ``sport_detail``.
    Otherwise the legacy ``sport`` or ``type`` token is translated, and text
    that cannot be resolved is kept in the detail. Blank records mean the
    default workout sport.
    """
    raw = record.get("sport") or record.get("type")
    if not raw:
        return DEFAULT_WORKOUT_SPORT
    resolved = resolve_workout_sport(
        raw, record.get("environment"), record.get("sport_detail")
    )
    return resolved if resolved is not None else legacy_workout_sport(raw)


def legacy_competition_token(value: Any) -> str | None:
    """Return the legacy competition token that free text resolves to, if any."""
    raw = str(value or "").strip().casefold()
    return LEGACY_COMPETITION_ALIASES.get(raw) or LEGACY_COMPETITION_ALIASES.get(
        _SEPARATORS.sub(" ", raw)
    )


def resolve_competition_sport(
    value: Any, environment: Any = None
) -> StoredSport | None:
    """Return the supported canonical competition sport, or None if unsupported."""
    canonical = _canonical_sport(value)
    if canonical in COMPETITION_SPORTS:
        assert canonical is not None
        return StoredSport(
            canonical, parse_environment(environment) or Environment.UNKNOWN
        )
    token = legacy_competition_token(value)
    if token is None:
        return None
    sport, token_environment = LEGACY_COMPETITION_TOKENS[token]
    return StoredSport(sport, token_environment)


def legacy_competition_sport(value: Any) -> StoredSport:
    """Translate stored legacy competition text; unsupported text is kept in detail."""
    resolved = resolve_competition_sport(value)
    if resolved is not None:
        return resolved
    return StoredSport(Sport.OTHER, Environment.UNKNOWN, _kept_detail(value))


def resolve_equipment_sport(value: Any, environment: Any = None) -> StoredSport | None:
    """Return the canonical equipment sport of a canonical value or legacy token."""
    canonical = _canonical_sport(value)
    explicit = parse_environment(environment)
    if canonical in EQUIPMENT_SPORTS:
        assert canonical is not None
        return StoredSport(canonical, explicit or Environment.UNKNOWN)
    entry = LEGACY_EQUIPMENT_TOKENS.get(value) if isinstance(value, str) else None
    if entry is None:
        return None
    return StoredSport(entry[0], explicit or entry[1])
