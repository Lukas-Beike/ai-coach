"""Classify free text into canonical sports and environments.

The sport terms below reproduce the matching order of the legacy
``activity_kind`` helper in ``backend/activities/identity.py``. The first four
groups are the legacy families. That order is a parity requirement for existing
behaviour, not a domain decision: a term checked earlier wins even when a later
term is more specific. For example "Run/Ride" is a ride, and "Langlauf" is a run
because the legacy run term "lauf" is checked before the nordic term.

Environments are inferred only where a term names them. OUTDOOR is never
inferred from text; a mapper that knows an activity was outdoors must say so.

Matching is substring search, so it has known false positives inherited from
the legacy helper: "stride" is a ride ("ride" inside "stride"), "brunch" is a
run ("run" inside "brunch"), and "Crowd" is a row. Mappers should not rely on
this text fallback for those words; provider type keys should be mapped
explicitly where they are known.

Mappers must classify the space-joined identity text, as ``activity_kind`` does,
rather than classifying individual fields. Field-by-field classification can
disagree with the legacy result when an earlier field lacks a term that a later
field supplies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from backend.canonical.vocabulary import Environment, Sport

# Legacy families, in the order used by activity_kind. Parity requirement.
_LEGACY_CYCLING_TERMS: Final = ("ride", "bike", "cycling", "rad", "velo", "bicycle")
_LEGACY_RUNNING_TERMS: Final = ("run", "lauf", "jog")
_LEGACY_SWIMMING_TERMS: Final = ("swim", "schwimm")
_LEGACY_STRENGTH_TERMS: Final = ("strength", "kraft", "weight", "gym")

_SPORT_TERMS: Final[tuple[tuple[tuple[str, ...], Sport], ...]] = (
    (_LEGACY_CYCLING_TERMS, Sport.RIDE),
    (_LEGACY_RUNNING_TERMS, Sport.RUN),
    (_LEGACY_SWIMMING_TERMS, Sport.SWIM),
    (_LEGACY_STRENGTH_TERMS, Sport.STRENGTH),
    (("walk", "geh"), Sport.WALK),
    (("hike", "wander"), Sport.HIKE),
    (("row", "ruder"), Sport.ROW),
    (("nordic", "langlauf", "cross_country"), Sport.NORDIC_SKI),
    (("alpine", "resort_ski"), Sport.ALPINE_SKI),
    (("yoga",), Sport.YOGA),
)

_LEGACY_FAMILIES: Final[Mapping[Sport, str]] = {
    Sport.RIDE: "cycling",
    Sport.RUN: "running",
    Sport.SWIM: "swimming",
    Sport.STRENGTH: "strength",
}

_ENVIRONMENT_TERMS: Final[tuple[tuple[tuple[str, ...], Environment], ...]] = (
    (("virtual", "zwift"), Environment.VIRTUAL),
    (("indoor", "trainer", "treadmill", "laufband"), Environment.INDOOR),
)


def classify_sport_text(text: str) -> Sport:
    """Return the first sport whose legacy-ordered term appears in ``text``.

    Matching is case-insensitive substring search. Non-text input is OTHER.
    """
    if not isinstance(text, str):
        return Sport.OTHER
    folded = text.casefold()
    for terms, sport in _SPORT_TERMS:
        if any(term in folded for term in terms):
            return sport
    return Sport.OTHER


def classify_environment_text(text: str) -> Environment:
    """Return the environment named by ``text``, or UNKNOWN when none is named."""
    if not isinstance(text, str):
        return Environment.UNKNOWN
    folded = text.casefold()
    for terms, environment in _ENVIRONMENT_TERMS:
        if any(term in folded for term in terms):
            return environment
    return Environment.UNKNOWN


def legacy_activity_family(sport: Sport) -> str:
    """Return the legacy ``activity_kind`` label for a canonical sport."""
    return _LEGACY_FAMILIES.get(sport, "other")
